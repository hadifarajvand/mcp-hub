#!/usr/bin/env python3
"""Test helper: obtain hub OAuth tokens through the REAL flow (DCR + PKCE + owner login + token endpoint).

Needs in the environment (dev .env):  HUBTEST_PASSWORD, HUB_OWNER_TOTP_SECRET
Caches refresh tokens (rotating) in $HUBTEST_CACHE so repeated runs need no new login. TOTP codes are single-use
per 30 s step on the server, so logins are spaced across steps automatically.

  python tests/hubclient.py token <route> [scope ...]     print a fresh access token
"""
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pyotp

BASE = os.getenv("HUB_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
CACHE = os.getenv("HUBTEST_CACHE", "/tmp/mcp-hub-test-tokens.json")
REDIRECT = "http://127.0.0.1:53682/callback"


def _load():
    try:
        return json.load(open(CACHE))
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = CACHE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CACHE)


def next_totp(state):
    """A code for a step strictly newer than the last one used (the server rejects replays)."""
    secret = os.environ["HUB_OWNER_TOTP_SECRET"]
    totp = pyotp.TOTP(secret)
    while True:
        now = int(time.time()) // 30
        last = state.get("_last_step", 0)
        for step in (now - 1, now, now + 1):
            if step > last:
                state["_last_step"] = step
                _save(state)
                return totp.at(step * 30)
        time.sleep(1)


def pkce():
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")


def login(route, scopes=None, name=None, cache=True):
    """Full interactive-equivalent login for one route. Returns the entry; cache=False for throwaway grants."""
    state = _load()
    h = httpx.Client(base_url=BASE, follow_redirects=False, timeout=30)
    cid = h.post("/register", json={"redirect_uris": [REDIRECT], "client_name": name or f"hub-test-{route}", "token_endpoint_auth_method": "none",
                                    "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}).json()["client_id"]
    verifier, challenge = pkce()
    params = {"response_type": "code", "client_id": cid, "redirect_uri": REDIRECT, "state": secrets.token_urlsafe(8), "code_challenge": challenge,
              "code_challenge_method": "S256", "resource": f"{BASE}/{route}/mcp"}
    if scopes:
        params["scope"] = " ".join(scopes)
    r = h.get("/authorize", params=params)
    assert r.status_code == 302, (r.status_code, r.text[:200])
    page = h.get(r.headers["location"].replace(BASE, ""))
    req = re.search(r'name="req" value="([^"]+)"', page.text).group(1)
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text).group(1)
    d = None
    for attempt in range(3):  # a rejected code usually means that step was already consumed (replay protection): wait for a fresh one
        d = h.post("/consent", data={"req": req, "nonce": nonce, "password": os.environ["HUBTEST_PASSWORD"], "totp": next_totp(state), "action": "approve"})
        if d.status_code == 303:
            break
        if d.status_code != 401 or attempt == 2:  # never retry into the lockout (5 failures / 15 min)
            break
        time.sleep(31)
    assert d.status_code == 303, d.text[:300]
    code = parse_qs(urlsplit(d.headers["location"]).query)["code"][0]
    t = h.post("/token", data={"grant_type": "authorization_code", "client_id": cid, "code": code, "code_verifier": verifier, "redirect_uri": REDIRECT}).json()
    entry = {"client_id": cid, "refresh_token": t["refresh_token"], "access_token": t["access_token"],
             "expires_at": time.time() + t["expires_in"], "scope": t["scope"]}
    if cache:
        state = _load()
        state[_key(route, scopes)] = entry
        _save(state)
    return entry


def _key(route, scopes):
    return route + "|" + " ".join(sorted(scopes or []))


def token_entry(route, scopes=None, min_ttl=60):
    state = _load()
    entry = state.get(_key(route, scopes))
    if entry and entry["expires_at"] - time.time() > min_ttl:
        return entry
    if entry:  # renew with the rotating refresh token: no login needed
        r = httpx.post(BASE + "/token", data={"grant_type": "refresh_token", "client_id": entry["client_id"], "refresh_token": entry["refresh_token"]}, timeout=30)
        if r.status_code == 200:
            t = r.json()
            entry.update(refresh_token=t["refresh_token"], access_token=t["access_token"], expires_at=time.time() + t["expires_in"])
            state = _load()
            state[_key(route, scopes)] = entry
            _save(state)
            return entry
    return login(route, scopes)


def token_for(route, scopes=None):
    return token_entry(route, scopes)["access_token"]


class HubAuth(httpx.Auth):
    """httpx auth that always sends a currently valid bearer for one route (renews before expiry)."""

    def __init__(self, route, scopes=None):
        self.route, self.scopes = route, scopes

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {token_for(self.route, self.scopes)}"
        yield request


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "token":
        print(token_for(sys.argv[2], sys.argv[3:] or None))
    else:
        print(__doc__)
