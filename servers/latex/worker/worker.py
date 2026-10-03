#!/usr/bin/env python3
"""LaTeX sandbox worker. Stateless: runs ONE allow-listed tool per request in a throwaway directory.

Trust model: the request body (project files, options) is untrusted. This process has no persistent data,
no secrets and (via compose) no network. It never uses a shell and never takes raw command-line arguments
from the caller: every tool builds its own argv from validated parameters.

POST /run  {"tool": str, "args": {...}, "files_b64": <tar.gz, base64>, "timeout": int}
        -> {"ok", "returncode", "timed_out", "stdout", "stderr", "outputs": {relpath: base64}, "error"}
GET /health
"""

import asyncio
import base64
import io
import os
import re
import resource
import shutil
import signal
import tarfile
import tempfile
import uuid
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

JOBS_DIR = Path(os.getenv("WORKER_JOBS_DIR", "/tmp/jobs"))
# One job at a time by default: LuaTeX/biber can read any file the worker uid can, so jobs must not share the
# filesystem concurrently. Raise only if every file in the worker is non-sensitive.
CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "1"))
MAX_REQUEST_BYTES = int(os.getenv("WORKER_MAX_REQUEST_MB", "64")) * 1024 * 1024
MAX_FILES = 2000
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_OUTPUT_BYTES = 40 * 1024 * 1024
LOG_CAP = 1024 * 1024
MAX_TIMEOUT = 180
STREAM_CAP = 64 * 1024
# Job-private dirs. NOT dot-prefixed: openin_any=p forbids dotfiles, which breaks luaotfload's font cache.
SYS_DIRS = ("_sys_home", "_sys_texmf-var", "_sys_texmf-config", "_sys_tmp")
AS_LIMIT = 4 * 1024**3

REL = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_@+=,.\- /]{1,200}$")
ENGINES = {"pdflatex", "xelatex", "lualatex"}
PANDOC_FROM = {"latex", "markdown", "gfm", "html", "docx", "rst", "org", "odt", "plain"}
# docx/odt are accepted as INPUT only: producing them needs template files that --sandbox forbids reading.
PANDOC_TO = {"latex", "markdown", "gfm", "html", "rst", "org", "plain"}

ENABLE_LUALATEX = os.getenv("LATEX_ENABLE_LUALATEX", "true").lower() not in ("0", "false", "no")
_sem = asyncio.Semaphore(CONCURRENCY)


class JobError(Exception):
    """Invalid request; message is safe to return."""


# ---- input handling ------------------------------------------------------------------------------

def safe_rel(path: str, *, must_exist_in: Path | None = None, suffix: str | None = None) -> str:
    if not isinstance(path, str) or not REL.match(path) or path.startswith("-"):
        raise JobError("invalid path")
    if any(part.startswith("-") for part in path.split("/")):
        raise JobError("invalid path")
    if suffix and not path.lower().endswith(suffix):
        raise JobError(f"path must end with {suffix}")
    if must_exist_in is not None and not (must_exist_in / path).is_file():
        raise JobError(f"file not found: {path}")
    return path


def unpack(files_b64: str, dest: Path) -> None:
    """Extract an untrusted tar.gz: regular files/dirs only, bounded count and size, no escapes."""
    try:
        raw = base64.b64decode(files_b64, validate=True)
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")
    except Exception as e:  # noqa: BLE001
        raise JobError("invalid project archive") from e
    total = 0
    members = tf.getmembers()
    if len(members) > MAX_FILES:
        raise JobError("too many files")
    root = dest.resolve()
    for m in members:
        name = m.name.lstrip("./")
        if not name:
            continue
        if not (m.isreg() or m.isdir()):
            raise JobError(f"unsupported entry type in archive: {m.name}")
        if name.startswith("/") or ".." in Path(name).parts:
            raise JobError("path escape in archive")
        target = (root / name).resolve()
        if root not in target.parents and target != root:
            raise JobError("path escape in archive")
        if m.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if m.size > MAX_FILE_BYTES:
            raise JobError("file too large")
        total += m.size
        if total > MAX_UNPACKED_BYTES:
            raise JobError("project too large")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tf.extractfile(m) as src, open(target, "wb") as out:  # type: ignore[arg-type]
            shutil.copyfileobj(src, out, 1024 * 1024)
        os.chmod(target, 0o644)


# ---- process execution ---------------------------------------------------------------------------

def _limits(cpu_seconds: int):
    def apply():
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 2))
        resource.setrlimit(resource.RLIMIT_AS, (AS_LIMIT, AS_LIMIT))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES * 2, MAX_FILE_BYTES * 2))
        resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
        resource.setrlimit(resource.RLIMIT_NPROC, (512, 512))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def _env(job: Path) -> dict[str, str]:
    for d in SYS_DIRS:
        (job / d).mkdir(exist_ok=True)
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(job / "_sys_home"),
        "TMPDIR": str(job / "_sys_tmp"),
        "TEXMFVAR": str(job / "_sys_texmf-var"),
        "TEXMFCONFIG": str(job / "_sys_texmf-config"),
        "LC_ALL": "C.UTF-8",
        # Belt and braces with the engine flags: no shell escape, paranoid file access.
        "shell_escape": "f",
        "shell_escape_commands": "",
        "openin_any": "p",
        "openout_any": "p",
        "max_print_line": "10000",
        "error_line": "254",
        "half_error_line": "238",
        "SOURCE_DATE_EPOCH": "315532800",
    }


async def run(argv: list[str], cwd: Path, timeout: int, job: Path, stdin: bytes | None = None) -> dict:
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=_env(job), stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, preexec_fn=_limits(timeout + 5),
    )
    timed_out = False

    async def pump(stream) -> bytes:
        buf = bytearray()
        while chunk := await stream.read(65536):
            if len(buf) < STREAM_CAP:
                buf.extend(chunk[: STREAM_CAP - len(buf)])
        return bytes(buf)

    out_t, err_t = asyncio.create_task(pump(proc.stdout)), asyncio.create_task(pump(proc.stderr))
    try:
        if stdin is not None:
            proc.stdin.write(stdin)
            await proc.stdin.drain()
            proc.stdin.close()
        await asyncio.wait_for(proc.wait(), timeout)
    except asyncio.TimeoutError:
        timed_out = True
    finally:
        # Kill the whole session, even on normal exit, so nothing outlives the job.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        if proc.returncode is None:
            await proc.wait()
    stdout, stderr = await asyncio.gather(out_t, err_t)
    return {"returncode": proc.returncode, "timed_out": timed_out,
            "stdout": stdout.decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace")}


# ---- tools ---------------------------------------------------------------------------------------

def _snapshot(job: Path) -> dict[str, tuple[int, int]]:
    snap = {}
    for p in job.rglob("*"):
        if p.is_file() and not p.is_symlink() and p.relative_to(job).parts[0] not in SYS_DIRS:
            st = p.stat()
            snap[str(p.relative_to(job))] = (st.st_size, st.st_mtime_ns)
    return snap


def _collect(job: Path, before: dict, want) -> dict[str, str]:
    """Return new/changed regular files (never symlinks) accepted by `want(relpath)`, size-capped."""
    outputs, total = {}, 0
    for rel, sig in _snapshot(job).items():
        if before.get(rel) == sig or not want(rel):
            continue
        p = job / rel
        if p.is_symlink() or not p.is_file():
            continue
        size = p.stat().st_size
        if rel.endswith((".log", ".blg")) and size > LOG_CAP:
            # A runaway document can write a huge log; keep head and tail, never fail the job for it.
            with p.open("rb") as fh:
                head = fh.read(LOG_CAP // 2)
                fh.seek(max(size - LOG_CAP // 2, LOG_CAP // 2))
                tail = fh.read()
            data = head + f"\n[... log truncated: {size - len(head) - len(tail)} bytes omitted ...]\n".encode() + tail
        else:
            data = p.read_bytes()
        total += len(data)
        if total > MAX_OUTPUT_BYTES:
            raise JobError("output too large")
        outputs[rel] = base64.b64encode(data).decode()
    return outputs


def tool_compile(job: Path, a: dict, timeout: int):
    engine = a.get("engine", "pdflatex")
    if engine not in ENGINES:
        raise JobError("engine must be pdflatex, xelatex or lualatex")
    main = safe_rel(a.get("main", ""), must_exist_in=job, suffix=".tex")
    common = "-interaction=nonstopmode -file-line-error -no-shell-escape"
    argv = ["latexmk", "-norc", "-cd", "-outdir=_build", "-f", "-silent", "-e", "$max_repeat=6;", "-e", "$biber='safe-biber %O %S';"]
    if engine == "pdflatex":
        argv += ["-pdf", f"-pdflatex=pdflatex {common} %O %S"]
    elif engine == "xelatex":
        argv += ["-xelatex", f"-xelatex=xelatex {common} %O %S"]
    else:
        # Neither --safer nor openin_any=p can be used: luaotfload refuses to start under either (verified).
        # So only the lualatex process runs with openin_any=r; bibtex/biber in the same build stay strict.
        # LuaTeX's Lua can therefore read any file the worker uid can see -> the container is the boundary
        # (no secrets, no network, read-only root, one job at a time). shell_escape=f still disables os.execute/io.popen.
        if not ENABLE_LUALATEX:
            raise JobError("lualatex is disabled on this server (LATEX_ENABLE_LUALATEX=false)")
        argv += ["-lualatex", f"-lualatex=env openin_any=r lualatex {common} %O %S"]
    argv += [main]  # safe_rel() already rejects any path starting with "-"
    return [argv], lambda r: "/_build/" in "/" + r and re.search(r"\.(pdf|log|bbl|blg|bcf|aux)$", r) is not None


def tool_chktex(job: Path, a: dict, timeout: int):
    path = safe_rel(a.get("path", ""), must_exist_in=job, suffix=".tex")
    fmt = "%f:%l:%c:%k:%n:%m\\n"
    return [["chktex", "-q", "-v0", "-I0", f"-f{fmt}", "--", path]], lambda r: False


def tool_latexindent(job: Path, a: dict, timeout: int):
    path = safe_rel(a.get("path", ""), must_exist_in=job)
    # no -s: in this version "silent" suppresses the formatted output itself; path never starts with "-"
    return [["latexindent", "-g", "/dev/null", path]], lambda r: False


def tool_pdftoppm(job: Path, a: dict, timeout: int):
    pdf = safe_rel(a.get("pdf", ""), must_exist_in=job, suffix=".pdf")
    page, dpi = int(a.get("page", 1)), int(a.get("dpi", 100))
    if not (1 <= page <= 10000 and 20 <= dpi <= 200):
        raise JobError("page must be >= 1 and dpi between 20 and 200")
    return [["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile", "-cropbox", pdf, "_page"]], \
        lambda r: r == "_page.png"


def tool_pdfinfo(job: Path, a: dict, timeout: int):
    pdf = safe_rel(a.get("pdf", ""), must_exist_in=job, suffix=".pdf")
    return [["pdfinfo", "-isodates", "--", pdf]], lambda r: False


def tool_pdftotext(job: Path, a: dict, timeout: int):
    pdf = safe_rel(a.get("pdf", ""), must_exist_in=job, suffix=".pdf")
    first, last = int(a.get("first", 1)), int(a.get("last", 1000000))
    if not (1 <= first <= last):
        raise JobError("invalid page range")
    return [["pdftotext", "-layout", "-f", str(first), "-l", str(last), "--", pdf, "-"]], lambda r: False


def tool_pdf_optimize(job: Path, a: dict, timeout: int):
    pdf = safe_rel(a.get("pdf", ""), must_exist_in=job, suffix=".pdf")
    if a.get("method", "qpdf") == "gs":
        quality = {"screen", "ebook", "printer", "prepress"} & {a.get("quality", "ebook")}
        if not quality:
            raise JobError("quality must be screen, ebook, printer or prepress")
        argv = ["gs", "-sDEVICE=pdfwrite", f"-dPDFSETTINGS=/{a.get('quality', 'ebook')}", "-dNOPAUSE", "-dBATCH", "-dQUIET",
                "-dSAFER", "-sOutputFile=_optimized.pdf", pdf]
    else:
        argv = ["qpdf", "--object-streams=generate", "--recompress-flate", "--compression-level=9", "--", pdf, "_optimized.pdf"]
    return [argv], lambda r: r == "_optimized.pdf"


def tool_math(job: Path, a: dict, timeout: int):
    """input: `_formula.tex` (generated by the API). Produces `_formula.svg` or `_formula.png`."""
    fmt = a.get("format", "svg")
    if fmt not in ("svg", "png"):
        raise JobError("format must be svg or png")
    safe_rel("_formula.tex", must_exist_in=job)
    flags = ["-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape"]
    if fmt == "svg":
        steps = [["latex", *flags, "_formula.tex"], ["dvisvgm", "--no-fonts", "--exact-bbox", "-o", "_formula.svg", "_formula.dvi"]]
    else:
        steps = [["pdflatex", *flags, "_formula.tex"], ["pdftoppm", "-png", "-r", str(int(a.get("dpi", 300))), "-singlefile", "_formula.pdf", "_formula"]]
    return steps, lambda r: r in ("_formula.svg", "_formula.png")


def tool_pandoc(job: Path, a: dict, timeout: int):
    src = safe_rel(a.get("source", ""), must_exist_in=job)
    frm, to = a.get("from"), a.get("to")
    if frm not in PANDOC_FROM or to not in PANDOC_TO:
        raise JobError("unsupported pandoc format")
    ext = {"markdown": "md", "gfm": "md", "plain": "txt"}.get(to, to)
    out = f"_converted.{ext}"
    # --sandbox: pandoc cannot read/write anything except the named input/output.
    argv = ["pandoc", "--sandbox", "-f", frm, "-t", to, "-o", out, "--wrap=preserve", "--", src]
    if to in ("latex", "html"):
        argv.insert(1, "--standalone")
    return [argv], lambda r: r == out


def tool_kpsewhich(job: Path, a: dict, timeout: int):
    name = a.get("name", "")
    if not re.fullmatch(r"[A-Za-z0-9_.+\-]{1,64}", name) or name.startswith("-"):
        raise JobError("invalid package/file name")
    return [["kpsewhich", name]], lambda r: False


def tool_versions(job: Path, a: dict, timeout: int):
    return [["sh", "-c", "pdflatex --version | head -1; xelatex --version | head -1; lualatex --version | head -1; "
             "biber --version; pandoc --version | head -1; chktex --version 2>&1 | head -1; latexmk --version | head -3 | tail -1"]], lambda r: False


TOOLS = {"compile": tool_compile, "chktex": tool_chktex, "latexindent": tool_latexindent, "pdftoppm": tool_pdftoppm,
         "pdfinfo": tool_pdfinfo, "pdftotext": tool_pdftotext, "pdf_optimize": tool_pdf_optimize, "math": tool_math,
         "pandoc": tool_pandoc, "kpsewhich": tool_kpsewhich, "versions": tool_versions}


# ---- HTTP ----------------------------------------------------------------------------------------

async def handle_run(request: Request) -> JSONResponse:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        return JSONResponse({"ok": False, "error": "request too large"}, status_code=413)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST_BYTES:
            return JSONResponse({"ok": False, "error": "request too large"}, status_code=413)
    try:
        import json
        req = json.loads(body)
        tool, args = req["tool"], req.get("args") or {}
        timeout = max(1, min(int(req.get("timeout", 60)), MAX_TIMEOUT))
        if tool not in TOOLS or not isinstance(args, dict):
            raise JobError("unknown tool")
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"ok": False, "error": "bad request"}, status_code=400)
    except JobError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix=f"{uuid.uuid4().hex}-", dir=JOBS_DIR))
    try:
        async with _sem:
            unpack(req.get("files_b64", ""), job)
            steps, want = TOOLS[tool](job, args, timeout)
            before = _snapshot(job)
            result = {"returncode": 0, "timed_out": False, "stdout": "", "stderr": ""}
            for argv in steps:
                r = await run(argv, job, timeout, job)
                result["returncode"] = r["returncode"]
                result["timed_out"] = result["timed_out"] or r["timed_out"]
                result["stdout"] += r["stdout"]
                result["stderr"] += r["stderr"]
                if r["returncode"] != 0 and tool not in ("compile", "chktex"):
                    break  # chktex/latexmk use nonzero codes for "findings"
            outputs = _collect(job, before, want)
        return JSONResponse({"ok": True, **result, "outputs": outputs, "error": None})
    except JobError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        print(f"job failed: {type(e).__name__}: {e}", flush=True)
        return JSONResponse({"ok": False, "error": "internal worker error"}, status_code=500)
    finally:
        shutil.rmtree(job, ignore_errors=True)


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = Starlette(routes=[Route("/run", handle_run, methods=["POST"]), Route("/health", health)])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9100, log_level="warning", timeout_keep_alive=5)
