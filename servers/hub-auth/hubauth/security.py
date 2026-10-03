"""Password + TOTP verification, rate limiting, and the audit log."""

from __future__ import annotations

import hmac
import json
import re
import sys
import threading
import time
from collections import defaultdict, deque

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .db import Db

_hasher = PasswordHasher()
_hash_lock = threading.Lock()  # argon2 uses ~64 MiB per call: never run them in parallel


def audit(event: str, **fields) -> None:
    """One JSON line per security event. Never pass token or password values here."""
    print(json.dumps({"ts": round(time.time(), 3), "event": event, **fields}, default=str), file=sys.stdout, flush=True)


def verify_password(stored_hash: str, password: str) -> bool:
    if not password or len(password) > 1024:
        return False
    with _hash_lock:
        try:
            return _hasher.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


def hash_password(password: str) -> str:
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4).hash(password)


def verify_totp(db: Db, secret: str, code: str, consume: bool = True) -> bool:
    """Accept a 6-digit code for the previous/current/next 30 s step, once only (replay-proof).
    consume=False checks without burning the step (used when the password was already wrong)."""
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return False
    totp = pyotp.TOTP(secret)
    now_step = int(time.time()) // 30
    matched = None
    for step in (now_step - 1, now_step, now_step + 1):  # evaluate all three: no early exit on a match
        if hmac.compare_digest(totp.generate_otp(step), code):
            matched = step

    def cas(conn):
        row = conn.execute("SELECT value FROM kv WHERE key='totp_last'").fetchone()
        last = int(row[0]) if row else 0
        if matched is None or matched <= last:
            return False
        if not consume:
            return True
        conn.execute("INSERT INTO kv(key,value) VALUES('totp_last',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(matched),))
        return True

    return bool(db.tx(cas))


class RateLimiter:
    """In-memory sliding windows (reset on restart; fine for a single-owner service)."""

    def __init__(self):
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        dq = self._events[key]
        while dq and now - dq[0] > window:
            dq.popleft()
        return dq

    def count(self, key: str, window: float) -> int:
        with self._lock:
            return len(self._prune(key, window, time.monotonic()))

    def add(self, key: str, window: float = 3600) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, window, now).append(now)

    def allow(self, key: str, limit: int, window: float) -> bool:
        """Record an event and report whether it is within `limit` per `window` seconds."""
        with self._lock:
            now = time.monotonic()
            dq = self._prune(key, window, now)
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True

    def retry_after(self, key: str, window: float) -> int:
        with self._lock:
            now = time.monotonic()
            dq = self._prune(key, window, now)
            return int(window - (now - dq[0])) + 1 if dq else 0


LOGIN_FAILS_PER_IP = 5
LOGIN_FAILS_GLOBAL = 20
LOGIN_WINDOW = 900.0
