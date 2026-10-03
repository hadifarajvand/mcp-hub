# OAuth: how access to the hub works

Every MCP route (`/web/mcp`, `/latex/mcp`, ...) requires an OAuth 2.1 access token. There is no shared secret.

```
client ── 401 + WWW-Authenticate(resource_metadata) ──> discovers hub-auth (RFC 9728 / RFC 8414)
client ── POST /register ──> public client + client_id           (Dynamic Client Registration, RFC 7591)
client ── GET /authorize (PKCE S256, resource=<route URL>) ──> you see the consent page
you    ── owner password + 6-digit authenticator code ──> approve
client ── POST /token (code + verifier) ──> short-lived access token + rotating refresh token
client ── Authorization: Bearer <token> ──> gateway asks hub-auth: valid? for THIS route? scope?
```

## What protects what

| Property | How |
|---|---|
| Only you can grant access | Consent needs your **password and a fresh TOTP code every time**. Codes are single-use (replay-proof); 5 failures/15 min/IP and 20 globally lock sign-in (existing tokens keep working). |
| A stolen token is limited | Opaque 256-bit tokens, stored only as SHA-256 hashes. Access 15 min (5 min for sensitive scopes). Refresh 30 days, **rotating**; re-using an old refresh token or auth code revokes the whole grant. Hard cap 180 days, then you log in again. |
| A token for one MCP is useless on another | Each route is its own OAuth resource (RFC 8707). `/web` tokens are rejected on `/latex`, etc. |
| Scopes are enforced | A token carries only the scopes you approved (e.g. `github:read`). Refresh can narrow, never widen. |
| Revocation is immediate | Every request is checked by hub-auth, so `/revoke` or the CLI takes effect on the next call. |
| Upstream never sees client tokens | The gateway strips `Authorization`, strips every client-supplied `X-Hub-*` identity header, and sets identity itself. |
| Clients cannot be tricked into leaking codes | Exact redirect-URI match; only https, loopback http, or allow-listed app schemes may register. A client whose redirect is neither on your allow-list nor a loopback address (a program on your own computer) shows an "unverified application" warning **and cannot be approved without ticking a confirmation box that you started the connection yourself** (enforced server-side). A bad `OAUTH_REDIRECT_ALLOWLIST` (e.g. `*`) stops hub-auth from starting. |

## Scopes

See [scopes.md](scopes.md). Scopes are **per MCP**, not per tool.

## Operating it

```bash
./scripts/gen-owner.sh                      # once: prints HUB_OWNER_PASSWORD_HASH and HUB_OWNER_TOTP_SECRET
docker compose exec hub-auth python -m hubauth list-grants
docker compose exec hub-auth python -m hubauth revoke-client <client_id>
docker compose exec hub-auth python -m hubauth revoke-all     # emergency: every client must re-authorize
```
In Dokploy use the service's *Terminal* tab for the same commands. All security events are JSON lines in the
`hub-auth` log (registrations, logins, denials, reuse detection); token values are never logged.

## Connecting clients

| Client | How |
|---|---|
| Claude Code | `claude mcp add --transport http web https://mcp.example.com/web/mcp`, then `/mcp` → Authenticate (opens the consent page) |
| claude.ai / Claude Desktop | Settings → Connectors → *Add custom connector* → `https://mcp.example.com/web/mcp` |
| ChatGPT | Settings → Connectors → create → `https://mcp.example.com/web/mcp` (the `search` and `fetch` tools are ChatGPT-compatible) |

Add one connector per MCP: each is a separate authorization (that is the audience binding at work).

## Limits (read these)

- **Dynamic Client Registration is open**, because claude.ai and ChatGPT need it. Anyone can register a client and send you
  to the consent page. The defences are the password + TOTP gate, the unverified-application warning and mandatory confirmation,
  registration rate limits, and caps on unused registrations and in-flight authorization requests. Approve only connections *you* started.
- Sign-in lockout is a deliberate trade-off: someone who can reach `/consent` can lock *new* authorizations for ~15 minutes.
  Existing tokens are unaffected.
- Not implemented: Client ID Metadata Documents (ChatGPT also supports DCR, which is used), the client-credentials grant
  (no headless/CI clients), per-tool scopes, login through an upstream identity provider.
- Single owner. All grants belong to one subject (`owner`).
- Real claude.ai / ChatGPT connector flows have **not** been exercised (no such client in the build environment); the
  protocol is verified with the MCP SDK's own OAuth client and 190+ attack/protocol tests.
- TOTP needs an accurate server clock.
