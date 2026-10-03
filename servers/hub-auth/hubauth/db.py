"""SQLite storage. Secrets (tokens, codes) are stored only as SHA-256 hashes of 256-bit random values."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients(client_id TEXT PRIMARY KEY, info_json TEXT NOT NULL, created_at REAL NOT NULL, verified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pending(req_id TEXT PRIMARY KEY, nonce TEXT NOT NULL, client_id TEXT NOT NULL, params_json TEXT NOT NULL,
  resource TEXT NOT NULL, scopes_json TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS families(family_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, subject TEXT NOT NULL, resource TEXT NOT NULL,
  scopes_json TEXT NOT NULL, created_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, revoked_reason TEXT);
CREATE TABLE IF NOT EXISTS codes(hash TEXT PRIMARY KEY, family_id TEXT NOT NULL, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL,
  redirect_explicit INTEGER NOT NULL, challenge TEXT NOT NULL, scopes_json TEXT NOT NULL, resource TEXT NOT NULL, subject TEXT NOT NULL,
  expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS access_tokens(hash TEXT PRIMARY KEY, family_id TEXT NOT NULL, expires_at REAL NOT NULL, scopes_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS refresh_tokens(hash TEXT PRIMARY KEY, family_id TEXT NOT NULL, expires_at REAL NOT NULL, rotated INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_access_family ON access_tokens(family_id);
CREATE INDEX IF NOT EXISTS idx_refresh_family ON refresh_tokens(family_id);
"""


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_secret(prefix: str) -> str:
    """256 bits of entropy with a recognisable prefix (helps secret scanners)."""
    return prefix + secrets.token_urlsafe(32)


class Db:
    def __init__(self, path: str):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        # umask only protects files created from now on; an existing database (volume reuse) keeps its old mode.
        for suffix in ("", "-wal", "-shm"):
            try:
                os.chmod(path + suffix, 0o600)
            except FileNotFoundError:
                pass

    def q(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def x(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    def tx(self, fn):
        """Run fn(conn) atomically."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                out = fn(self._conn)
                self._conn.execute("COMMIT")
                return out
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    # ---- key/value (TOTP replay counter etc.) ----
    def kv_get(self, key: str) -> str | None:
        r = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return r["value"] if r else None

    def kv_set(self, key: str, value: str) -> None:
        self.x("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # ---- families / revocation ----
    def revoke_family(self, family_id: str, reason: str) -> None:
        self.x("UPDATE families SET revoked=1, revoked_reason=? WHERE family_id=? AND revoked=0", (reason, family_id))

    def revoke_client(self, client_id: str, reason: str) -> int:
        return self.x("UPDATE families SET revoked=1, revoked_reason=? WHERE client_id=? AND revoked=0", (reason, client_id))

    def revoke_all(self, reason: str) -> int:
        return self.x("UPDATE families SET revoked=1, revoked_reason=? WHERE revoked=0", (reason,))

    # ---- housekeeping ----
    def gc(self, client_gc_hours: int) -> None:
        now = time.time()
        self.x("DELETE FROM pending WHERE expires_at < ?", (now,))
        self.x("DELETE FROM codes WHERE expires_at < ?", (now - 3600,))  # keep a while to detect replays
        self.x("DELETE FROM access_tokens WHERE expires_at < ?", (now - 3600,))
        self.x("DELETE FROM refresh_tokens WHERE expires_at < ?", (now - 86400,))
        self.x("DELETE FROM clients WHERE created_at < ? AND client_id NOT IN (SELECT client_id FROM families)", (now - client_gc_hours * 3600,))
        self.x("DELETE FROM families WHERE revoked=1 AND created_at < ?", (now - 90 * 86400,))

    @staticmethod
    def dumps(obj) -> str:
        return json.dumps(obj, separators=(",", ":"))
