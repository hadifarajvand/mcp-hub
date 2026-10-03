#!/usr/bin/env python3
"""End-to-end + hostile-input tests for the LaTeX MCP through the gateway (dev overlay).

  MCP_HUB_TOKEN=... python tests/latex_e2e.py [base_url]

Hostile tests plant CANARY files inside the worker container (readable by the TeX process, so only the
sandbox stands between them and the output) and assert no marker ever reaches a result.
"""
import asyncio
import base64
import io
import json
import os
import struct
import subprocess
import sys
import time
import zipfile
import zlib

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
TOKEN = os.environ["MCP_HUB_TOKEN"]
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]
failures = []
RUN = str(int(time.time()))


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {('- ' + str(detail)[:220]) if (detail and not ok) else ''}")
    if not ok:
        failures.append(name)


def sh(service, cmd):
    return subprocess.run(COMPOSE + ["exec", "-T", service, "sh", "-c", cmd], capture_output=True, text=True)


def png(w=4, h=4):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


async def main():
    http = httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=240)
    async with Client(streamable_http_client(f"{BASE}/latex/mcp", http_client=http)) as c:
        async def call(name, args):
            r = await c.call_tool(name, args)
            text = "".join(getattr(x, "text", "") or "" for x in r.content)
            return r.is_error, text, r.structured_content, r.content

        async def js(name, args):
            err, text, sc, _ = await call(name, args)
            if sc is not None:
                return err, sc
            try:
                return err, json.loads(text)
            except ValueError:
                return err, {"_text": text}

        async def mk(name, template="article", **kw):
            err, text, _, _ = await call("create_project", {"name": f"{name}-{RUN}", "template": template, **kw})
            if err:
                print(f"[WARN] create_project {name} failed: {text[:120]}")
            return f"{name}-{RUN}"

        async def put(p, path, content):
            return await call("write_file", {"project": p, "path": path, "content": content})

        async def build(p, **kw):
            return await js("compile", {"project": p, **kw})

        tools = {t.name for t in (await c.list_tools()).tools}
        expected = {"create_project", "list_projects", "delete_project", "list_files", "read_file", "write_file", "delete_file", "move_file",
                    "upload_zip", "download_zip", "replace_text", "edit_lines", "apply_patch", "insert_snippet", "get_structure",
                    "check_references", "compile", "clean", "get_pdf", "render_page", "pdf_info", "pdf_text", "pdf_optimize", "lint", "format",
                    "render_math", "convert", "check_package", "tex_versions", "list_templates"}
        check(f"all {len(expected)} tools exposed", expected <= tools, expected - tools)

        # =============== functional: templates and engines ===============
        for tpl in ("article", "report", "ieee", "beamer", "letter", "cv"):
            p = await mk(f"t-{tpl}", tpl, title="Test & Title", author="A. Author")
            err, r = await build(p)
            check(f"template {tpl} compiles", r.get("success") and r.get("pages", 0) >= 1, r.get("log_tail") or r.get("diagnostics"))
        p = await mk("engines")
        for eng in ("pdflatex", "xelatex", "lualatex"):
            err, r = await build(p, engine=eng)
            check(f"engine {eng}", r.get("success"), r.get("log_tail") or r.get("diagnostics"))

        # Unicode / non-Latin script with XeLaTeX and LuaLaTeX
        uni = "\\documentclass{article}\n\\usepackage{fontspec}\\setmainfont{FreeSerif}\n\\begin{document}\nسلام دنیا — Привет — 你好\n\\end{document}\n"
        pu = await mk("unicode")
        await put(pu, "main.tex", uni)
        for eng in ("xelatex", "lualatex"):
            err, r = await build(pu, engine=eng)
            _, t = await js("pdf_text", {"project": pu})
            check(f"{eng}: Arabic/Persian/Cyrillic text rendered", r.get("success") and any("\u0600" <= ch <= "\u06ff" for ch in t.get("text", "")) and "Привет" in t.get("text", ""), r.get("log_tail") or t)

        # =============== bibliography flows ===============
        pb = await mk("bibtex", "ieee")
        err, r = await build(pb)
        _, t = await js("pdf_text", {"project": pb})
        check("bibtex: citation resolved and bibliography typeset", r.get("success") and "Knuth" in t.get("text", "") and "TeXbook" in t.get("text", ""), t.get("text", "")[:200])
        pbl = await mk("biber")
        await put(pbl, "main.tex", "\\documentclass{article}\n\\usepackage[backend=biber]{biblatex}\n\\addbibresource{refs.bib}\n\\begin{document}\nSee \\cite{lamport}.\n\\printbibliography\n\\end{document}\n")
        await put(pbl, "refs.bib", "@book{lamport, author={Leslie Lamport}, title={LaTeX: A Document Preparation System}, publisher={Addison-Wesley}, year={1994}}\n")
        err, r = await build(pbl)
        _, t = await js("pdf_text", {"project": pbl})
        check("biber: bibliography typeset", r.get("success") and "Lamport" in t.get("text", ""), r.get("log_tail") or t)

        # =============== diagnostics ===============
        pd = await mk("diag")
        await put(pd, "main.tex", "\\documentclass{article}\n\\usepackage{nosuchpackage123}\n\\begin{document}\nHello \\undefinedcmd world.\nSee \\ref{nolabel} and \\cite{nokey}.\n\\end{document}\n")
        err, r = await build(pd)
        d = r.get("diagnostics", [])
        check("broken doc: success=false with errors", r.get("success") is False and r["counts"]["error"] >= 1, r)
        check("missing package error has file/line/hint", any("nosuchpackage123" in x["message"] and x.get("hint") for x in d), d[:3])
        await put(pd, "main.tex", "\\documentclass{article}\n\\begin{document}\nLine three.\nHello \\undefinedcmd world.\nSee \\ref{nolabel} and \\cite{nokey}.\n\\end{document}\n")
        err, r = await build(pd)
        d = r.get("diagnostics", [])
        e1 = [x for x in d if x["severity"] == "error"]
        check("error pinpointed: file, line 4, context", e1 and e1[0]["file"] == "main.tex" and e1[0]["line"] == 4 and "undefinedcmd" in (e1[0].get("context") or ""), e1[:1])
        check("undefined ref/cite surfaced as warnings", any("nolabel" in x["message"] for x in d) and any("nokey" in x["message"] for x in d), d)

        # =============== editing tools then compile ===============
        pe = await mk("edit")
        err, r = await js("insert_snippet", {"project": pe, "path": "main.tex", "snippet": "table", "values": {"CAPTION": "Scores", "LABEL": "scores"}})
        check("insert_snippet", not err and "booktabs" in r["needs_packages"], r)
        err, r = await js("replace_text", {"project": pe, "path": "main.tex", "find": "Write here.", "replace": "Intro text, see Table~\\ref{tab:scores}."})
        check("replace_text literal (backslashes preserved)", r.get("replacements") == 1)
        err, rd = await js("read_file", {"project": pe, "path": "main.tex", "numbered": True})
        check("read_file numbered", "    1| \\documentclass" in rd["content"])
        ln = next(i for i, x in enumerate(rd["content"].split("\n"), 1) if "Intro text" in x)
        err, r = await js("edit_lines", {"project": pe, "path": "main.tex", "start_line": ln, "end_line": ln, "new_text": "Edited line.\nSecond line."})
        check("edit_lines replaces a range", not err and r["lines_added"] == 2, r)
        patch = "@@ -%d,2 +%d,2 @@\n Edited line.\n-Second line.\n+Patched line.\n" % (ln, ln)
        err, r = await js("apply_patch", {"project": pe, "path": "main.tex", "patch": patch})
        check("apply_patch", not err, r)
        err, r = await js("apply_patch", {"project": pe, "path": "main.tex", "patch": "@@ -1,1 +1,1 @@\n-WRONG CONTEXT\n+x\n"})
        check("apply_patch with wrong context fails and writes nothing", err)
        err, r = await js("insert_snippet", {"project": pe, "path": "main.tex", "snippet": "equation", "values": {"EXPRESSION": "E=mc^2", "LABEL": "emc"}, "after_text": "Patched line."})
        err, r = await build(pe)
        check("edited project compiles (booktabs table + equation)", r.get("success"), r.get("log_tail") or r.get("diagnostics"))
        err, r = await js("check_references", {"project": pe})
        check("check_references clean after edits", not r["undefined_references"], r["undefined_references"])
        err, r = await js("get_structure", {"project": pe})
        check("get_structure outline + labels", r["outline"] and {"tab:scores", "eq:emc"} <= {x["name"] for x in r["labels"]}, r["labels"])

        # =============== lint / format / convert / optimize / render ===============
        pl = await mk("lint")
        await put(pl, "main.tex", "\\documentclass{article}\n\\begin{document}\nA sentence.Another one with a  double space and wrong... dots\n\\end{document}\n")
        err, r = await js("lint", {"project": pl})
        check("lint returns structured findings", r["count"] >= 1 and {"line", "severity", "message"} <= set(r["findings"][0]), r)
        await put(pl, "main.tex", "\\documentclass{article}\n\\begin{document}\n\\begin{itemize}\n\\item a\n\\item b\n\\end{itemize}\n\\end{document}\n")
        err, r = await js("format", {"project": pl, "write": True})
        _, rd = await js("read_file", {"project": pl, "path": "main.tex"})
        err, rc = await build(pl)
        check("format (latexindent) indents and still compiles", not err and r.get("changed") and "\n\t\\item a" in rd["content"].replace("    ", "\t").replace("  ", "\t") and rc.get("success"), (r, rd["content"][:200]))
        err, r = await js("pdf_optimize", {"project": pe, "method": "qpdf"})
        check("pdf_optimize qpdf", not err and r["optimized_bytes"] > 0, r)
        err, r = await js("pdf_optimize", {"project": pe, "method": "gs", "quality": "screen"})
        check("pdf_optimize gs", not err and r["optimized_bytes"] > 0, r)
        err, text, _, content = await call("get_pdf", {"project": pe, "optimized": True})
        check("get_pdf optimized returns a PDF resource", not err and any(type(x).__name__ == "EmbeddedResource" and base64.b64decode(x.resource.blob)[:4] == b"%PDF" for x in content))
        err, text, _, content = await call("render_page", {"project": pe, "page": 1, "dpi": 80})
        check("render_page returns a PNG", not err and content and base64.b64decode(content[0].data)[:4] == b"\x89PNG")
        err, text, _, content = await call("render_page", {"project": pe, "page": 99})
        check("render_page out of range -> isError", err)
        err, text, _, _ = await call("render_page", {"project": pe, "dpi": 5000})
        check("render_page absurd dpi -> isError", err)
        err, t, _, content = await call("render_math", {"latex": "\\sum_{i=1}^n i = \\frac{n(n+1)}{2}", "format": "svg"})
        check("render_math svg", not err and "<svg" in t)
        err, t, _, content = await call("render_math", {"latex": "x^2", "format": "png"})
        check("render_math png", not err and content and base64.b64decode(content[0].data)[:4] == b"\x89PNG")
        err, t, _, _ = await call("render_math", {"latex": "\\undefinedmacro"})
        check("render_math error reported cleanly", err and "render" in t.lower(), t)
        pm = await mk("convert")
        await put(pm, "notes.md", "# Title\n\nSome *markdown* with $x^2$.\n")
        err, t, _, content = await call("convert", {"project": pm, "source": "notes.md", "to": "latex"})
        check("convert md -> latex", not err and "\\section" in t and "markdown" in t, t[:200])
        err, t, _, content = await call("convert", {"project": pm, "source": "notes.md", "to": "html"})
        check("convert md -> html", not err and "<h1" in t and "<em>markdown</em>" in t, t[:200])
        err, t, _, content = await call("convert", {"project": pm, "source": "notes.md", "to": "docx"})
        check("convert to docx is refused cleanly (cannot be produced in the sandbox)", err, t[:120])
        await put(pm, "evil.md", "![x](/tmp/canary-secret.txt)\n\n```{=latex}\n\\input{/etc/passwd}\n```\n")
        err, t, _, _ = await call("convert", {"project": pm, "source": "evil.md", "to": "latex"})
        check("pandoc --sandbox: no file reads via image/include", "CANARY" not in t and "root:" not in t, t[:200])
        err, r = await js("check_package", {"name": "IEEEtran"})
        check("check_package finds a class", r["installed"])
        err, r = await js("check_package", {"name": "definitelynotapackage"})
        check("check_package reports missing", r["installed"] is False)
        err, r = await js("tex_versions", {})
        check("tex_versions", any("pdfTeX" in v or "TeX" in v for v in r["versions"]), r)

        # =============== zip round trip with an image ===============
        pz = await mk("zip")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("proj/main.tex", "\\documentclass{article}\\usepackage{graphicx}\\begin{document}\\includegraphics[width=1cm]{img/dot.png}\\end{document}")
            z.writestr("proj/img/dot.png", png())
        err, r = await js("upload_zip", {"project": pz, "zip_base64": base64.b64encode(buf.getvalue()).decode(), "replace": True})
        err, rc = await build(pz)
        check("upload_zip with image then compile", not err and r["files_imported"] == 2 and rc.get("success"), (r, rc.get("log_tail")))
        err, text, _, content = await call("download_zip", {"project": pz})
        zb = base64.b64decode(next(x.resource.blob for x in content if type(x).__name__ == "EmbeddedResource"))
        check("download_zip round trips", "main.tex" in zipfile.ZipFile(io.BytesIO(zb)).namelist())
        err, r = await js("clean", {"project": pz})
        err, r = await js("list_files", {"project": pz, "include_build": True})
        check("clean removes build output", not any(f["path"].startswith("_build/") for f in r["files"]), r)

        # =============== concurrency ===============
        pc = await mk("conc")
        results = await asyncio.gather(*(build(pc) for _ in range(3)))
        check("3 concurrent compiles all succeed", all(r.get("success") for _, r in results), [r.get("log_tail") for _, r in results])

        # =============== HOSTILE INPUT ===============
        print("\n--- hostile input ---")
        sh("latex-worker", "echo CANARY-7731-TXT > /tmp/canary-secret.txt; printf '@book{canary,title={CANARY-BIB-7731},author={X},year={2000}}' > /tmp/canary.bib; rm -f /tmp/PWNED_*")

        async def hostile(label, files, engine="pdflatex", timeout=30, main="main.tex"):
            p = await mk("h-" + label)
            for path, content in files.items():
                await put(p, path, content)
            t0 = time.time()
            err, r = await build(p, engine=engine, timeout=timeout)
            _, t = await js("pdf_text", {"project": p}) if r.get("pdf") else (False, {"text": ""})
            blob = json.dumps(r) + t.get("text", "")
            return r, blob, time.time() - t0

        wrap = lambda body, pre="": "\\documentclass{article}\n" + pre + "\\begin{document}\n" + body + "\n\\end{document}\n"
        # NOTE the space after %s: without it TeX expands \ifeof while still scanning the file name and never opens the file.
        read_secret = "\\newread\\f\\openin\\f=%s \\ifeof\\f NOREAD\\else\\read\\f to\\x LEAK:\\x\\fi"
        for label, path in [("passwd", "/etc/passwd"), ("canary", "/tmp/canary-secret.txt"), ("parent", "../secret.txt"), ("environ", "/proc/self/environ")]:
            r, blob, _ = await hostile("openin-" + label, {"main.tex": wrap(read_secret % path)})
            check(f"\\openin {path} is blocked", "CANARY" not in blob and "root:" not in blob and "TEXMFVAR" not in blob and "shell_escape" not in blob.replace("shell_escape=f", ""), blob[:200])
        r, blob, _ = await hostile("input-canary", {"main.tex": wrap("\\input{/tmp/canary-secret.txt}")})
        check("\\input of absolute canary path is blocked", "CANARY" not in blob and r.get("success") is False, blob[:200])
        r, blob, _ = await hostile("input-dotdot", {"main.tex": wrap("\\input{../../../../tmp/canary-secret}")})
        check("\\input with ../ is blocked", "CANARY" not in blob, blob[:200])
        r, blob, _ = await hostile("verbatiminput", {"main.tex": wrap("\\verbatiminput{/etc/passwd}", "\\usepackage{verbatim}\n")})
        check("\\verbatiminput /etc/passwd blocked", "root:" not in blob, blob[:200])
        r, blob, _ = await hostile("write18", {"main.tex": wrap("\\immediate\\write18{touch /tmp/PWNED_write18}\\immediate\\write18{echo SHELLRAN > shell.txt}")})
        check("\\write18 does not execute", sh("latex-worker", "ls /tmp | grep -c PWNED_").stdout.strip() == "0", blob[:200])
        r, blob, _ = await hostile("shellescape-pkg", {"main.tex": wrap("\\immediate\\write18{touch /tmp/PWNED_sh2}", "\\usepackage{catchfile}\n")})
        r, blob, _ = await hostile("openout-abs", {"main.tex": wrap("\\newwrite\\o\\immediate\\openout\\o=/tmp/PWNED_openout\\immediate\\write\\o{x}\\immediate\\closeout\\o")})
        check("\\openout to an absolute path is blocked", sh("latex-worker", "ls /tmp | grep -c PWNED_").stdout.strip() == "0", blob[:200])
        r, blob, _ = await hostile("openout-up", {"main.tex": wrap("\\newwrite\\o\\immediate\\openout\\o=../escape.tex\\immediate\\write\\o{x}\\immediate\\closeout\\o")})
        check("\\openout ../ is blocked", "escape.tex" not in (sh("latex-worker", "find /tmp -name escape.tex 2>/dev/null").stdout), blob[:200])
        # LuaLaTeX: shell-escape-style functions must stay disabled. (Reading files is NOT restricted for Lua - see below.)
        for label, code in [("os.execute", 'os.execute("touch /tmp/PWNED_lua_exec")'), ("io.popen", 'local h=io.popen("touch /tmp/PWNED_lua_popen") if h then h:close() end'),
                            ("os.spawn", 'os.spawn({"touch","/tmp/PWNED_lua_spawn"})'), ("os.rename", 'os.rename("/etc/hostname","/tmp/PWNED_lua_rename")'),
                            ("write abs", 'local f=io.open("/tmp/PWNED_lua_write","w") if f then f:write("x") f:close() end')]:
            r, blob, _ = await hostile("lua-" + label.replace(" ", "-").replace(".", ""), {"main.tex": wrap("\\directlua{%s}" % code)}, engine="lualatex")
            gone = sh("latex-worker", "ls /tmp | grep -c PWNED_").stdout.strip() == "0"
            check(f"lualatex \\directlua {label} has no effect outside the job dir", gone, blob[:250])
            sh("latex-worker", "rm -f /tmp/PWNED_*")
        r, blob, _ = await hostile("lua-read", {"main.tex": wrap('\\directlua{local f=io.open("/tmp/canary-secret.txt") if f then tex.print("LEAK "..f:read("*a")) end}')}, engine="lualatex")
        print(f"[INFO] lualatex io.open of a canary file: {'READABLE (documented limitation: Lua cannot be sandboxed without breaking fonts)' if 'CANARY' in blob else 'blocked'}")
        env_dump = sh("latex-worker", "env").stdout
        check("the worker environment holds no secrets (what Lua could read)", not any(k in env_dump.upper() for k in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL")), env_dump[:200])
        r, blob, _ = await hostile("lua-bibtex-strict", {"main.tex": wrap("\\cite{canary}\\bibliographystyle{plain}\\bibliography{/tmp/canary}")}, engine="lualatex")
        check("bibtex stays strict even in a lualatex build", "CANARY-BIB" not in blob, blob[:200])
        # latexmkrc: the API refuses to store one; the worker must ALSO ignore one (defence in depth).
        err, t, _, _ = await call("write_file", {"project": await mk("h-rc"), "path": "latexmkrc", "content": "system('touch /tmp/PWNED_rc');"})
        check("API refuses to store a latexmkrc", err)
        err, t, _, _ = await call("write_file", {"project": f"h-rc-{RUN}", "path": ".latexmkrc", "content": "x"})
        check("API refuses to store a hidden .latexmkrc", err)
        probe = (
            "import base64,io,json,tarfile,httpx\n"
            "b=io.BytesIO()\n"
            "with tarfile.open(fileobj=b,mode='w:gz') as t:\n"
            "  for n,d in {'main.tex':b'\\\\documentclass{article}\\\\begin{document}x\\\\end{document}','latexmkrc':b'system(\"touch /tmp/PWNED_rc\");'}.items():\n"
            "    i=tarfile.TarInfo(n);i.size=len(d);t.addfile(i,io.BytesIO(d))\n"
            "r=httpx.post('http://latex-worker:9100/run',json={'tool':'compile','args':{'main':'main.tex'},'files_b64':base64.b64encode(b.getvalue()).decode()},timeout=60).json()\n"
            "print(r['ok'],r['returncode'],'_build/main.pdf' in r['outputs'])\n"
        )
        out = subprocess.run(COMPOSE + ["exec", "-T", "latex", "python", "-c", probe], capture_output=True, text=True)
        check("worker ignores a project latexmkrc (-norc), still compiles", "True 0 True" in out.stdout and sh("latex-worker", "ls /tmp | grep -c PWNED_").stdout.strip() == "0", out.stdout + out.stderr[-200:])

        # biber/bibtex read paths are NOT covered by kpathsea paranoia: test them with a canary.
        r, blob, _ = await hostile("biber-canary", {"main.tex": wrap("\\cite{canary}\\printbibliography", "\\usepackage[backend=biber]{biblatex}\n\\addbibresource{/tmp/canary.bib}\n")})
        biber_leak = "CANARY-BIB" in blob
        print(f"[INFO] biber absolute .bib read of a canary file: {'LEAKED' if biber_leak else 'blocked'}")
        check("biber cannot read an absolute .bib canary", not biber_leak, blob[:300])
        r, blob, _ = await hostile("bibtex-canary", {"main.tex": wrap("\\cite{canary}\\bibliographystyle{plain}\\bibliography{/tmp/canary}")})
        check("bibtex cannot read an absolute .bib canary", "CANARY-BIB" not in blob, blob[:300])

        # cross-project isolation: another project's files are not even present in the sandbox.
        pa = await mk("iso-a")
        await put(pa, "secret.tex", "ISOLATION-SECRET-5512")
        pb2 = await mk("iso-b")
        await put(pb2, "main.tex", wrap(f"\\input{{/data/ws/owner/{pa}/secret}} \\input{{../{pa}/secret}}"))
        err, rb = await build(pb2)
        check("another project's file is unreachable from the sandbox", "ISOLATION-SECRET" not in json.dumps(rb))

        # resource abuse: each must end in a clean result and the service must stay healthy.
        r, blob, secs = await hostile("loop", {"main.tex": wrap("\\def\\x{\\x}\\x")}, timeout=5)
        check("infinite loop is killed at the time limit", r.get("timed_out") is True and secs < 30, (r.get("timed_out"), secs))
        r, blob, secs = await hostile("membomb", {"main.tex": wrap("\\def\\a{x\\a\\a}\\a")}, timeout=30)
        check("exponential expansion ends cleanly (TeX capacity / limit)", r.get("success") is False and secs < 60, (r.get("log_tail") or "")[-150:])
        r, blob, secs = await hostile("logflood", {"main.tex": wrap("\\def\\a{\\message{AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA}\\a}\\a")}, timeout=10)
        check("log flood returns a normal, bounded result (log truncated, not a failure)", r.get("success") is False and "counts" in r and secs < 40 and len(json.dumps(r)) < 200_000, (secs, str(r)[:200]))
        r, blob, secs = await hostile("deeprec", {"main.tex": wrap("\\def\\a#1{\\a{#1#1}}\\a{x}")}, timeout=20)
        check("runaway growth ends cleanly", r.get("success") is False and secs < 60, secs)
        err, rr = await build(await mk("after-abuse"))
        check("service still compiles normally after abuse", rr.get("success"), rr)
        leftovers = sh("latex-worker", "ls /tmp/jobs 2>/dev/null | wc -l").stdout.strip()
        check("worker leaves no job directories behind", leftovers == "0", leftovers)
        procs = sh("latex-worker", "ps -eo stat,comm | grep -cE 'pdflatex|xelatex|lualatex|latexmk|perl|biber' || true").stdout.strip()
        check("no stray or zombie TeX processes remain (init reaps)", procs == "0", sh("latex-worker", "ps -eo pid,stat,comm").stdout)

        # =============== path traversal across every file tool ===============
        print("\n--- path traversal in file tools ---")
        pt = await mk("trav")
        bads = ["../x.tex", "../../etc/passwd", "/etc/passwd", ".hidden.tex", "a/../../x.tex", "_build/x.tex", "x\\y.tex", "run.sh"]
        for bad in bads:
            res = [
                await call("read_file", {"project": pt, "path": bad}),
                await call("write_file", {"project": pt, "path": bad, "content": "x"}),
                await call("delete_file", {"project": pt, "path": bad}),
                await call("move_file", {"project": pt, "source": "main.tex", "destination": bad}),
                await call("replace_text", {"project": pt, "path": bad, "find": "a", "replace": "b"}),
                await call("edit_lines", {"project": pt, "path": bad, "start_line": 1, "end_line": 1, "new_text": "x"}),
                await call("apply_patch", {"project": pt, "path": bad, "patch": "@@ -1 +1 @@\n-a\n+b\n"}),
                await call("insert_snippet", {"project": pt, "path": bad, "snippet": "table"}),
                await call("lint", {"project": pt, "path": bad}),
                await call("compile", {"project": pt, "main": bad}),
            ]
            leaked = [t for e, t, _, _ in res if "root:x" in t]
            check(f"path {bad!r}: rejected by all 10 file tools", all(e for e, *_ in res) and not leaked, [t[:80] for e, t, _, _ in res if not e][:2])
        for badproj in ["../other", "a/b", ".hidden", "", "x" * 70, "p q"]:
            e1, *_ = await call("read_file", {"project": badproj, "path": "main.tex"})
            e2, *_ = await call("create_project", {"name": badproj})
            e3, *_ = await call("delete_project", {"name": badproj})
            check(f"project name {badproj[:20]!r} rejected", e1 and e2 and e3)
        for name, files in {"zip-slip": {"../evil.tex": "x"}, "absolute": {"/evil.tex": "x"}, "script": {"run.sh": "x"}, "lua": {"x.lua": "x"}}.items():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n, d in files.items():
                    z.writestr(n, d)
            e, t, _, _ = await call("upload_zip", {"project": f"zip-{name}-{RUN}", "zip_base64": base64.b64encode(buf.getvalue()).decode()})
            check(f"upload_zip {name} rejected", e, t[:120])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("big.tex", "A" * (30 * 1024 * 1024))
        e, t, _, _ = await call("upload_zip", {"project": f"zip-bomb-{RUN}", "zip_base64": base64.b64encode(buf.getvalue()).decode()})
        check("upload_zip decompression bomb rejected", e, t[:120])
        e, t, _, _ = await call("write_file", {"project": pt, "path": "big.tex", "content": "A" * (11 * 1024 * 1024)})
        check("write_file over the per-file limit rejected", e, t[:120])

        # ReDoS in replace_text must time out, not hang.
        pr = await mk("redos")
        await put(pr, "main.tex", "a" * 50 + "!\n")
        t0 = time.time()
        e, t, _, _ = await call("replace_text", {"project": pr, "path": "main.tex", "find": "(a|aa)+$", "replace": "x", "regex": True})
        check("catastrophic regex is cut off (isError, quickly)", e and time.time() - t0 < 15, (t[:100], time.time() - t0))

        # =============== network isolation of both tiers ===============
        print("\n--- network isolation ---")
        for svc in ("latex", "latex-worker"):
            out = sh(svc, "python -c \"import urllib.request;urllib.request.urlopen('http://example.com',timeout=5)\" 2>&1 | tail -1")
            check(f"{svc}: no route to the internet", "example.com" not in out.stdout or "error" in out.stdout.lower() or "unreach" in out.stdout.lower() or out.returncode != 0, out.stdout)
            out2 = sh(svc, "python -c \"import socket;socket.create_connection(('1.1.1.1',443),timeout=4);print('CONNECTED')\" 2>&1 | tail -1")
            check(f"{svc}: cannot open a raw connection to 1.1.1.1", "CONNECTED" not in out2.stdout, out2.stdout)
            for host in ("dokploy", "github", "web", "searxng", "google-workspace"):
                out3 = sh(svc, f"python -c \"import socket;socket.gethostbyname('{host}');print('RESOLVED')\" 2>&1 | tail -1")
                check(f"{svc}: cannot resolve {host}", "RESOLVED" not in out3.stdout, out3.stdout)
        out = sh("latex-worker", "ls /data 2>&1; id -u")
        check("worker has no workspace volume and runs as uid 10001", "No such file" in out.stdout and "10001" in out.stdout, out.stdout)

        # final cleanup of everything this run created
        ls_err, ls = await js("list_projects", {})
        for pr_ in ls.get("projects", []):
            if pr_["name"].endswith(RUN) or pr_["name"] == f"h-rc-{RUN}":
                await call("delete_project", {"name": pr_["name"]})

    await http.aclose()
    sh("latex-worker", "rm -f /tmp/canary-secret.txt /tmp/canary.bib")
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


asyncio.run(main())
