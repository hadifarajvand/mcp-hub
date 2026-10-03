# Adding an MCP

1. **Container**: add `servers/<name>/Dockerfile` (pin the upstream version; run
   non-root) or reuse a published image. The server must speak MCP
   *streamable HTTP* on a fixed port. For stdio-only servers, wrap them with a
   stdio→HTTP bridge such as `supergateway`.
2. **Compose**: copy an existing service in `docker-compose.yml`, keep
   `<<: *hardening`, `read_only: true`, resource limits, and pass secrets as
   `${VAR:-}` from the environment. Add it to the gateway's `depends_on`.
3. **Gateway + scopes**: add one line to `gateway/Caddyfile`:
   `import mcp_route <name> <service>:<port>` → served at `/<name>/mcp`, behind OAuth automatically.
   Then declare the route and its scope(s) in `servers/hub-auth/hubauth/resources.py` (mark anything that can change
   state or reach secrets as `sensitive`). A route missing from that file is refused by hub-auth (HTTP 500), never opened.
   If the server validates `Host`/`Origin` (the Python SDK does), allow the
   service name, e.g. `MCP_ALLOWED_HOSTS=<service>:<port>`.
4. **Test**: add the route to the loops in `tests/security.sh`, `tests/oauth_e2e.py` (cross-route rejection) and a case in
   `tests/smoke.py`, then run them.
5. Document its env vars in `.env.example`.
