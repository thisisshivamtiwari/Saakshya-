"""
Timeline construction (ARCHITECTURE section 5).

One event per source (dated sources first, in chronological order, undated last) plus a
"first seen" marker per candidate entity.  Dates come from the source's ``published_at``
or, failing that, the earliest dated finding on that source; precision is propagated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.models import DatePrecision, Entity, FieldType, Finding, Source, TimelineEvent

from correlation._text import display_domain, join_human
from correlation.entity_resolver import UNRESOLVED_LABEL

_FIELD_WORD = {
    FieldType.NAME: "name", FieldType.BUSINESS: "business", FieldType.ORGANIZATION: "organisation",
    FieldType.EMAIL: "e-mail", FieldType.USERNAME: "username", FieldType.LOCATION: "location",
    FieldType.ADDRESS: "address", FieldType.WEBSITE: "website", FieldType.JOB_TITLE: "job title",
    FieldType.PHONE: "co-listed number", FieldType.SOCIAL_PROFILE: "profile",
}


def _source_date(src: Source, findings: list[Finding]) -> tuple[Optional[datetime], DatePrecision]:
    if src.published_at is not None:
        return src.published_at, src.date_precision
    dated = [(f.published_at, f.date_precision) for f in findings if f.published_at is not None]
    if dated:
        return min(dated, key=lambda t: t[0])  # type: ignore[arg-type]
    return None, DatePrecision.UNKNOWN


def _field_summary(findings: list[Finding]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for f in findings:
        word = _FIELD_WORD.get(f.field)
        if not word:
            continue
        item = f"{word} '{f.value}'"
        if item not in seen:
            seen.add(item)
            parts.append(item)
    return join_human(parts, 3) if parts else "no extractable entity"


def build_timeline(findings: list[Finding], sources: list[Source], entities: list[Entity]) -> list[TimelineEvent]:
    """Build the chronological public-mention timeline.  Deterministic; unknown dates sort last."""
    by_source: dict[str, list[Finding]] = {}
    for f in findings:
        by_source.setdefault(f.source_id, []).append(f)
    label_of: dict[str, str] = {e.entity_id: e.label for e in entities}

    events: list[TimelineEvent] = []
    for src in sources:
        fs = by_source.get(src.source_id, [])
        date, precision = _source_date(src, fs)
        displayed = any(f.number_displayed for f in fs)
        labels = sorted({label_of[f.entity_id] for f in fs if f.entity_id in label_of and label_of[f.entity_id] != UNRESOLVED_LABEL})
        with_what = join_human(labels, 3) if labels else _field_summary(fs)
        verb = "Number displayed on" if displayed else "Number referenced via"
        entity_id = next((f.entity_id for f in fs if f.entity_id in label_of), None)
        events.append(
            TimelineEvent(
                date=date,
                precision=precision,
                description=f"{verb} {display_domain(src.url)} ({src.source_type.value}) with {with_what}",
                finding_id=fs[0].finding_id if fs else "",
                source_id=src.source_id,
                source_url=src.url,
                entity_id=entity_id,
                kind="public_mention",
            )
        )

    for e in entities:
        if e.first_seen is None or e.label == UNRESOLVED_LABEL:
            continue
        first = next((f for f in findings if f.entity_id == e.entity_id and f.published_at == e.first_seen), None)
        events.append(
            TimelineEvent(
                date=e.first_seen,
                precision=first.date_precision if first else DatePrecision.UNKNOWN,
                description=f"Earliest dated public association with '{e.label}' ({e.kind.value})",
                finding_id=first.finding_id if first else "",
                source_id=first.source_id if first else "",
                source_url=first.source_url if first else "",
                entity_id=e.entity_id,
                kind="entity_first_seen",
            )
        )

    def key(ev: TimelineEvent) -> tuple[int, float, str]:
        return (0 if ev.date else 1, ev.date.timestamp() if ev.date else 0.0, ev.description)

    events.sort(key=key)
    return events


__all__ = ["build_timeline"]
