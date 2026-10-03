#!/usr/bin/env python3
"""LaTeX MCP server (API tier): project workspaces, editing, analysis. TeX itself runs in latex-worker.

This process holds the per-subject workspace volume but contains no TeX engines; anything that executes
TeX/pandoc/ghostscript is sent to the sandbox worker (no network, no persistent data) as a tarball.
"""

import asyncio
import base64
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Literal

import httpx
import regex as re2
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import BlobResourceContents, EmbeddedResource, TextContent
from starlette.requests import Request
from starlette.responses import JSONResponse

import patch as patchmod
import templates
import texlog
import texstruct
import ws
from ws import BUILD_DIR, Workspace, WorkspaceError

WORKER_URL = os.getenv("LATEX_WORKER_URL", "http://latex-worker:9100").rstrip("/")
DEFAULT_SUBJECT = os.getenv("LATEX_DEFAULT_SUBJECT", "owner")
MAX_PDF_RETURN = int(os.getenv("LATEX_MAX_PDF_RETURN_MB", "15")) * 1024 * 1024
RETENTION_DAYS = int(os.getenv("LATEX_RETENTION_DAYS", "30"))
REGEX_TIMEOUT = 2.0
_worker_sem = asyncio.Semaphore(int(os.getenv("LATEX_API_CONCURRENCY", "3")))

Engine = Literal["pdflatex", "xelatex", "lualatex"]


class LatexError(ToolError):
    """Error whose message is safe to show to the client."""


def guarded(fn):
    from functools import wraps

    @wraps(fn)
    async def wrapper(*a, **kw):
        try:
            return await fn(*a, **kw)
        except ToolError:
            raise
        except WorkspaceError as e:
            raise LatexError(str(e)) from e
        except patchmod.PatchError as e:
            raise LatexError(f"patch failed: {e}") from e
        except Exception as e:  # noqa: BLE001
            print(f"unexpected error in {fn.__name__}: {type(e).__name__}: {e}", flush=True)
            raise LatexError(f"Unexpected error ({type(e).__name__})") from e
    return wrapper


def workspace(ctx: Context) -> Workspace:
    # The gateway sets X-Hub-Subject after authentication and strips any client-supplied value.
    hdrs = ctx.headers or {}
    return Workspace(hdrs.get("x-hub-subject") or DEFAULT_SUBJECT)


# ---- worker client -------------------------------------------------------------------------------

async def run_worker(tool: str, args: dict, tar: bytes, timeout: int = 60) -> dict:
    payload = {"tool": tool, "args": args, "files_b64": base64.b64encode(tar).decode(), "timeout": timeout}
    try:
        async with _worker_sem:
            async with httpx.AsyncClient(timeout=timeout + 30, trust_env=False) as c:
                r = await c.post(f"{WORKER_URL}/run", json=payload)
    except httpx.ConnectError as e:
        raise LatexError("The LaTeX sandbox is unavailable") from e
    except httpx.TimeoutException as e:
        raise LatexError("The LaTeX sandbox timed out") from e
    try:
        body = r.json()
    except ValueError as e:
        raise LatexError("The LaTeX sandbox returned an invalid response") from e
    if r.status_code != 200 or not body.get("ok"):
        raise LatexError(f"Sandbox rejected the job: {body.get('error', 'unknown error')}")
    body["outputs"] = {k: base64.b64decode(v) for k, v in (body.get("outputs") or {}).items()}
    return body


def _text(b: bytes) -> str:
    return b.decode("utf-8", "replace")


def _read_text(w: Workspace, project: str, path: str) -> str:
    return _text(w.read(project, path))


def _need_tex(path: str) -> str:
    rel = Workspace.check_rel(path)
    if not rel.lower().endswith(".tex"):
        raise LatexError("path must be a .tex file")
    return rel


def _project_texts(w: Workspace, project: str) -> dict[str, str]:
    base = w.project_dir(project)
    out = {}
    for f in w.list_files(project):
        ext = f["path"].rsplit(".", 1)[-1].lower() if "." in f["path"] else ""
        if ext in ws.TEXT_EXT and ext != "svg" and f["bytes"] <= 2 * 1024 * 1024:
            out[f["path"]] = _text((base / f["path"]).read_bytes())
    return out


def _build_paths(main: str) -> tuple[str, str]:
    d = str(Path(main).parent)
    build = BUILD_DIR if d == "." else f"{d}/{BUILD_DIR}"
    return build, f"{build}/{Path(main).stem}.pdf"


def _pdf(w: Workspace, project: str, main: str, optimized: bool = False) -> tuple[str, bytes]:
    _, pdf = _build_paths(_need_tex(main))
    if optimized:
        pdf = pdf[:-4] + ".optimized.pdf"
    try:
        return pdf, w.read(project, pdf)
    except WorkspaceError as e:
        raise LatexError("No compiled PDF yet; run compile first") from e


mcp = MCPServer(
    name="latex",
    instructions=(
        "Create and edit LaTeX projects and compile them in a sandbox. Typical flow: create_project -> write_file/edit "
        "-> compile (read diagnostics) -> get_pdf / render_page. Projects are private to the authenticated user. "
        "Shell-escape and runtime package installation are disabled; use check_package to see what is installed."
    ),
)


# ---- templates / projects ------------------------------------------------------------------------

@mcp.tool()
@guarded
async def list_templates() -> dict[str, Any]:
    """List starter templates for create_project and snippets for insert_snippet."""
    return {"templates": sorted(templates.TEMPLATES), "snippets": {k: templates.SNIPPET_PACKAGES.get(k, []) for k in sorted(templates.SNIPPETS)}}


@mcp.tool()
@guarded
async def create_project(ctx: Context, name: str, template: str = "article", title: str = "Untitled", author: str = "") -> dict[str, Any]:
    """Create a project from a template (article, report, ieee, beamer, letter, cv). `name`: letters, digits, _ . -"""
    w = workspace(ctx)
    try:
        files = templates.render_template(template, title, author)
    except KeyError:
        raise LatexError(f"unknown template; choose from {sorted(templates.TEMPLATES)}") from None
    w.create_project(name, files)
    return {"project": name, "files": sorted(files), "main": "main.tex"}


@mcp.tool()
@guarded
async def list_projects(ctx: Context) -> dict[str, Any]:
    """List your projects with file counts and sizes."""
    return {"projects": workspace(ctx).list_projects()}


@mcp.tool()
@guarded
async def delete_project(ctx: Context, name: str) -> dict[str, Any]:
    """Permanently delete a project and all its files."""
    workspace(ctx).delete_project(name)
    return {"deleted": name}


# ---- files ---------------------------------------------------------------------------------------

@mcp.tool()
@guarded
async def list_files(ctx: Context, project: str, path: str = "", include_build: bool = False) -> dict[str, Any]:
    """List files in a project (optionally under a subdirectory). Build output (_build/) is hidden unless include_build."""
    return {"files": workspace(ctx).list_files(project, path, include_build)}


@mcp.tool()
@guarded
async def read_file(ctx: Context, project: str, path: str, start_line: int = 1, end_line: int | None = None,
                    numbered: bool = False, max_chars: int = 60000) -> dict[str, Any]:
    """Read a text file (or a line range). Set numbered=True to prefix line numbers (handy before edit_lines)."""
    w = workspace(ctx)
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext in ws.BINARY_EXT:
        raise LatexError("binary file; use get_pdf / render_page / download_zip instead")
    lines = _read_text(w, project, path).split("\n")
    total = len(lines)
    s = max(start_line, 1)
    e = min(end_line if end_line is not None else total, total)
    chunk = lines[s - 1:e]
    body = "\n".join(f"{s + i:>5}| {ln}" for i, ln in enumerate(chunk)) if numbered else "\n".join(chunk)
    truncated = len(body) > max_chars
    return {"path": path, "start_line": s, "end_line": s + len(chunk) - 1, "total_lines": total, "content": body[:max_chars], "truncated": truncated}


@mcp.tool()
@guarded
async def write_file(ctx: Context, project: str, path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
    """Create or replace a text file. Allowed types: tex sty cls bib bst csv json txt md and images/fonts via upload_zip."""
    data = content.encode("utf-8")
    workspace(ctx).write(project, path, data, overwrite=overwrite)
    return {"path": path, "bytes": len(data)}


@mcp.tool()
@guarded
async def delete_file(ctx: Context, project: str, path: str) -> dict[str, Any]:
    """Delete one file."""
    workspace(ctx).delete(project, path)
    return {"deleted": path}


@mcp.tool()
@guarded
async def move_file(ctx: Context, project: str, source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
    """Rename or move a file within the project."""
    workspace(ctx).move(project, source, destination, overwrite=overwrite)
    return {"moved": source, "to": destination}


@mcp.tool()
@guarded
async def upload_zip(ctx: Context, project: str, zip_base64: str, replace: bool = False, create: bool = True) -> dict[str, Any]:
    """Import a zip (base64) into a project, creating it if needed. replace=True wipes existing files first.
    Symlinks, absolute/.. paths and non-document file types (scripts, binaries) are rejected."""
    w = workspace(ctx)
    try:
        data = base64.b64decode(zip_base64, validate=True)
    except Exception as e:  # noqa: BLE001
        raise LatexError("zip_base64 is not valid base64") from e
    try:
        w.project_dir(project)
    except WorkspaceError:
        if not create:
            raise
        w.create_project(project, {})
    n = await asyncio.to_thread(w.extract_zip, project, data, replace=replace)
    return {"project": project, "files_imported": n}


@mcp.tool()
@guarded
async def download_zip(ctx: Context, project: str, include_build: bool = False) -> list:
    """Export the project as a zip (embedded resource)."""
    data = await asyncio.to_thread(workspace(ctx).zip_project, project, include_build)
    if len(data) > MAX_PDF_RETURN:
        raise LatexError("archive too large to return inline")
    blob = BlobResourceContents(uri=f"latex://{project}/{project}.zip", mimeType="application/zip", blob=base64.b64encode(data).decode())
    return [TextContent(type="text", text=json.dumps({"project": project, "bytes": len(data)})), EmbeddedResource(resource=blob)]


# ---- editing -------------------------------------------------------------------------------------

def _line_numbers(text: str, positions: list[int]) -> list[int]:
    return [text.count("\n", 0, p) + 1 for p in positions]


@mcp.tool()
@guarded
async def replace_text(ctx: Context, project: str, path: str, find: str, replace: str, regex: bool = False,
                       ignore_case: bool = False, count: int = 0, dry_run: bool = False) -> dict[str, Any]:
    """Find and replace in a file. regex=True uses Python-style regex (with a 2s time limit); count=0 replaces all.
    dry_run=True reports matches without writing."""
    w = workspace(ctx)
    text = _read_text(w, project, path)
    if not find:
        raise LatexError("find must not be empty")
    flags = re2.IGNORECASE if ignore_case else 0
    try:
        pattern = re2.compile(find if regex else re2.escape(find), flags)
        matches = [m.start() for m in pattern.finditer(text, timeout=REGEX_TIMEOUT)]
        new, n = pattern.subn((lambda m: replace) if not regex else replace, text, count=count, timeout=REGEX_TIMEOUT)
    except TimeoutError:
        raise LatexError("regex took too long; simplify the pattern") from None
    except re2.error as e:
        raise LatexError(f"invalid regex: {e}") from e
    if not dry_run and n:
        w.write(project, path, new.encode("utf-8"))
    return {"replacements": n, "matched_lines": _line_numbers(text, matches)[:20], "written": bool(n and not dry_run)}


@mcp.tool()
@guarded
async def edit_lines(ctx: Context, project: str, path: str, start_line: int, end_line: int, new_text: str) -> dict[str, Any]:
    """Replace lines start_line..end_line (1-based, inclusive) with new_text. Use end_line = start_line - 1 to insert
    before start_line; use empty new_text to delete the range."""
    w = workspace(ctx)
    text = _read_text(w, project, path)
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if trailing:
        lines.pop()
    if not (1 <= start_line <= len(lines) + 1) or not (start_line - 1 <= end_line <= len(lines)):
        raise LatexError(f"line range out of bounds (file has {len(lines)} lines)")
    repl = new_text.split("\n") if new_text != "" else []
    if new_text.endswith("\n") and repl:
        repl.pop()
    lines[start_line - 1:end_line] = repl
    w.write(project, path, ("\n".join(lines) + ("\n" if trailing or not text else "")).encode("utf-8"))
    return {"path": path, "lines_removed": max(0, end_line - start_line + 1), "lines_added": len(repl), "total_lines": len(lines)}


@mcp.tool()
@guarded
async def apply_patch(ctx: Context, project: str, path: str, patch: str) -> dict[str, Any]:
    """Apply a unified diff to one file. Context lines must match exactly; on mismatch nothing is written."""
    w = workspace(ctx)
    new = patchmod.apply_patch(_read_text(w, project, path), patch)
    w.write(project, path, new.encode("utf-8"))
    return {"path": path, "applied": True}


@mcp.tool()
@guarded
async def insert_snippet(ctx: Context, project: str, path: str, snippet: str, after_line: int | None = None,
                         before_line: int | None = None, after_text: str | None = None,
                         values: dict[str, str] | None = None) -> dict[str, Any]:
    """Insert a named snippet (see list_templates). Position: after_line, before_line, or after the first line containing
    after_text (default: before \\end{document}). `values` replaces placeholders like CAPTION, LABEL, FILE."""
    if snippet not in templates.SNIPPETS:
        raise LatexError(f"unknown snippet; choose from {sorted(templates.SNIPPETS)}")
    w = workspace(ctx)
    text = _read_text(w, project, path)
    lines = text.split("\n")
    body = templates.SNIPPETS[snippet]
    for k, v in (values or {}).items():
        if not re.fullmatch(r"[A-Z_]{2,20}", k):
            raise LatexError("placeholder names are UPPERCASE words")
        body = body.replace(k, v)
    if after_line is not None:
        idx = after_line
    elif before_line is not None:
        idx = before_line - 1
    elif after_text is not None:
        idx = next((i + 1 for i, ln in enumerate(lines) if after_text in ln), None)
        if idx is None:
            raise LatexError("after_text not found")
    else:
        idx = next((i for i, ln in enumerate(lines) if "\\end{document}" in ln), len(lines))
    if not 0 <= idx <= len(lines):
        raise LatexError("insert position out of range")
    lines[idx:idx] = body.rstrip("\n").split("\n")
    w.write(project, path, "\n".join(lines).encode("utf-8"))
    return {"inserted_at_line": idx + 1, "needs_packages": templates.SNIPPET_PACKAGES.get(snippet, [])}


# ---- analysis ------------------------------------------------------------------------------------

@mcp.tool()
@guarded
async def get_structure(ctx: Context, project: str, main: str = "main.tex") -> dict[str, Any]:
    """Outline (sections with file/line), labels, refs, citations, packages, \\input tree, graphics and approx word count."""
    w = workspace(ctx)
    _need_tex(main)
    texts = await asyncio.to_thread(_project_texts, w, project)
    if main not in texts:
        raise LatexError(f"file not found: {main}")
    return await asyncio.to_thread(texstruct.analyze, texts, main)


@mcp.tool()
@guarded
async def check_references(ctx: Context, project: str, main: str = "main.tex") -> dict[str, Any]:
    """Static check for undefined/duplicate labels, undefined \\cite keys, unused bib entries, missing inputs/graphics/.bib."""
    w = workspace(ctx)
    _need_tex(main)
    texts = await asyncio.to_thread(_project_texts, w, project)
    if main not in texts:
        raise LatexError(f"file not found: {main}")
    return await asyncio.to_thread(texstruct.check_references, texts, main)


# ---- sandboxed tools: compile / lint / format / pdf ----------------------------------------------

@mcp.tool(name="compile")
@guarded
async def compile_project(ctx: Context, project: str, main: str = "main.tex", engine: Engine = "pdflatex", timeout: int = 60) -> dict[str, Any]:
    """Compile with latexmk (reruns and bibtex/biber handled automatically) in the sandbox.

    Returns success, page count and structured diagnostics (severity, file, line, message, context, hint).
    Engines: pdflatex | xelatex (Unicode/system fonts, e.g. Persian/Arabic with xepersian) | lualatex.
    Note: lualatex runs with weaker file-read isolation than the others (its Lua cannot be restricted without
    breaking font loading); the sandbox contains no secrets, but prefer xelatex when you do not need Lua.
    """
    w = workspace(ctx)
    main = _need_tex(main)
    if not (5 <= timeout <= 120):
        raise LatexError("timeout must be between 5 and 120 seconds")
    w.resolve(project, main)  # existence + containment
    tar = await asyncio.to_thread(w.tar_for_worker, project)
    r = await run_worker("compile", {"engine": engine, "main": main}, tar, timeout)

    build, pdf_rel = _build_paths(main)
    outputs = {Path(k).name: v for k, v in r["outputs"].items()}
    await asyncio.to_thread(w.replace_build, project, build, outputs)
    stem = Path(main).stem
    log = _text(outputs.get(f"{stem}.log", b""))
    parsed = texlog.parse_latex_log(log)
    diags = parsed["diagnostics"] + texlog.parse_bib_log(_text(outputs.get(f"{stem}.blg", b"")))
    order = {"error": 0, "warning": 1, "info": 2}
    diags.sort(key=lambda d: order[d["severity"]])
    counts = texlog.summarize(diags)
    pdf_ok = f"{stem}.pdf" in outputs
    if not log and not r["timed_out"]:
        # No log at all: the build never started (bad options, missing tool...). Show the sandbox's own message.
        msg = " ".join((r["stderr"] or r["stdout"]).split())[-300:] or "the build produced no output"
        diags.insert(0, {"severity": "error", "source": "sandbox", "file": None, "line": None, "message": f"Build did not run: {msg}"})
        counts["error"] += 1
    for ln in (r["stdout"] + "\n" + r["stderr"]).splitlines():  # messages from our own sandbox shims
        if ln.startswith("SANDBOX:"):
            diags.insert(0, {"severity": "error", "source": "sandbox", "file": None, "line": None, "message": ln[8:].strip()})
            counts["error"] += 1
    if r["timed_out"]:
        diags.insert(0, {"severity": "error", "source": "sandbox", "file": None, "line": None,
                         "message": f"Compilation exceeded the {timeout}s limit and was killed (infinite loop or very heavy document?)"})
        counts["error"] += 1
    res: dict[str, Any] = {
        "success": bool(pdf_ok and counts["error"] == 0 and not r["timed_out"]), "engine": engine, "main": main,
        "pdf": pdf_rel if pdf_ok else None, "pages": parsed["pages"], "pdf_bytes": len(outputs.get(f"{stem}.pdf", b"")),
        "counts": counts, "diagnostics": diags[:60], "timed_out": r["timed_out"],
    }
    if len(diags) > 60:
        res["diagnostics_truncated"] = len(diags) - 60
    if not res["success"]:
        tail = [ln for ln in log.splitlines() if ln.strip()][-25:] or r["stderr"].splitlines()[-15:]
        res["log_tail"] = "\n".join(texlog._JOBDIR.sub("", ln) for ln in tail)[:4000]
    return res


@mcp.tool()
@guarded
async def clean(ctx: Context, project: str) -> dict[str, Any]:
    """Delete all build output (_build/ directories)."""
    w = workspace(ctx)
    base = w.project_dir(project)
    n = 0
    import shutil
    for d in [p for p in base.rglob(BUILD_DIR) if p.is_dir() and not p.is_symlink()]:
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    return {"cleaned_directories": n}


@mcp.tool()
@guarded
async def get_pdf(ctx: Context, project: str, main: str = "main.tex", optimized: bool = False) -> list:
    """Return the compiled PDF (embedded resource). optimized=True returns the output of pdf_optimize."""
    w = workspace(ctx)
    rel, data = _pdf(w, project, main, optimized)
    if len(data) > MAX_PDF_RETURN:
        raise LatexError(f"PDF is {len(data) // 1024 // 1024} MB, over the {MAX_PDF_RETURN // 1024 // 1024} MB inline limit; try pdf_optimize")
    blob = BlobResourceContents(uri=f"latex://{project}/{rel}", mimeType="application/pdf", blob=base64.b64encode(data).decode())
    return [TextContent(type="text", text=json.dumps({"path": rel, "bytes": len(data)})), EmbeddedResource(resource=blob)]


@mcp.tool()
@guarded
async def render_page(ctx: Context, project: str, page: int = 1, dpi: int = 100, main: str = "main.tex") -> Image:
    """Render one page of the compiled PDF to a PNG image so you can look at the layout (dpi 20-200)."""
    w = workspace(ctx)
    _, data = _pdf(w, project, main)
    r = await run_worker("pdftoppm", {"pdf": "doc.pdf", "page": page, "dpi": dpi}, Workspace.tar_of({"doc.pdf": data}), 60)
    png = r["outputs"].get("_page.png")
    if not png:
        raise LatexError(f"could not render page {page} (does the document have that many pages?)")
    return Image(data=png, format="png")


@mcp.tool()
@guarded
async def pdf_info(ctx: Context, project: str, main: str = "main.tex") -> dict[str, Any]:
    """PDF metadata: pages, page size, title, producer, file size."""
    w = workspace(ctx)
    _, data = _pdf(w, project, main)
    r = await run_worker("pdfinfo", {"pdf": "doc.pdf"}, Workspace.tar_of({"doc.pdf": data}), 30)
    info = {}
    for ln in r["stdout"].splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            info[k.strip().lower().replace(" ", "_")] = v.strip()
    return info


@mcp.tool()
@guarded
async def pdf_text(ctx: Context, project: str, main: str = "main.tex", first_page: int = 1, last_page: int | None = None,
                   max_chars: int = 40000) -> dict[str, Any]:
    """Extract text (layout preserved) from the compiled PDF, handy for checking what actually rendered."""
    w = workspace(ctx)
    _, data = _pdf(w, project, main)
    r = await run_worker("pdftotext", {"pdf": "doc.pdf", "first": first_page, "last": last_page or 1000000},
                         Workspace.tar_of({"doc.pdf": data}), 60)
    return {"text": r["stdout"][:max_chars], "truncated": len(r["stdout"]) > max_chars}


@mcp.tool()
@guarded
async def pdf_optimize(ctx: Context, project: str, main: str = "main.tex", method: Literal["qpdf", "gs"] = "qpdf",
                       quality: Literal["screen", "ebook", "printer", "prepress"] = "ebook") -> dict[str, Any]:
    """Shrink the PDF (qpdf: lossless; gs: re-encodes images by quality). Saved next to the original as *.optimized.pdf."""
    w = workspace(ctx)
    rel, data = _pdf(w, project, main)
    r = await run_worker("pdf_optimize", {"pdf": "doc.pdf", "method": method, "quality": quality}, Workspace.tar_of({"doc.pdf": data}), 90)
    out = r["outputs"].get("_optimized.pdf")
    if not out:
        raise LatexError("optimization failed")
    target = Path(w.project_dir(project)) / (rel[:-4] + ".optimized.pdf")
    target.write_bytes(out)
    return {"original_bytes": len(data), "optimized_bytes": len(out), "saved_as": rel[:-4] + ".optimized.pdf"}


@mcp.tool()
@guarded
async def lint(ctx: Context, project: str, path: str = "main.tex") -> dict[str, Any]:
    """Run chktex on one .tex file and return structured findings."""
    w = workspace(ctx)
    path = _need_tex(path)
    data = w.read(project, path)
    r = await run_worker("chktex", {"path": path}, Workspace.tar_of({path: data}), 30)
    findings = []
    for ln in r["stdout"].splitlines():
        parts = ln.split(":", 5)
        if len(parts) == 6 and parts[1].isdigit():
            findings.append({"file": parts[0], "line": int(parts[1]), "column": int(parts[2]) if parts[2].isdigit() else None,
                             "severity": parts[3].lower(), "number": parts[4], "message": parts[5].strip()})
    return {"count": len(findings), "findings": findings[:100], "truncated": len(findings) > 100}


@mcp.tool(name="format")
@guarded
async def format_latex(ctx: Context, project: str, path: str = "main.tex", write: bool = False) -> dict[str, Any]:
    """Re-indent a .tex file with latexindent. write=False returns a preview only; write=True saves it."""
    w = workspace(ctx)
    path = _need_tex(path)
    original = w.read(project, path)
    r = await run_worker("latexindent", {"path": path}, Workspace.tar_of({path: original}), 60)
    formatted = r["stdout"]
    if r["returncode"] != 0 or not formatted.strip():
        raise LatexError("latexindent failed: " + (r["stderr"].strip().splitlines() or ["no output"])[-1][:200])
    changed = formatted != _text(original)
    if write and changed:
        w.write(project, path, formatted.encode("utf-8"))
    out: dict[str, Any] = {"changed": changed, "written": bool(write and changed)}
    if not write:
        out["preview"] = formatted[:20000]
        out["preview_truncated"] = len(formatted) > 20000
    return out


@mcp.tool()
@guarded
async def render_math(latex: str, format: Literal["svg", "png"] = "svg", display: bool = True, packages: list[str] | None = None,
                      dpi: int = 300) -> Image | dict[str, Any]:
    """Render a formula (LaTeX math, without $) to an SVG (returned as text) or PNG (returned as an image)."""
    if len(latex) > 5000:
        raise LatexError("formula too long")
    pk = [p for p in (packages or []) if re.fullmatch(r"[A-Za-z0-9-]{1,30}", p)][:8]
    if packages and len(pk) != len(packages):
        raise LatexError("package names may contain only letters, digits and '-'")
    pre = "\\usepackage{amsmath,amssymb,amsfonts,xcolor}\n" + "".join(f"\\usepackage{{{p}}}\n" for p in pk)
    mode = "\\displaystyle " if display else ""
    src = f"\\documentclass[border=3pt]{{standalone}}\n{pre}\\begin{{document}}\n\\begin{{math}}{mode}{latex}\\end{{math}}\n\\end{{document}}\n"
    r = await run_worker("math", {"format": format, "dpi": max(50, min(dpi, 600))}, Workspace.tar_of({"_formula.tex": src.encode()}), 60)
    out = r["outputs"].get(f"_formula.{format}")
    if not out:
        err = [ln for ln in r["stdout"].splitlines() if ln.startswith("!")][:2]
        raise LatexError("could not render formula: " + ("; ".join(err) or "LaTeX error"))
    return Image(data=out, format="png") if format == "png" else {"format": "svg", "svg": _text(out)}


@mcp.tool()
@guarded
async def convert(ctx: Context, project: str, source: str, to: Literal["markdown", "gfm", "html", "latex", "plain", "rst", "org"],
                  source_format: Literal["latex", "markdown", "gfm", "html", "docx", "rst", "org", "odt"] | None = None) -> list:
    """Convert a project file between formats with pandoc (sandboxed). docx/odt can be read as input but not produced (sandbox). Result is returned inline."""
    w = workspace(ctx)
    src = Workspace.check_rel(source)
    guess = {"tex": "latex", "md": "markdown", "html": "html", "docx": "docx", "rst": "rst", "org": "org", "odt": "odt"}
    frm = source_format or guess.get(src.rsplit(".", 1)[-1].lower())
    if not frm:
        raise LatexError("cannot infer source_format; pass it explicitly")
    data = w.read(project, src)
    r = await run_worker("pandoc", {"source": src, "from": frm, "to": to}, Workspace.tar_of({src: data}), 90)
    outs = r["outputs"]
    if not outs:
        err = (r["stderr"].strip().splitlines() or ["conversion failed"])[-1][:200]
        raise LatexError(f"pandoc: {err}")
    name, blob = next(iter(outs.items()))
    return [TextContent(type="text", text=_text(blob))]


@mcp.tool()
@guarded
async def check_package(name: str) -> dict[str, Any]:
    """Check whether a LaTeX package/class/file exists in the sandbox's TeX installation (e.g. 'tikz', 'IEEEtran')."""
    found = {}
    for suffix in ("", ".sty", ".cls"):
        r = await run_worker("kpsewhich", {"name": name + suffix}, Workspace.tar_of({}), 20)
        path = r["stdout"].strip().splitlines()
        if path:
            found[name + suffix or name] = path[0]
            break
    return {"name": name, "installed": bool(found), "path": next(iter(found.values()), None)}


@mcp.tool()
@guarded
async def tex_versions() -> dict[str, Any]:
    """Versions of the TeX engines and tools available in the sandbox."""
    r = await run_worker("versions", {}, Workspace.tar_of({}), 30)
    return {"versions": [ln for ln in r["stdout"].splitlines() if ln.strip()]}


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _prune_loop() -> None:
    while RETENTION_DAYS > 0:
        try:
            for sub in ws.ROOT.iterdir():
                if sub.is_dir() and not sub.is_symlink():
                    Workspace(sub.name).prune(RETENTION_DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"prune failed: {type(e).__name__}", flush=True)
        time.sleep(86400)


if __name__ == "__main__":
    ws.ROOT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_prune_loop, daemon=True).start()
    mcp.run(
        transport="streamable-http",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8000")),
        max_request_body_size=48 * 1024 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "latex:8000,localhost:*,127.0.0.1:*").split(",") if h.strip()],
            allowed_origins=[],
        ),
    )
