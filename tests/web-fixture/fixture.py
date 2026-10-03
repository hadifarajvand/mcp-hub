"""Local test server for the web MCP (dev overlay only; reachable only on fetchnet)."""
import gzip
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARTICLE = b"""<!doctype html><html lang="en"><head><title>Fixture Article</title>
<meta name="author" content="Ada Lovelace"><meta name="description" content="A test article"></head>
<body><nav><a href="/nav">NAVIGATION NOISE</a></nav><article><h1>The Fixture Article</h1>
<p>Paragraph one contains the unique marker PINEAPPLE-7421 and enough words to be recognised as main content by the extractor.
The quick brown fox jumps over the lazy dog while the extractor considers whether this is boilerplate or real content.</p>
<p>Paragraph two continues with more substantial prose so that the readability heuristics treat the whole block as the article body,
including a <a href="/linked-page">relevant link</a> and an <a href="https://example.org/ext">external link</a>.</p>
<ul><li>alpha</li><li>beta</li></ul></article><footer>COOKIE BANNER NOISE</footer></body></html>"""

def build_pdf(text: str) -> bytes:
    """A minimal but valid single-page PDF with a correct xref table."""
    stream = f"BT /F1 12 Tf 20 50 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<</Root 1 0 R/Size %d>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


PDF = build_pdf("PDF-MARKER-5530 hello")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/robots.txt":
            return self.send(200, b"User-agent: *\nDisallow: /private\n", "text/plain")
        if p == "/article":
            return self.send(200, ARTICLE)
        if p == "/private":
            return self.send(200, b"<html><body>secret</body></html>")
        if p == "/json":
            return self.send(200, json.dumps({"hello": "world"}).encode(), "application/json")
        if p == "/text":
            return self.send(200, b"plain text body", "text/plain")
        if p == "/pdf":
            return self.send(200, PDF, "application/pdf")
        if p == "/binary":
            return self.send(200, b"\x00\x01\x02", "application/octet-stream")
        if p == "/redirect":
            return self.send(302, headers={"Location": "/article"})
        if p == "/redirect-metadata":
            return self.send(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        if p == "/redirect-internal":
            return self.send(302, headers={"Location": "http://dokploy-stub:3000/api/project.all"})
        if p == "/redirect-loop":
            return self.send(302, headers={"Location": "/redirect-loop"})
        if p == "/gzip-bomb":
            return self.send(200, gzip.compress(b"A" * (80 * 1024 * 1024)), "text/plain", {"Content-Encoding": "gzip"})
        if p == "/huge":
            return self.send(200, b"B" * (8 * 1024 * 1024), "text/plain")
        if p == "/slow":
            time.sleep(40)
            return self.send(200, b"late")
        if p == "/404":
            return self.send(404, b"nope")
        if p == "/long":
            body = ("<html><body><article>" + "".join(f"<p>Sentence number {i} of the long document, with filler words to pad it out.</p>" for i in range(2000)) + "</article></body></html>").encode()
            return self.send(200, body)
        self.send(404, b"not found")


ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
