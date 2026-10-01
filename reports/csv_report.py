"""
CSV exports: flat, spreadsheet-friendly tables (one file per collection).

List-valued fields are joined with ``"; "``; datetimes are ISO-8601; enums
are their string values.  Every row carries the investigation id so several
exports can be concatenated safely.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from core.models import Investigation
from reports.markdown_report import entity_label, finding_label

JOIN = "; "

FINDINGS_COLUMNS = [
    "investigation_id", "finding_id", "label", "entity_id", "field", "value", "normalized_value", "association",
    "number_displayed", "confidence", "source_id", "source_url", "source_type", "source_quality", "published_at",
    "date_precision", "discovered_at", "provider", "query_id", "extractor", "evidence_text",
]
SOURCES_COLUMNS = [
    "investigation_id", "source_id", "url", "canonical_url", "domain", "title", "source_type", "quality", "provider",
    "retrieved_at", "published_at", "date_precision", "http_status", "fetched", "robots_allowed", "content_hash",
    "referenced_by_count", "referenced_by", "excerpt",
]
ENTITIES_COLUMNS = [
    "investigation_id", "entity_id", "label", "kind", "claim_label", "confidence_label", "percent", "total_points",
    "association", "independent_source_count", "names", "emails", "usernames", "businesses", "websites",
    "job_titles", "locations", "addresses", "associated_numbers", "first_seen", "last_seen", "why_linked",
    "score_components", "contradiction_ids", "source_ids", "finding_count",
]
QUERIES_COLUMNS = [
    "investigation_id", "query_id", "provider", "query", "stage", "purpose", "lead_id", "executed_at",
    "results_count", "new_results_count", "information_gain", "cached", "error",
]
TIMELINE_COLUMNS = [
    "investigation_id", "date", "precision", "description", "kind", "entity_id", "finding_id", "source_id",
    "source_url",
]
ASSOCIATED_NUMBERS_COLUMNS = [
    "investigation_id", "e164", "masked", "relation", "reason", "entity_id", "confidence", "source_id",
    "source_url", "finding_id", "discovered_at", "published_at",
]
CONTRADICTIONS_COLUMNS = [
    "investigation_id", "contradiction_id", "kind", "severity", "description", "entity_ids", "finding_ids",
    "resolution_hint",
]


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat(timespec="seconds") if value else ""


def _join(values: Iterable[Any]) -> str:
    return JOIN.join(str(v) for v in values)


def _write(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def findings_rows(inv: Investigation) -> list[dict[str, Any]]:
    iid = inv.investigation.investigation_id
    return [
        {
            "investigation_id": iid, "finding_id": f.finding_id, "label": finding_label(f), "entity_id": f.entity_id or "",
            "field": f.field.value, "value": f.value, "normalized_value": f.normalized_value,
            "association": f.association.value, "number_displayed": f.number_displayed, "confidence": f.confidence,
            "source_id": f.source_id, "source_url": f.source_url, "source_type": f.source_type.value,
            "source_quality": f.source_quality.value, "published_at": _iso(f.published_at),
            "date_precision": f.date_precision.value, "discovered_at": _iso(f.discovered_at), "provider": f.provider,
            "query_id": f.query_id or "", "extractor": f.extractor, "evidence_text": f.evidence_text,
        }
        for f in inv.findings
    ]


def sources_rows(inv: Investigation) -> list[dict[str, Any]]:
    iid = inv.investigation.investigation_id
    return [
        {
            "investigation_id": iid, "source_id": s.source_id, "url": s.url, "canonical_url": s.canonical_url,
            "domain": s.domain, "title": s.title, "source_type": s.source_type.value, "quality": s.quality.value,
            "provider": s.provider, "retrieved_at": _iso(s.retrieved_at), "published_at": _iso(s.published_at),
            "date_precision": s.date_precision.value, "http_status": s.http_status if s.http_status is not None else "",
            "fetched": s.fetched, "robots_allowed": "" if s.robots_allowed is None else s.robots_allowed,
            "content_hash": s.content_hash, "referenced_by_count": len(s.referenced_by),
            "referenced_by": _join(s.referenced_by), "excerpt": s.excerpt,
        }
        for s in inv.sources
    ]


def entities_rows(inv: Investigation) -> list[dict[str, Any]]:
    iid = inv.investigation.investigation_id
    return [
        {
            "investigation_id": iid, "entity_id": e.entity_id, "label": e.label, "kind": e.kind.value,
            "claim_label": entity_label(e), "confidence_label": e.score.label.value, "percent": e.score.percent,
            "total_points": e.score.total_points, "association": e.association.value,
            "independent_source_count": e.independent_source_count, "names": _join(e.names),
            "emails": _join(e.emails), "usernames": _join(e.usernames), "businesses": _join(e.businesses),
            "websites": _join(e.websites), "job_titles": _join(e.job_titles), "locations": _join(e.locations),
            "addresses": _join(e.addresses), "associated_numbers": _join(e.associated_numbers),
            "first_seen": _iso(e.first_seen), "last_seen": _iso(e.last_seen), "why_linked": _join(e.why_linked),
            "score_components": _join(f"{c.rule}={c.points:+d}" for c in e.score.components),
            "contradiction_ids": _join(e.contradiction_ids), "source_ids": _join(e.source_ids),
            "finding_count": len(e.finding_ids),
        }
        for e in inv.entities
    ]


def queries_rows(inv: Investigation) -> list[dict[str, Any]]:
    iid = inv.investigation.investigation_id
    return [
        {
            "investigation_id": iid, "query_id": q.query_id, "provider": q.provider, "query": q.query,
            "stage": q.stage.value, "purpose": q.purpose, "lead_id": q.lead_id or "", "executed_at": _iso(q.executed_at),
            "results_count": q.results_count, "new_results_count": q.new_results_count,
            "information_gain": f"{q.information_gain:.3f}", "cached": q.cached, "error": q.error or "",
        }
        for q in inv.queries
    ]


def timeline_rows(inv: Investigation) -> list[dict[str, Any]]:
    iid = inv.investigation.investigation_id
    return [
        {
            "investigation_id": iid, "date": _iso(t.date), "precision": t.precision.value,
            "description": t.description, "kind": t.kind, "entity_id": t.entity_id or "", "finding_id": t.finding_id,
            "source_id": t.source_id, "source_url": t.source_url,
        }
        for t in inv.timeline
    ]


def associated_numbers_rows(inv: Investigation) -> list[dict[str, Any]]:
    iid = inv.investigation.investigation_id
    return [
        {
            "investigation_id": iid, "e164": n.e164, "masked": n.masked, "relation": n.relation, "reason": n.reason,
            "entity_id": n.entity_id or "", "confidence": n.confidence, "source_id": n.source_id,
            "source_url": n.source_url, "finding_id": n.finding_id, "discovered_at": _iso(n.discovered_at),
            "published_at": _iso(n.published_at),
        }
        for n in inv.associated_numbers
    ]


def contradictions_rows(inv: Investigation) -> list[dict[str, Any]]:
    iid = inv.investigation.investigation_id
    return [
        {
            "investigation_id": iid, "contradiction_id": c.contradiction_id, "kind": c.kind.value,
            "severity": c.severity, "description": c.description, "entity_ids": _join(c.entity_ids),
            "finding_ids": _join(c.finding_ids), "resolution_hint": c.resolution_hint,
        }
        for c in inv.contradictions
    ]


CSV_FILES: dict[str, tuple[list[str], Any]] = {
    "findings.csv": (FINDINGS_COLUMNS, findings_rows),
    "sources.csv": (SOURCES_COLUMNS, sources_rows),
    "entities.csv": (ENTITIES_COLUMNS, entities_rows),
    "queries.csv": (QUERIES_COLUMNS, queries_rows),
    "timeline.csv": (TIMELINE_COLUMNS, timeline_rows),
    "associated_numbers.csv": (ASSOCIATED_NUMBERS_COLUMNS, associated_numbers_rows),
    "contradictions.csv": (CONTRADICTIONS_COLUMNS, contradictions_rows),
}


def write_csv(inv: Investigation, directory: Path | str) -> dict[str, Path]:
    """Write every CSV export into ``directory`` and return ``{file name: path}``."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, (columns, builder) in CSV_FILES.items():
        written[name] = _write(out_dir / name, columns, builder(inv))
    return written


__all__ = ["write_csv", "CSV_FILES", "JOIN"]
