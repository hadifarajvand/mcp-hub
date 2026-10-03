"""Server-rendered consent page. No JavaScript; strict CSP; every dynamic value is HTML-escaped."""

from __future__ import annotations

import html
import secrets
from urllib.parse import urlsplit

from starlette.responses import HTMLResponse

from .resources import RESOURCES

_CSS = """
body{font:16px/1.5 system-ui,sans-serif;max-width:34rem;margin:2rem auto;padding:0 1rem;color:#1b1f23;background:#fafafa}
@media(prefers-color-scheme:dark){body{background:#14161a;color:#e6e8eb}input{background:#1f2227;color:#e6e8eb}}
h1{font-size:1.4rem}.card{border:1px solid #8884;border-radius:.6rem;padding:1rem 1.2rem;margin:1rem 0}
.warn{border-color:#c62828;background:#c6282814}.ok{border-color:#2e7d32}.muted{opacity:.75;font-size:.9rem}
code{background:#8882;padding:.1rem .35rem;border-radius:.25rem;word-break:break-all}
label{display:block;margin:.8rem 0 .2rem}input[type=password],input[type=text]{width:100%;padding:.55rem;border:1px solid #8886;border-radius:.4rem;box-sizing:border-box}
button{padding:.6rem 1.2rem;border-radius:.4rem;border:1px solid #8886;font-size:1rem;cursor:pointer}
button.go{background:#1565c0;color:#fff;border-color:#1565c0}ul{padding-left:1.2rem}li.sens{color:#c62828;font-weight:600}
"""


def e(value: object) -> str:
    return html.escape(str(value), quote=True)


def respond(title: str, body: str, status: int = 200, headers: dict[str, str] | None = None) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<meta name="robots" content="noindex"><title>{e(title)}</title><style nonce="{nonce}">{_CSS}</style></head><body>{body}</body></html>')
    h = {
        "Content-Security-Policy": f"default-src 'none'; style-src 'nonce-{nonce}'; frame-ancestors 'none'; base-uri 'none'",
        "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store", "Pragma": "no-cache",
    }
    h.update(headers or {})
    return HTMLResponse(doc, status_code=status, headers=h)


def message(title: str, text: str, status: int = 400, headers: dict[str, str] | None = None) -> HTMLResponse:
    return respond(title, f"<h1>{e(title)}</h1><p>{e(text)}</p>", status, headers)


def consent(*, req_id: str, nonce: str, client_name: str, client_id: str, verified: bool, redirect_uri: str,
            route: str, scopes: list[str], error: str | None = None, status: int = 200) -> HTMLResponse:
    res = RESOURCES[route]
    p = urlsplit(redirect_uri)
    dest = p.netloc or f"{p.scheme}:// (app)"
    items = "".join(f'<li class="{"sens" if s in res.sensitive else ""}">{e(res.scopes[s])}<br><span class="muted"><code>{e(s)}</code></span></li>' for s in scopes)
    sensitive = [s for s in scopes if s in res.sensitive]
    trust = ('<div class="card ok"><strong>Recognised application</strong><br>This redirect address is on your allow-list.</div>' if verified else
             '<div class="card warn"><strong>Unverified application.</strong> Its redirect address is <em>not</em> on your allow-list. '
             'Continue only if <em>you</em> just started this connection yourself.</div>')
    danger = ('<div class="card warn"><strong>High-impact access.</strong> This lets the application make changes for you, '
              'not just read. Approve only if you trust it completely.</div>') if sensitive else ""
    err = f'<div class="card warn" role="alert">{e(error)}</div>' if error else ""
    body = f"""
<h1>Authorize access</h1>
<p><strong>{e(client_name)}</strong> is asking to use <strong>{e(res.title)}</strong> on your MCP hub.</p>
{trust}
<div class="card"><div class="muted">After you decide, you will be sent to:</div><code>{e(dest)}</code>
<div class="muted">Client ID: <code>{e(client_id)}</code></div></div>
<div class="card"><strong>It will be able to:</strong><ul>{items}</ul></div>
{danger}{err}
<form method="post" action="/consent" autocomplete="off">
<input type="hidden" name="req" value="{e(req_id)}"><input type="hidden" name="nonce" value="{e(nonce)}">
<label for="pw">Owner password</label><input id="pw" type="password" name="password" autocomplete="current-password" required maxlength="1024">
<label for="totp">6-digit authenticator code</label><input id="totp" type="text" name="totp" inputmode="numeric" pattern="[0-9 ]{{6,7}}" autocomplete="one-time-code" required maxlength="7">
<p><button class="go" type="submit" name="action" value="approve">Approve</button> <button type="submit" name="action" value="deny" formnovalidate>Deny</button></p>
</form>
<p class="muted">Approving needs your password and a fresh authenticator code every time. You can revoke access later with <code>python -m hubauth revoke-client</code>.</p>"""
    return respond("Authorize access", body, status)
