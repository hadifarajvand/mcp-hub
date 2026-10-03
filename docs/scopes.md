# Scopes

One OAuth resource per MCP route; a scope belongs to exactly one route.

| Route | Scope | Grants | Sensitive* |
|---|---|---|---|
| `/web/mcp` | `web:read` | search the web and fetch pages | |
| `/latex/mcp` | `latex:use` | create/edit/compile your LaTeX projects | |
| `/transcriber/mcp` | `transcriber:use` | transcribe audio with your Google Cloud quota | |
| `/github/mcp` | `github:read` | read repos, issues, PRs, code | |
| `/github/mcp` | `github:write` | create/change issues, PRs, branches, files | yes |
| `/google-workspace/mcp` | `workspace:use` | read **and modify** Gmail, Drive, Docs, Sheets, Calendar | yes |
| `/dokploy/mcp` | `dokploy:use` | manage the Dokploy server, including deleting applications | yes |

\* Sensitive scopes show a red warning on the consent screen and get 5-minute access tokens.

## Where "read vs write" is real, and where it is not

Authorization is enforced **per MCP route at the gateway**, not per tool.

- **GitHub** is the one MCP with a real read/write split, because the upstream server supports it: the gateway passes
  `X-MCP-Readonly` derived from the token's scope. It is **fail-closed**: only an explicit grant lifts read-only; a
  missing, empty or unexpected value stays read-only (verified in `tests/gateway_failclosed.py`). `github:write`
  is offered **only if** you set `GITHUB_READ_ONLY=0`, because the server's own read-only mode is a hard cap that no header
  can lift (verified), and offering a scope that cannot work would make the consent screen lie.
- **Dokploy** and **Google Workspace** are all-or-nothing. Their upstreams offer no per-request restriction, so
  `dokploy:use` means everything your Dokploy API key can do. Scope that key and your Google OAuth client minimally.
- The GitHub PAT, Dokploy key and Google credentials are shared server-side secrets; OAuth here controls *who may use
  them*, not what they can reach.

Adding a scope or route: edit `servers/hub-auth/hubauth/resources.py` and add the `import mcp_route` line to the Caddyfile.
