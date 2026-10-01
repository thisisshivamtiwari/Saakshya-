"""SQLite evidence store: persists whole investigations plus queryable findings/sources/queries tables."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from core.models import Investigation, mask_phone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY, phone_e164 TEXT, phone_masked TEXT, depth TEXT, started_at TEXT,
    finished_at TEXT, engine_version TEXT, case_reference TEXT, summary_json TEXT, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS findings (
    finding_id TEXT PRIMARY KEY, investigation_id TEXT, field TEXT, value TEXT, source_url TEXT,
    source_quality TEXT, confidence REAL, association TEXT, number_displayed INTEGER, published_at TEXT,
    evidence_text TEXT);
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY, investigation_id TEXT, url TEXT, canonical_url TEXT, domain TEXT, title TEXT,
    source_type TEXT, quality TEXT, retrieved_at TEXT, published_at TEXT, content_hash TEXT, excerpt TEXT);
CREATE TABLE IF NOT EXISTS queries (
    query_id TEXT PRIMARY KEY, investigation_id TEXT, provider TEXT, query TEXT, stage TEXT, results_count INTEGER,
    new_results_count INTEGER, information_gain REAL, executed_at TEXT);
CREATE INDEX IF NOT EXISTS idx_inv_started ON investigations(started_at);
CREATE INDEX IF NOT EXISTS idx_findings_inv ON findings(investigation_id);
CREATE INDEX IF NOT EXISTS idx_sources_inv ON sources(investigation_id);
"""


class EvidenceStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def save(self, inv: Investigation, *, store_provider_snippets: bool = False) -> str:
        persisted = inv.model_copy(deep=True)
        if not store_provider_snippets:
            for s in persisted.sources:
                if not s.fetched:
                    s.excerpt = ""  # provider snippets are transient (search-API terms); keep our own excerpts
        m = persisted.investigation
        with self._lock:
            c = self._conn
            c.execute("DELETE FROM findings WHERE investigation_id=?", (m.investigation_id,))
            c.execute("DELETE FROM sources WHERE investigation_id=?", (m.investigation_id,))
            c.execute("DELETE FROM queries WHERE investigation_id=?", (m.investigation_id,))
            c.execute(
                "INSERT OR REPLACE INTO investigations VALUES(?,?,?,?,?,?,?,?,?,?)",
                (m.investigation_id, persisted.phone.e164, mask_phone(persisted.phone.e164), m.depth.value,
                 m.started_at.isoformat(), m.finished_at.isoformat() if m.finished_at else None, m.engine_version,
                 m.case_reference, persisted.summary.model_dump_json(), persisted.model_dump_json()),
            )
            c.executemany(
                "INSERT OR REPLACE INTO findings VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(f.finding_id, m.investigation_id, f.field.value, f.value, f.source_url, f.source_quality.value,
                  f.confidence, f.association.value, int(f.number_displayed),
                  f.published_at.isoformat() if f.published_at else None, f.evidence_text) for f in persisted.findings],
            )
            c.executemany(
                "INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                [(s.source_id, m.investigation_id, s.url, s.canonical_url, s.domain, s.title, s.source_type.value,
                  s.quality.value, s.retrieved_at.isoformat(), s.published_at.isoformat() if s.published_at else None,
                  s.content_hash, s.excerpt) for s in persisted.sources],
            )
            c.executemany(
                "INSERT OR REPLACE INTO queries VALUES(?,?,?,?,?,?,?,?,?)",
                [(q.query_id, m.investigation_id, q.provider, q.query, q.stage.value, q.results_count,
                  q.new_results_count, q.information_gain, q.executed_at.isoformat()) for q in persisted.queries],
            )
            c.commit()
        return m.investigation_id

    def load(self, investigation_id: str) -> Optional[Investigation]:
        with self._lock:
            row = self._conn.execute("SELECT payload_json FROM investigations WHERE investigation_id=?",
                                     (investigation_id,)).fetchone()
        return Investigation.model_validate_json(row[0]) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT investigation_id, phone_masked, depth, started_at, finished_at, summary_json FROM investigations "
                "ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            summary = json.loads(r[5]) if r[5] else {}
            out.append({"investigation_id": r[0], "phone_masked": r[1], "depth": r[2], "started_at": r[3],
                        "finished_at": r[4], "top_candidate": summary.get("candidate_identity"),
                        "top_percent": summary.get("confidence_percent")})
        return out

    def delete(self, investigation_id: str) -> None:
        with self._lock:
            for table in ("findings", "sources", "queries", "investigations"):
                self._conn.execute(f"DELETE FROM {table} WHERE investigation_id=?", (investigation_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
