"""Unit tests for servers/latex/api (workspace containment, patch, log parser, analyzer)."""
import io
import os
import stat
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "servers", "latex", "api"))
import patch as patchmod  # noqa: E402
import templates  # noqa: E402
import texlog  # noqa: E402
import texstruct  # noqa: E402
import ws  # noqa: E402
from ws import Workspace, WorkspaceError  # noqa: E402


@pytest.fixture
def w(tmp_path):
    ws_ = Workspace("tester", root=tmp_path)
    ws_.create_project("p", {"main.tex": b"\\documentclass{article}"})
    return ws_


# ---------------- path containment ----------------
@pytest.mark.parametrize("bad", ["../x.tex", "a/../../x.tex", "/etc/passwd", "a\\b.tex", ".hidden.tex", "a/.git/x.tex", "x\x00.tex",
                                 "-rf.tex", "a//b.tex/..", "..", ".", "a/./b.tex", "_build/x.tex", "a b/../c.tex", "%2e%2e/x.tex"])
def test_bad_paths_rejected(w, bad):
    with pytest.raises(WorkspaceError):
        w.write("p", bad, b"x")


@pytest.mark.parametrize("bad", ["x.sh", "x.py", "x.pl", "x.lua", "x.so", "x.exe", "x", "x.TEX.sh", "latexmkrc", ".latexmkrc"])
def test_dangerous_extensions_rejected(w, bad):
    with pytest.raises(WorkspaceError):
        w.write("p", bad, b"x")


@pytest.mark.parametrize("name", ["../p", "a/b", ".hidden", "", "x" * 65, "p q", "..", "p\x00"])
def test_bad_project_names(w, name):
    with pytest.raises(WorkspaceError):
        w.project_dir(name)


def test_symlink_in_project_is_never_followed(w, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    link = w.project_dir("p") / "link.tex"
    os.symlink(secret, link)
    with pytest.raises(WorkspaceError):
        w.read("p", "link.tex")
    with pytest.raises(WorkspaceError):
        w.write("p", "link.tex", b"overwrite")
    assert secret.read_text() == "TOPSECRET"
    assert "link.tex" not in [f["path"] for f in w.list_files("p")]
    assert b"TOPSECRET" not in w.tar_for_worker("p")  # not packed for the worker either


def test_symlinked_directory_not_followed(w, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.tex").write_text("LEAK")
    os.symlink(outside, w.project_dir("p") / "dir")
    with pytest.raises(WorkspaceError):
        w.read("p", "dir/a.tex")
    with pytest.raises(WorkspaceError):
        w.write("p", "dir/new.tex", b"x")
    assert not (outside / "new.tex").exists()


def test_subject_isolation(tmp_path):
    a, b = Workspace("alice", root=tmp_path), Workspace("bob", root=tmp_path)
    a.create_project("p", {"main.tex": b"alice"})
    assert b.list_projects() == []
    with pytest.raises(WorkspaceError):
        b.read("p", "main.tex")


@pytest.mark.parametrize("subject", ["../../etc", "a/b", "..", "", ".", "x\x00y"])
def test_subject_cannot_escape(tmp_path, subject):
    s = Workspace(subject, root=tmp_path)
    assert str(s.root.resolve()).startswith(str(tmp_path.resolve()))
    assert s.root != tmp_path


def test_roundtrip_edit_delete_move(w):
    w.write("p", "ch/one.tex", b"hello")
    assert w.read("p", "ch/one.tex") == b"hello"
    w.move("p", "ch/one.tex", "two.tex")
    assert w.read("p", "two.tex") == b"hello"
    w.delete("p", "two.tex")
    with pytest.raises(WorkspaceError):
        w.read("p", "two.tex")


# ---------------- quotas ----------------
def test_quotas(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "MAX_FILES", 3)
    monkeypatch.setattr(ws, "MAX_FILE_BYTES", 100)
    w = Workspace("q", root=tmp_path)
    w.create_project("p", {"a.tex": b"1"})
    w.write("p", "b.tex", b"1")
    w.write("p", "c.tex", b"1")
    with pytest.raises(WorkspaceError, match="file limit"):
        w.write("p", "d.tex", b"1")
    w.write("p", "a.tex", b"overwrite is fine")  # does not add a file
    with pytest.raises(WorkspaceError, match="too large"):
        w.write("p", "a.tex", b"x" * 101)
    monkeypatch.setattr(ws, "MAX_PROJECTS", 1)
    with pytest.raises(WorkspaceError, match="project limit"):
        w.create_project("p2", {})


def test_project_bytes_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "MAX_PROJECT_BYTES", 50)
    w = Workspace("q", root=tmp_path)
    w.create_project("p", {})
    w.write("p", "a.tex", b"x" * 40)
    with pytest.raises(WorkspaceError, match="size limit"):
        w.write("p", "b.tex", b"x" * 40)


# ---------------- zip handling ----------------
def _zip(entries, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in entries.items():
            z.writestr(n, d)
        if symlink:
            zi = zipfile.ZipInfo(symlink[0])
            zi.create_system = 3
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(zi, symlink[1])
    return buf.getvalue()


def test_zip_ok_strips_single_top_dir(w):
    n = w.extract_zip("p", _zip({"proj/main.tex": "A", "proj/sec/b.tex": "B"}), replace=True)
    assert n == 2 and w.read("p", "main.tex") == b"A" and w.read("p", "sec/b.tex") == b"B"


@pytest.mark.parametrize("name", ["../evil.tex", "a/../../evil.tex", "/abs/evil.tex", "..\\evil.tex", ".hidden.tex", "_build/x.tex", "x.sh", "a/b.py"])
def test_zip_slip_and_bad_names(w, tmp_path, name):
    with pytest.raises(WorkspaceError):
        w.extract_zip("p", _zip({name: "x", "ok.tex": "y"}))
    assert not (tmp_path / "evil.tex").exists()


def test_zip_symlink_rejected(w):
    with pytest.raises(WorkspaceError, match="symlink"):
        w.extract_zip("p", _zip({"ok.tex": "x"}, symlink=("link.tex", "/etc/passwd")))


def test_zip_bomb_rejected(w, monkeypatch):
    monkeypatch.setattr(ws, "MAX_PROJECT_BYTES", 1024 * 1024)
    monkeypatch.setattr(ws, "MAX_FILE_BYTES", 512 * 1024)
    bomb = _zip({"big.tex": "A" * (50 * 1024 * 1024)})
    assert len(bomb) < 100_000
    with pytest.raises(WorkspaceError, match="too large|expands"):
        w.extract_zip("p", bomb)


def test_zip_too_many_files(w, monkeypatch):
    monkeypatch.setattr(ws, "MAX_FILES", 5)
    with pytest.raises(WorkspaceError, match="too many"):
        w.extract_zip("p", _zip({f"f{i}.tex": "x" for i in range(6)}))


def test_not_a_zip(w):
    with pytest.raises(WorkspaceError):
        w.extract_zip("p", b"not a zip")


def test_zip_replace_is_atomic_on_validation_failure(w):
    w.write("p", "keep.tex", b"keep")
    with pytest.raises(WorkspaceError):
        w.extract_zip("p", _zip({"../bad.tex": "x"}), replace=True)
    assert w.read("p", "keep.tex") == b"keep"  # validation happens before anything is deleted


# ---------------- patch ----------------
def test_patch_apply_and_mismatch():
    src = "a\nb\nc\nd\ne\n"
    out = patchmod.apply_patch(src, "@@ -2,3 +2,3 @@\n b\n-c\n+C\n d\n")
    assert out == "a\nb\nC\nd\ne\n"
    with pytest.raises(patchmod.PatchError, match="does not match"):
        patchmod.apply_patch(src, "@@ -2,3 +2,3 @@\n b\n-WRONG\n+C\n d\n")
    with pytest.raises(patchmod.PatchError):
        patchmod.apply_patch(src, "garbage")


def test_patch_multi_hunk_and_insert_delete():
    src = "1\n2\n3\n4\n5\n6\n7\n8\n"
    p = "@@ -1,2 +1,3 @@\n 1\n+1.5\n 2\n@@ -6,3 +7,2 @@\n 6\n-7\n 8\n"
    assert patchmod.apply_patch(src, p) == "1\n1.5\n2\n3\n4\n5\n6\n8\n"


# ---------------- log parser ----------------
LOG = r"""This is pdfTeX
./main.tex:7: Undefined control sequence.
l.7 \foo
        bar
! LaTeX Error: File `nosuchpkg.sty' not found.
LaTeX Warning: Reference `fig:x' on page 1 undefined on input line 12.
LaTeX Warning: Citation `knuth' on page 1 undefined on input line 13.
Package hyperref Warning: Token not allowed in a PDF string (PDFDocEncoding):
(hyperref)                removing `math shift' on input line 20.
Overfull \hbox (12.3pt too wide) in paragraph at lines 30--31
Output written on _build/main.pdf (3 pages, 45678 bytes).
"""


def test_parse_latex_log():
    r = texlog.parse_latex_log(LOG)
    assert r["pages"] == 3 and r["output_bytes"] == 45678
    d = r["diagnostics"]
    err = [x for x in d if x["severity"] == "error"]
    assert err[0]["file"] == "main.tex" and err[0]["line"] == 7 and "Undefined control" in err[0]["message"] and "foo" in err[0]["context"]
    assert any("nosuchpkg.sty" in x["message"] and "hint" in x for x in err)
    warn = [x for x in d if x["severity"] == "warning"]
    assert any(x["line"] == 12 and "undefined" in x["message"] for x in warn)
    assert any(x["source"] == "package:hyperref" and x["line"] == 20 for x in warn)
    assert any(x["severity"] == "info" and "Overfull" in x["message"] for x in d)
    assert texlog.summarize(d)["error"] == 2


def test_parse_blg_and_strip_jobdir():
    blg = "Warning--I didn't find a database entry for \"nokey\"\nI was expecting a `,' or a `}'\n---line 5 of file refs.bib\n" \
          "[1] Utils.pm:123> ERROR - BibTeX subsystem: /tmp/jobs/abc123-xyz/refs.bib, line 9, syntax error\n"
    d = texlog.parse_bib_log(blg)
    assert any("nokey" in x["message"] for x in d)
    assert any(x["file"] == "refs.bib" and x["line"] == 5 for x in d)
    assert not any("/tmp/jobs" in x["message"] for x in d)


# ---------------- analyzer ----------------
def test_analyze_and_check_references():
    files = {
        "main.tex": "\\documentclass{article}\n\\usepackage{amsmath,graphicx}\n\\begin{document}\n\\section{Intro}\\label{sec:a}\n"
                    "See \\ref{sec:a}, \\cref{sec:zzz} and \\cite{k1,k2}.\n% \\cite{commented}\n\\input{ch/two}\n\\includegraphics{missing.png}\n"
                    "\\bibliography{refs}\n\\end{document}",
        "ch/two.tex": "\\subsection{Two}\\label{sec:a}\n\\autocite{k3}\n",
        "refs.bib": "@article{k1, title={x}}\n@book{k2,\n title={y}}\n@comment{zzz}\n@article{unused1, title={u}}",
    }
    a = texstruct.analyze(files, "main.tex")
    assert a["documentclass"] == "article" and a["packages"] == ["amsmath", "graphicx"]
    assert [o["title"] for o in a["outline"]] == ["Intro", "Two"] and a["outline"][1]["file"] == "ch/two.tex"
    assert a["inputs"][0]["resolved"] == "ch/two.tex"
    assert any(g["name"] == "missing.png" and not g["exists"] for g in a["graphics"])
    assert "commented" not in {c["key"] for c in a["citations"]}
    c = texstruct.check_references(files, "main.tex")
    assert [r["name"] for r in c["undefined_references"]] == ["sec:zzz"]
    assert [d["label"] for d in c["duplicate_labels"]] == ["sec:a"]
    assert [x["key"] for x in c["undefined_citations"]] == ["k3"]
    assert c["unused_bib_entries"] == ["unused1"]
    assert len(c["missing_graphics"]) == 1


def test_analyze_ignores_verbatim_and_handles_cycles():
    files = {"main.tex": "\\input{main}\n\\begin{verbatim}\\label{no}\\ref{no}\\end{verbatim}\\section{S}"}
    a = texstruct.analyze(files, "main.tex")
    assert a["labels"] == [] and a["refs"] == [] and len(a["outline"]) == 1


# ---------------- templates ----------------
def test_templates_escape_user_input():
    f = templates.render_template("article", "R&D \\input{/etc/passwd} 50%", "A_B $x$")
    t = f["main.tex"].decode()
    assert "\\input{/etc/passwd}" not in t.replace("\\textbackslash{}input", "") and "R\\&D" in t and "50\\%" in t
