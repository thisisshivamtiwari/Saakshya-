"""
Publicly co-listed numbers (ARCHITECTURE section 5 / spec section 20).

An ``AssociatedNumber`` is emitted **only** for a ``FieldType.PHONE`` finding extracted from a
source that also literally displays the subject number.  Nothing here generates, guesses,
permutes or validates numbers by testing them - that would violate security invariant 5.
"""

from __future__ import annotations

from typing import Optional

from core.models import AssociatedNumber, Entity, FieldType, Finding, NormalizedPhone, Source, SourceQuality, mask_phone
from core.normalize import normalize_indian_number
from scoring.source_quality import QUALITY_RANK

from correlation._text import display_domain

CONFIDENCE_BY_QUALITY = {
    SourceQuality.A: 0.9, SourceQuality.B: 0.9, SourceQuality.C: 0.8, SourceQuality.D: 0.6, SourceQuality.E: 0.4,
}


def _canonical(value: str) -> str:
    """E.164 for a public display format; empty string when it is not a plausible number."""
    norm = normalize_indian_number(value)
    if norm.e164 and (norm.is_valid or norm.is_possible):
        return norm.e164
    v = value.strip().replace(" ", "").replace("-", "")
    return v if v.startswith("+") and v[1:].isdigit() and len(v) >= 11 else ""


def find_co_listed_numbers(
    phone: NormalizedPhone,
    findings: list[Finding],
    sources: list[Source],
    entities: Optional[list[Entity]] = None,
) -> list[AssociatedNumber]:
    """
    Return numbers publicly co-listed with the subject, one per distinct E.164, keeping the
    best-quality source and naming the other sources in ``reason``.  Deterministic order:
    confidence desc, then E.164.
    """
    src_by_id = {s.source_id: s for s in sources}
    displayed_sources = {f.source_id for f in findings if f.number_displayed}
    label_of = {e.entity_id: e.label for e in entities or []}
    owner_of: dict[str, str] = {}
    for e in entities or []:
        for fid in e.finding_ids:
            owner_of.setdefault(fid, e.entity_id)

    rows: dict[str, list[tuple[int, Finding, Source]]] = {}
    for f in sorted(findings, key=lambda x: (x.source_url, x.finding_id)):
        if f.field != FieldType.PHONE:
            continue
        src = src_by_id.get(f.source_id)
        if src is None:
            continue
        if f.source_id not in displayed_sources:
            continue  # subject number not on this page: not a co-listing
        e164 = _canonical(f.value)
        if not e164 or e164 == phone.e164:
            continue
        rows.setdefault(e164, []).append((QUALITY_RANK[src.quality], f, src))

    out: list[AssociatedNumber] = []
    for e164 in sorted(rows):
        ranked = sorted(rows[e164], key=lambda t: (-t[0], t[2].published_at or _MAX_DATE, t[1].finding_id))
        _, best_f, best_src = ranked[0]
        entity_id = best_f.entity_id or owner_of.get(best_f.finding_id)
        reason = (
            f"Publicly co-listed with the subject number on {display_domain(best_src.url)} "
            f"({best_src.source_type.value}, quality {best_src.quality.value})"
        )
        if entity_id and entity_id in label_of:
            reason += f" for '{label_of[entity_id]}'"
        others = sorted({display_domain(s.url) for _, _, s in ranked[1:]})
        if others:
            reason += "; also listed on " + ", ".join(others)
        out.append(
            AssociatedNumber(
                e164=e164,
                masked=mask_phone(e164),
                relation="publicly_co_listed",
                reason=reason,
                source_id=best_src.source_id,
                source_url=best_src.url,
                finding_id=best_f.finding_id,
                entity_id=entity_id,
                confidence=CONFIDENCE_BY_QUALITY[best_src.quality],
                published_at=best_f.published_at or best_src.published_at,
            )
        )
    out.sort(key=lambda a: (-a.confidence, a.e164))
    return out


from datetime import datetime, timezone  # noqa: E402  (kept at bottom: only used as a sort sentinel)

_MAX_DATE = datetime(9999, 1, 1, tzinfo=timezone.utc)

__all__ = ["find_co_listed_numbers", "CONFIDENCE_BY_QUALITY"]
