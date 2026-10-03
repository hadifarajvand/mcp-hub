"""Static analysis of a LaTeX project: outline, labels, refs, citations, inputs. Regex-based, no execution."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

SECTION_LEVELS = {"part": 0, "chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4, "paragraph": 5}
REF_CMDS = r"(?:ref|eqref|autoref|cref|Cref|crefrange|vref|Vref|pageref|nameref|subref|hyperref)"
CITE_CMDS = (r"(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|parencite|textcite|autocite|footcite|smartcite|"
             r"supercite|fullcite|Cite|Parencite|Textcite|Autocite|nocite)")
_OPT = r"(?:\[[^\]]*\])*"
_VERB_ENVS = re.compile(r"\\begin\{(verbatim\*?|lstlisting|minted|comment)\}.*?\\end\{\1\}", re.S)
_COMMENT = re.compile(r"(?<!\\)%.*")
_LABEL = re.compile(r"\\label\{([^}]+)\}")
_REF = re.compile(r"\\" + REF_CMDS + r"\*?" + _OPT + r"\{([^}]+)\}")
_CITE = re.compile(r"\\(" + CITE_CMDS + r")\*?" + _OPT + r"\{([^}]+)\}")
_INPUT = re.compile(r"\\(input|include|subfile|import)\{([^}]+)\}")
_GRAPHICS = re.compile(r"\\includegraphics\*?" + _OPT + r"\{([^}]+)\}")
_BIB = re.compile(r"\\(?:bibliography|addbibresource|addglobalbib)" + _OPT + r"\{([^}]+)\}")
_USEPKG = re.compile(r"\\(?:usepackage|RequirePackage)" + _OPT + r"\{([^}]+)\}")
_DOCCLASS = re.compile(r"\\documentclass" + _OPT + r"\{([^}]+)\}")
_SECTION = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)(\*?)(?:\[[^\]]*\])?\{")
_BIB_ENTRY = re.compile(r"^\s*@(\w+)\s*[{(]\s*([^,\s]+)\s*,", re.M)
_GRAPHIC_EXTS = ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")


def strip_noise(text: str) -> str:
    """Remove verbatim-like environments and comments but keep line numbering intact."""
    text = _VERB_ENVS.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return "\n".join(_COMMENT.sub("", ln) for ln in text.split("\n"))


def _balanced(text: str, start: int) -> str:
    depth, i = 1, start
    while i < len(text) and depth:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        depth += (c == "{") - (c == "}")
        i += 1
    return text[start:i - 1] if depth == 0 else text[start:i]


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _split(names: str) -> list[str]:
    return [n.strip() for n in names.split(",") if n.strip()]


def bib_keys(bib_text: str) -> list[str]:
    return [m.group(2) for m in _BIB_ENTRY.finditer(bib_text) if m.group(1).lower() not in ("comment", "string", "preamble")]


def analyze(files: dict[str, str], main: str) -> dict:
    """`files`: relpath -> text for every text file in the project. Follows \\input/\\include from `main`."""
    out = {"main": main, "documentclass": None, "packages": [], "outline": [], "labels": [], "refs": [], "citations": [],
           "bibliography": [], "inputs": [], "graphics": [], "missing": [], "files_parsed": []}
    seen: set[str] = set()
    all_files = set(files)

    def resolve(base: str, name: str, exts: tuple[str, ...]) -> str | None:
        here = str(PurePosixPath(base).parent)
        for root in ({here, ""} if here != "." else {""}):
            for ext in exts:
                cand = str(PurePosixPath(root, name + ext)) if root else name + ext
                cand = str(PurePosixPath(cand))
                if cand in all_files:
                    return cand
        return None

    def visit(path: str) -> None:
        if path in seen or path not in files:
            return
        seen.add(path)
        out["files_parsed"].append(path)
        raw = files[path]
        text = strip_noise(raw)
        if (m := _DOCCLASS.search(text)) and out["documentclass"] is None:
            out["documentclass"] = m.group(1).strip()
        for m in _USEPKG.finditer(text):
            out["packages"] += [p for p in _split(m.group(1)) if p not in out["packages"]]
        for m in _SECTION.finditer(text):
            title = " ".join(_balanced(text, m.end()).split())
            out["outline"].append({"level": SECTION_LEVELS[m.group(1)], "kind": m.group(1), "title": title[:120],
                                   "numbered": not m.group(2), "file": path, "line": _line_of(text, m.start())})
        for m in _LABEL.finditer(text):
            out["labels"].append({"name": m.group(1).strip(), "file": path, "line": _line_of(text, m.start())})
        for m in _REF.finditer(text):
            for n in _split(m.group(1)):
                out["refs"].append({"name": n, "file": path, "line": _line_of(text, m.start())})
        for m in _CITE.finditer(text):
            for n in _split(m.group(2)):
                out["citations"].append({"key": n, "cmd": m.group(1), "file": path, "line": _line_of(text, m.start())})
        for m in _BIB.finditer(text):
            for n in _split(m.group(1)):
                out["bibliography"].append({"name": n, "file": path, "line": _line_of(text, m.start())})
        for m in _GRAPHICS.finditer(text):
            name = m.group(1).strip()
            found = resolve(path, name, _GRAPHIC_EXTS)
            out["graphics"].append({"name": name, "file": path, "line": _line_of(text, m.start()), "exists": found is not None, "resolved": found})
        for m in _INPUT.finditer(text):
            name = m.group(2).strip()
            found = resolve(path, name, (".tex", ""))
            rec = {"cmd": m.group(1), "name": name, "file": path, "line": _line_of(text, m.start()), "resolved": found}
            out["inputs"].append(rec)
            if found:
                visit(found)

    visit(main)
    out["missing"] = ([{"kind": "input", **i} for i in out["inputs"] if not i["resolved"]] +
                      [{"kind": "graphics", **g} for g in out["graphics"] if not g["exists"]])
    body = " ".join(strip_noise(files[p]) for p in out["files_parsed"])
    body = body.split("\\begin{document}", 1)[-1].split("\\end{document}", 1)[0]
    body = re.sub(r"\\[A-Za-z]+\*?(\[[^\]]*\])?", " ", body)
    out["approx_words"] = len(re.findall(r"[^\W\d_]{2,}", re.sub(r"[{}$&#^_~\\]", " ", body)))
    return out


def check_references(files: dict[str, str], main: str) -> dict:
    a = analyze(files, main)
    labels = {}
    dup = []
    for lab in a["labels"]:
        if lab["name"] in labels:
            dup.append({"label": lab["name"], "file": lab["file"], "line": lab["line"], "first": f"{labels[lab['name']]['file']}:{labels[lab['name']]['line']}"})
        labels.setdefault(lab["name"], lab)
    ref_names = {r["name"] for r in a["refs"]}
    undefined_refs = [r for r in a["refs"] if r["name"] not in labels]
    unused_labels = [lab for lab in a["labels"] if lab["name"] not in ref_names]

    bib_files, bib_missing, keys = [], [], set()
    for b in a["bibliography"]:
        name = b["name"]
        cands = [name, name + ".bib"] if not name.endswith(".bib") else [name]
        hit = next((c for c in cands if c in files), None)
        if hit is None:
            hit = next((c for c in files if c.endswith("/" + cands[-1]) or c == cands[-1]), None)
        if hit:
            bib_files.append(hit)
            keys.update(bib_keys(files[hit]))
        else:
            bib_missing.append(b)
    cite_all = any(c["key"] == "*" and c["cmd"] == "nocite" for c in a["citations"])
    cited = {c["key"] for c in a["citations"]}
    undefined_cites = [] if not (bib_files or bib_missing) and not a["bibliography"] and any(
        re.search(r"\\begin\{thebibliography\}", files[p]) for p in a["files_parsed"]) else \
        [c for c in a["citations"] if c["key"] != "*" and c["key"] not in keys]
    return {
        "undefined_references": undefined_refs, "unused_labels": unused_labels, "duplicate_labels": dup,
        "undefined_citations": undefined_cites, "unused_bib_entries": [] if cite_all else sorted(keys - cited),
        "missing_bib_files": bib_missing, "missing_inputs": [m for m in a["missing"] if m["kind"] == "input"],
        "missing_graphics": [m for m in a["missing"] if m["kind"] == "graphics"], "bib_files": bib_files,
        "counts": {"labels": len(a["labels"]), "refs": len(a["refs"]), "citations": len(a["citations"]), "bib_entries": len(keys)},
    }
