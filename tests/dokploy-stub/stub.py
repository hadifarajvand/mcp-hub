"""Minimal fake of the Dokploy API for local tests.

Requires the x-api-key header, and returns a secret-bearing field so tests can
assert that the MCP server redacts it.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

API_KEY = "stub-dokploy-api-key-for-local-tests"
PROJECTS = [{
    "projectId": "proj_stub_1",
    "name": "stub-project",
    "description": "returned by tests/dokploy-stub",
    "env": "DATABASE_PASSWORD=super-secret-value-should-be-redacted",
}]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("x-api-key") != API_KEY:
            return self._send(401, {"message": "Unauthorized"})
        if self.path.split("?")[0] == "/api/project.all":
            return self._send(200, PROJECTS)
        self._send(404, {"message": "not found"})

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


HTTPServer(("0.0.0.0", 3000), Handler).serve_forever()
