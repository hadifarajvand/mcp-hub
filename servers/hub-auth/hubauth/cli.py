"""Operator CLI:  python -m hubauth <command>"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import sys
import time

import pyotp

from .db import Db
from .security import hash_password


def gen_owner(args) -> int:
    pw = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Choose an owner password (min 14 chars): ")
    if not args.password_stdin and getpass.getpass("Repeat: ") != pw:
        print("Passwords differ.", file=sys.stderr)
        return 1
    if len(pw) < 14:
        print("Password must be at least 14 characters.", file=sys.stderr)
        return 1
    secret = pyotp.random_base32(length=32)
    phc = hash_password(pw)
    uri = pyotp.TOTP(secret).provisioning_uri(name="owner", issuer_name="MCP Hub")
    print("\nAdd these to your environment (Dokploy -> Environment). The hash is base64 so '$' survives .env/compose:\n")
    print(f"HUB_OWNER_PASSWORD_HASH=b64:{base64.b64encode(phc.encode()).decode()}")
    print(f"HUB_OWNER_TOTP_SECRET={secret}")
    print("\nAdd the TOTP secret to your authenticator app (enter the key manually, or use this URI):")
    print(uri)
    return 0


def _db() -> Db:
    return Db(os.getenv("HUBAUTH_DB", "/data/hubauth.db"))


def list_grants(_) -> int:
    for r in _db().q("SELECT f.family_id, f.client_id, f.resource, f.scopes_json, f.created_at, f.revoked, f.revoked_reason, c.info_json FROM families f LEFT JOIN clients c USING(client_id) ORDER BY f.created_at DESC"):
        import json
        name = (json.loads(r["info_json"]).get("client_name") if r["info_json"] else None) or "?"
        state = f"REVOKED({r['revoked_reason']})" if r["revoked"] else "active"
        print(f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(r['created_at']))}  {state:28} {r['resource']:18} {r['scopes_json']:30} client={r['client_id']} ({name})")
    return 0


def revoke_client(args) -> int:
    n = _db().revoke_client(args.client_id, "revoked_by_operator")
    print(f"revoked {n} grant(s)")
    return 0


def revoke_all(_) -> int:
    n = _db().revoke_all("revoked_by_operator")
    print(f"revoked {n} grant(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="hubauth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen-owner", help="generate the owner password hash and TOTP secret")
    g.add_argument("--password-stdin", action="store_true")
    g.set_defaults(fn=gen_owner)
    sub.add_parser("list-grants", help="list authorizations").set_defaults(fn=list_grants)
    r = sub.add_parser("revoke-client", help="revoke every grant of one client")
    r.add_argument("client_id")
    r.set_defaults(fn=revoke_client)
    sub.add_parser("revoke-all", help="revoke every grant (emergency)").set_defaults(fn=revoke_all)
    args = ap.parse_args()
    return args.fn(args)
