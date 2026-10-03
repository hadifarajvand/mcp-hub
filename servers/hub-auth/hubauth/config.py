"""Settings from the environment. Anything missing or weak is fatal: this service must fail closed."""

from __future__ import annotations

import base64
import os
import re
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit


def fatal(msg: str) -> "None":
    print(f"FATAL: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _decode_hash(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("b64:"):  # base64 avoids '$' interpolation problems in .env / Dokploy
        try:
            raw = base64.b64decode(raw[4:], validate=True).decode()
        except Exception:  # noqa: BLE001
            fatal("HUB_OWNER_PASSWORD_HASH has an invalid b64: value")
    return raw


@dataclass(frozen=True)
class Settings:
    base_url: str
    db_path: str
    owner_hash: str
    owner_totp_secret: str
    access_ttl: int = 900
    access_ttl_sensitive: int = 300
    refresh_ttl: int = 30 * 86400
    code_ttl: int = 60
    pending_ttl: int = 600
    max_pending_clients: int = 100
    client_gc_hours: int = 24
    redirect_allowlist: tuple[str, ...] = ()
    custom_schemes: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        parts = urlsplit(base)
        if not base or parts.scheme not in ("https", "http") or not parts.hostname or parts.path or parts.query or parts.fragment:
            fatal("PUBLIC_BASE_URL must be an origin like https://mcp.example.com (no path, query or fragment)")
        if parts.scheme != "https" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            fatal("PUBLIC_BASE_URL must be https (plain http is only allowed for localhost)")

        owner_hash = _decode_hash(os.getenv("HUB_OWNER_PASSWORD_HASH", ""))
        m = re.match(r"^\$argon2id\$v=\d+\$m=(\d+),t=(\d+),p=(\d+)\$", owner_hash)
        if not m:
            fatal("HUB_OWNER_PASSWORD_HASH must be an argon2id hash (generate with: python -m hubauth gen-owner)")
        if int(m.group(1)) < 19456 or int(m.group(2)) < 2:
            fatal("HUB_OWNER_PASSWORD_HASH uses weak argon2id parameters (need m>=19456 KiB, t>=2)")

        secret = os.getenv("HUB_OWNER_TOTP_SECRET", "").replace(" ", "").upper()
        if not re.fullmatch(r"[A-Z2-7]{26,}", secret):
            fatal("HUB_OWNER_TOTP_SECRET must be a base32 secret of at least 26 characters (generate with: python -m hubauth gen-owner)")

        default_redirects = ("https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback",
                             "https://chatgpt.com/connector/oauth/*", "https://chatgpt.com/connector_platform_oauth_redirect")
        allow = tuple(x.strip() for x in os.getenv("OAUTH_REDIRECT_ALLOWLIST", ",".join(default_redirects)).split(",") if x.strip())
        schemes = tuple(x.strip().lower() for x in os.getenv("OAUTH_CUSTOM_SCHEMES", "cursor,vscode,vscode-insiders").split(",") if x.strip())
        return cls(
            base_url=base, db_path=os.getenv("HUBAUTH_DB", "/data/hubauth.db"), owner_hash=owner_hash, owner_totp_secret=secret,
            access_ttl=int(os.getenv("OAUTH_ACCESS_TTL", "900")), access_ttl_sensitive=int(os.getenv("OAUTH_ACCESS_TTL_SENSITIVE", "300")),
            refresh_ttl=int(os.getenv("OAUTH_REFRESH_TTL_DAYS", "30")) * 86400,
            redirect_allowlist=allow, custom_schemes=schemes,
        )
