"""
SQLite response / query cache (spec section 25).

Keys are opaque strings built by callers (``provider:query`` or a URL).  Values
are JSON payloads plus metadata (timestamp, HTTP status, content hash).  The
cache is intentionally simple and synchronous: SQLite calls are fast and the
engine's concurrency is bounded.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def content_hash(text: str | bytes) -> str:
    data = text.encode("utf-8", "ignore") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def cache_key(namespace: str, *parts: str) -> str:
    raw = "\x1f".join(parts)
    return f"{namespace}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


@dataclass
class CacheEntry:
    key: str
    payload: Any
    created_at: float
    status: Optional[int]
    content_hash: str
    url: str = ""
    query: str = ""

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class ResponseCache:
    """Thread-safe SQLite cache with TTL."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS cache (
        key TEXT PRIMARY KEY,
        url TEXT,
        query TEXT,
        status INTEGER,
        content_hash TEXT,
        payload TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_cache_created ON cache(created_at);
    """

    def __init__(self, path: Path | str = ":memory:", ttl_seconds: int = 72 * 3600) -> None:
        self.path = str(path)
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(self._SCHEMA)
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------------ #
    def get(self, key: str, max_age: Optional[int] = None) -> Optional[CacheEntry]:
        ttl = self.ttl_seconds if max_age is None else max_age
        with self._lock:
            row = self._conn.execute(
                "SELECT key, url, query, status, content_hash, payload, created_at FROM cache WHERE key=?",
                (key,),
            ).fetchone()
        if not row:
            self.misses += 1
            return None
        created = float(row[6])
        if ttl >= 0 and time.time() - created > ttl:
            self.misses += 1
            return None
        self.hits += 1
        return CacheEntry(
            key=row[0], url=row[1] or "", query=row[2] or "", status=row[3],
            content_hash=row[4] or "", payload=json.loads(row[5]), created_at=created,
        )

    def set(self, key: str, payload: Any, *, url: str = "", query: str = "", status: Optional[int] = None) -> str:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        digest = content_hash(text)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache(key,url,query,status,content_hash,payload,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (key, url, query, status, digest, text, time.time()),
            )
            self._conn.commit()
        return digest

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM cache WHERE key=?", (key,))
            self._conn.commit()

    def purge_expired(self) -> int:
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            cur = self._conn.execute("DELETE FROM cache WHERE created_at < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM cache")
            self._conn.commit()

    def stats(self) -> dict[str, int]:
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        return {"entries": int(n), "hits": self.hits, "misses": self.misses}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
