"""
Contradiction detection (ARCHITECTURE section 5).

Contradictions are *described*, never resolved: the engine does not decide which
of two conflicting public claims is right.  Every contradiction carries the entity
and finding ids involved, a severity and a ``resolution_hint`` telling the analyst
what to check.  Contradiction ids are attached to the affected entities so scoring
can apply the transparent negative rules.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import combinations
from typing import Optional

from core.models import (
    Association,
    Contradiction,
    ContradictionKind,
    Entity,
    EntityKind,
    FieldType,
    Finding,
    NormalizedPhone,
    Source,
    SourceQuality,
    stable_id,
)

from correlation._text import display_domain, names_fuzzy_equal, normalise_business, normalise_city
from correlation.entity_resolver import UNRESOLVED_LABEL

OWNERSHIP_PHRASES: tuple[str, ...] = (
    "not my number", "wrong number", "previous owner", "old number", "no longer", "used to belong",
    "new owner", "number changed", "recycled",
)

_TEMPORAL_GAP = timedelta(days=365)


def _direct_displayed(findings: list[Finding], sources: dict[str, Source], min_quality_rank: int = 2) -> list[Finding]:
    """DIRECT findings where the number is literally displayed on an A-D quality source."""
    from scoring.source_quality import QUALITY_RANK

    out: list[Finding] = []
    for f in findings:
        if not (f.number_displayed and f.association == Association.DIRECT):
            continue
        src = sources.get(f.source_id)
        quality = src.quality if src else f.source_quality
        if QUALITY_RANK[quality] >= min_quality_rank:
            out.append(f)
    return out


def _year(f: Finding, sources: dict[str, Source]) -> Optional[int]:
    d = f.published_at or (sources[f.source_id].published_at if f.source_id in sources else None)
    return d.year if d else None


def _dated(findings: list[Finding], sources: dict[str, Source]):  # type: ignore[no-untyped-def]
    for f in findings:
        d = f.published_at or (sources[f.source_id].published_at if f.source_id in sources else None)
        if d is not None:
            yield d, f


def detect_contradictions(
    phone: NormalizedPhone, entities: list[Entity], findings: list[Finding], sources: list[Source]
) -> list[Contradiction]:
    """
    Detect NAME / LOCATION / ENTITY_KIND / TEMPORAL / OWNERSHIP contradictions between and
    within entities.  Mutates ``Entity.contradiction_ids`` (sorted, unique).  Deterministic.
    """
    src_by_id = {s.source_id: s for s in sources}
    fnd_by_id = {f.finding_id: f for f in findings}
    ent_findings: dict[str, list[Finding]] = {
        e.entity_id: [fnd_by_id[i] for i in e.finding_ids if i in fnd_by_id] for e in entities
    }
    candidates = [e for e in entities if e.label != UNRESOLVED_LABEL]
    out: list[Contradiction] = []

    def emit(kind: ContradictionKind, description: str, entity_ids: list[str], finding_ids: list[str],
             severity: str, hint: str) -> None:
        out.append(
            Contradiction(
                contradiction_id=stable_id("ctr", kind.value, *entity_ids, *finding_ids),
                kind=kind,
                description=description,
                entity_ids=entity_ids,
                finding_ids=finding_ids,
                severity=severity,
                resolution_hint=hint,
            )
        )

    # NAME_CONFLICT: >=2 PERSON entities each with a DIRECT, number-displayed finding on an A-D source
    persons = [
        e for e in candidates
        if e.kind == EntityKind.PERSON and _direct_displayed(ent_findings[e.entity_id], src_by_id)
    ]
    for a, b in combinations(persons, 2):
        if names_fuzzy_equal(a.label, b.label):
            continue
        fa = _direct_displayed(ent_findings[a.entity_id], src_by_id)
        fb = _direct_displayed(ent_findings[b.entity_id], src_by_id)
        severity = "high" if a.independent_source_count >= 2 and b.independent_source_count >= 2 else "medium"
        emit(
            ContradictionKind.NAME_CONFLICT,
            f"The number is publicly displayed with two different person names: '{a.label}' "
            f"({a.independent_source_count} independent source(s)) and '{b.label}' "
            f"({b.independent_source_count} independent source(s)).",
            [a.entity_id, b.entity_id],
            [f.finding_id for f in fa + fb],
            severity,
            "Compare publication dates: the number may have been reassigned or shared (family/business "
            "line). Do not merge the two identities; verify through lawful, authorised channels.",
        )

    # LOCATION_CONFLICT: one entity, >=2 different cities from DIRECT findings
    for e in candidates:
        cities: dict[str, list[Finding]] = {}
        for f in ent_findings[e.entity_id]:
            if f.field == FieldType.LOCATION and f.association == Association.DIRECT:
                city = normalise_city(str((f.metadata or {}).get("city") or f.normalized_value or f.value))
                if city:
                    cities.setdefault(city, []).append(f)
        # Localities of one metro (Gomti Nagar / Lucknow) are not a conflict: compare states when known.
        states: dict[str, str] = {}
        for city, fs in cities.items():
            st = str((fs[0].metadata or {}).get("state") or "").strip().lower()
            states[city] = st
        known_states = {s for s in states.values() if s}
        distinct = len(known_states) if known_states else len(cities)
        if len(known_states) == 1 and any(not s for s in states.values()):
            distinct = 2  # one known state plus unknown cities -> still ambiguous
        if len(cities) >= 2 and distinct >= 2:
            names = sorted(cities)
            emit(
                ContradictionKind.LOCATION_CONFLICT,
                f"'{e.label}' is directly associated with {len(names)} different cities: "
                + ", ".join(n.title() for n in names) + ".",
                [e.entity_id],
                [f.finding_id for c in names for f in cities[c]],
                "medium",
                "The entity may have relocated or operate branches; check which city each dated source refers to.",
            )

    # ENTITY_KIND_CONFLICT: number displayed for a person and an unrelated business
    businesses = [
        e for e in candidates
        if e.kind in (EntityKind.BUSINESS, EntityKind.ORGANIZATION) and _direct_displayed(ent_findings[e.entity_id], src_by_id)
    ]
    for p in persons:
        related = {normalise_business(b) for b in p.businesses}
        for b in businesses:
            key = normalise_business(b.label)
            if key in related or any(names_fuzzy_equal(key, r) for r in related):
                continue
            emit(
                ContradictionKind.ENTITY_KIND_CONFLICT,
                f"The number is displayed both for person '{p.label}' and for business '{b.label}', "
                "and no public source links the two.",
                [p.entity_id, b.entity_id],
                [f.finding_id for f in _direct_displayed(ent_findings[p.entity_id], src_by_id)
                 + _direct_displayed(ent_findings[b.entity_id], src_by_id)],
                "medium",
                "Check whether the person is publicly named as owner/employee of the business; otherwise treat as separate candidates.",
            )

    # TEMPORAL_CHANGE: DIRECT findings for different entities dated >= 1 year apart
    for a, b in combinations(candidates, 2):
        da = list(_dated(_direct_displayed(ent_findings[a.entity_id], src_by_id, 1), src_by_id))
        db = list(_dated(_direct_displayed(ent_findings[b.entity_id], src_by_id, 1), src_by_id))
        if not da or not db:
            continue
        latest_a, fa = max(da, key=lambda t: t[0])
        latest_b, fb = max(db, key=lambda t: t[0])
        if abs(latest_a - latest_b) < _TEMPORAL_GAP:
            continue
        older, newer = ((a, latest_a), (b, latest_b)) if latest_a < latest_b else ((b, latest_b), (a, latest_a))
        emit(
            ContradictionKind.TEMPORAL_CHANGE,
            f"Public association changed over time: '{older[0].label}' (latest {older[1].year}) -> "
            f"'{newer[0].label}' (latest {newer[1].year}).",
            [a.entity_id, b.entity_id],
            [fa.finding_id, fb.finding_id],
            "medium",
            "The older association may reflect a previous holder of the number (numbers are recycled); "
            "treat the newer one as current only with corroboration.",
        )

    # OWNERSHIP_CONFLICT: evidence text says the number belongs to someone else
    for f in sorted(findings, key=lambda x: (x.source_url, x.finding_id)):
        text = (f.evidence_text or "").lower()
        hits = [p for p in OWNERSHIP_PHRASES if p in text]
        if not hits:
            continue
        src = src_by_id.get(f.source_id)
        where = display_domain(src.url) if src else f.source_url
        ent_ids = [f.entity_id] if f.entity_id else []
        emit(
            ContradictionKind.OWNERSHIP_CONFLICT,
            f"A public post on {where} states the number may belong to someone else "
            f"(phrases: {', '.join(repr(h) for h in hits)}).",
            ent_ids,
            [f.finding_id],
            "high" if f.number_displayed else "medium",
            "Read the post in context: it may be a user report of a wrong/recycled number. Check its date against the other evidence.",
        )

    # attach to entities (sorted, unique)
    by_entity: dict[str, set[str]] = {e.entity_id: set(e.contradiction_ids) for e in entities}
    for c in out:
        for eid in c.entity_ids:
            if eid in by_entity:
                by_entity[eid].add(c.contradiction_id)
    for e in entities:
        e.contradiction_ids = sorted(by_entity[e.entity_id])
    return out


__all__ = ["detect_contradictions", "OWNERSHIP_PHRASES"]
