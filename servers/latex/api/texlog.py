"""Parse LaTeX / BibTeX / Biber logs into structured diagnostics."""

from __future__ import annotations

import re

_JOBDIR = re.compile(r"/tmp/jobs/[0-9a-f]+-[A-Za-z0-9_]+/")
_FILE_ERR = re.compile(r"^(?P<file>[^\s:][^:\n]*?\.(?:tex|sty|cls|bib|def|cfg|clo|fd|ldf|dtx|bbx|cbx|lbx|aux|toc|out|bbl|lua)):(?P<line>\d+): (?P<msg>.+)$")
_BANG = re.compile(r"^! (?P<msg>.+)$")
_CTX = re.compile(r"^l\.(?P<line>\d+) ?(?P<text>.*)$")
_LATEX_WARN = re.compile(r"^LaTeX (?:Font )?Warning: (?P<msg>.*)$")
_PKG_WARN = re.compile(r"^(?:Package|Class) (?P<pkg>[\w@-]+) Warning: (?P<msg>.*)$")
_PKG_INFO = re.compile(r"^(?:Package|Class) (?P<pkg>[\w@-]+) Info: (?P<msg>.*)$")
_ONLINE = re.compile(r"\s+on input line (?P<line>\d+)\.?$")
_BOX = re.compile(r"^(?P<kind>Overfull|Underfull) \\[hv]box \((?P<amount>[^)]*)\).* at lines? (?P<line>\d+)")
_OUTPUT = re.compile(r"^Output written on (?P<path>.+?) \((?P<pages>\d+) pages?, (?P<bytes>\d+) bytes\)")
_BLG_WARN = re.compile(r"^Warning--(?P<msg>.+)$")
_BLG_LINE = re.compile(r"^---line (?P<line>\d+) of file (?P<file>.+)$")
_BIBER = re.compile(r"(?:^|\] )(?:\S+\.pm:\d+> )?(?P<lvl>WARN|ERROR) - (?P<msg>.+)$")

MAX_DIAGNOSTICS = 200


def _norm(path: str | None) -> str | None:
    if not path:
        return None
    path = _JOBDIR.sub("", path)
    return path[2:] if path.startswith("./") else path


def _hint(msg: str) -> str | None:
    m = re.search(r"File [`']([^'`]+)' not found", msg)
    if m:
        return (f"'{m.group(1)}' is not available in the sandbox (no runtime package installs). "
                "Use check_package to see what exists, or pick another package/class.")
    if "Undefined control sequence" in msg:
        return "A command is misspelled or its package is not loaded (check \\usepackage)."
    if "Missing $ inserted" in msg:
        return "Math-mode symbol used outside math mode (or an unescaped _ ^ in text)."
    if "Runaway argument" in msg or "File ended while scanning" in msg:
        return "A brace or environment is not closed."
    if "Emergency stop" in msg or "no output PDF file produced" in msg:
        return "Compilation aborted; fix the first error above it."
    return None


def parse_latex_log(log: str) -> dict:
    lines = log.splitlines()
    diags: list[dict] = []
    pages = out_bytes = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _OUTPUT.match(ln)
        if m:
            pages, out_bytes = int(m["pages"]), int(m["bytes"])
        m = _FILE_ERR.match(ln)
        err_file, err_line, err_msg = None, None, None
        if m:
            err_file, err_line, err_msg = _norm(m["file"]), int(m["line"]), m["msg"].strip()
        else:
            b = _BANG.match(ln)
            if b and not ln.startswith("!  "):
                err_msg = b["msg"].strip()
        if err_msg is not None:
            ctx = None
            for j in range(i + 1, min(i + 8, len(lines))):
                c = _CTX.match(lines[j])
                if c:
                    err_line = err_line or int(c["line"])
                    ctx = (c["text"] + (" " + lines[j + 1].strip() if j + 1 < len(lines) and lines[j + 1].strip() else "")).strip()[:200]
                    break
            d = {"severity": "error", "source": "latex", "file": err_file, "line": err_line, "message": err_msg}
            if ctx:
                d["context"] = ctx
            if (h := _hint(err_msg)):
                d["hint"] = h
            diags.append(d)
        else:
            w = _LATEX_WARN.match(ln) or _PKG_WARN.match(ln)
            if w:
                msg = w["msg"]
                # Continuation lines look like "(pkgname)      more text" or are indented.
                j = i + 1
                while j < len(lines) and (re.match(r"^\([\w@-]+\)\s{2,}", lines[j]) or (not _ONLINE.search(msg) and lines[j].startswith("  ") and lines[j].strip())):
                    msg += " " + re.sub(r"^\([\w@-]+\)\s+", "", lines[j]).strip()
                    j += 1
                    if _ONLINE.search(msg):
                        break
                om = _ONLINE.search(msg)
                line_no = int(om["line"]) if om else None
                msg = _ONLINE.sub("", msg).strip().rstrip(".")
                src = "latex"
                if (pm := _PKG_WARN.match(ln)):
                    src = f"package:{pm['pkg']}"
                diags.append({"severity": "warning", "source": src, "file": None, "line": line_no, "message": msg})
            else:
                bx = _BOX.match(ln)
                if bx:
                    diags.append({"severity": "info", "source": "latex", "file": None, "line": int(bx["line"]),
                                  "message": f"{bx['kind']} box ({bx['amount']})"})
                elif "No pages of output" in ln:
                    diags.append({"severity": "error", "source": "latex", "file": None, "line": None, "message": "No pages of output"})
        i += 1
    return {"diagnostics": _dedupe(diags), "pages": pages, "output_bytes": out_bytes}


def parse_bib_log(blg: str) -> list[dict]:
    out: list[dict] = []
    lines = blg.splitlines()
    for idx, ln in enumerate(lines):
        ln = _JOBDIR.sub("", ln)
        w = _BLG_WARN.match(ln)
        if w:
            out.append({"severity": "warning", "source": "bibtex", "file": None, "line": None, "message": w["msg"].strip()})
            continue
        e = _BLG_LINE.match(ln)
        if e and idx > 0:
            out.append({"severity": "error", "source": "bibtex", "file": _norm(e["file"]), "line": int(e["line"]),
                        "message": lines[idx - 1].strip()})
            continue
        b = _BIBER.search(ln)
        if b:
            msg = _JOBDIR.sub("", b["msg"]).strip()
            fm = re.search(r"([\w./-]+\.bib), line (\d+)", msg)
            out.append({"severity": "error" if b["lvl"] == "ERROR" else "warning", "source": "biber",
                        "file": _norm(fm[1]) if fm else None, "line": int(fm[2]) if fm else None, "message": msg[:300]})
    return _dedupe(out)


def _dedupe(diags: list[dict]) -> list[dict]:
    seen, out = set(), []
    for d in diags:
        key = (d["severity"], d["source"], d.get("file"), d.get("line"), d["message"])
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda d: order[d["severity"]])
    return out[:MAX_DIAGNOSTICS]


def summarize(diags: list[dict]) -> dict:
    return {s: sum(1 for d in diags if d["severity"] == s) for s in ("error", "warning", "info")}
