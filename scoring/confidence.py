"""
Transparent confidence scoring (ARCHITECTURE section 6 / spec section 17).

Every point on the ledger comes from a named rule in ``RULES``; ``score_entity`` records a
``ScoreComponent`` (rule, points, human reason, finding ids) for *each rule that fired*, so a
reader of the report can recompute the score by hand.  The percentage is an **analytical
estimate**, never a statement of fact:

* ``FACT`` is reserved for entities whose number is literally displayed by an A/B quality
  source, corroborated by >= 2 independent sources, with no contradiction on record.
* ``CONTRADICTORY`` overrides the numeric bands when a NAME or OWNERSHIP contradiction
  involves the entity and the score is below 75.
* An INFERRED-only entity is penalised (-20) and can never be labelled FACT.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from core.models import (
    Association,
    ConfidenceLabel,
    ConfidenceSummary,
    Contradiction,
    ContradictionKind,
    Entity,
    EntityKind,
    ExecutiveSummary,
    FieldType,
    Finding,
    Investigation,
    ScoreBreakdown,
    ScoreComponent,
    Source,
    SourceQuality,
)

from correlation._text import (
    display_domain,
    independent_domain,
    join_human,
    names_fuzzy_equal,
    normalise_business,
    normalise_city,
    normalise_email,
)
from correlation.entity_resolver import UNRESOLVED_LABEL

RULES: dict[str, int] = {
    "exact_phone_match": 40,
    "same_name_multiple_sources": 25,
    "same_business": 15,
    "same_location": 10,
    "same_email": 10,
    "same_username": 10,
    "multiple_independent_sources": 10,
    "official_or_primary_source": 10,
    "direct_association": 5,
    "contradictory_location": -30,
    "contradictory_name": -30,
    "evidence_belongs_to_other_person": -50,
    "low_quality_sources_only": -15,
    "inferred_only": -20,
    "stale_evidence_only": -10,
}

STALE_AFTER = timedelta(days=3 * 365)
_OFFICIAL = {SourceQuality.A, SourceQuality.B}
_LOW = {SourceQuality.D, SourceQuality.E}


def _clamp(v: int) -> int:
    return max(0, min(100, v))


def label_for(
    percent: int,
    has_official_direct: bool,
    independent_sources: int,
    has_conflict: bool,
    has_any_contradiction: Optional[bool] = None,
) -> ConfidenceLabel:
    """
    Map a score to its label.

    ``has_conflict`` = a NAME or OWNERSHIP contradiction involves the entity;
    ``has_any_contradiction`` (defaults to ``has_conflict``) = any contradiction at all,
    which is enough to withhold FACT.
    """
    any_ctr = has_conflict if has_any_contradiction is None else has_any_contradiction
    if has_conflict and percent < 75:
        return ConfidenceLabel.CONTRADICTORY
    if has_official_direct and independent_sources >= 2 and not any_ctr and percent >= 75:
        return ConfidenceLabel.FACT
    if percent >= 75:
        return ConfidenceLabel.STRONG_MATCH
    if percent >= 50:
        return ConfidenceLabel.POSSIBLE_MATCH
    if percent >= 25:
        return ConfidenceLabel.WEAK_ASSOCIATION
    return ConfidenceLabel.UNVERIFIED


def _domain(f: Finding, sources: dict[str, Source]) -> str:
    src = sources.get(f.source_id)
    return independent_domain(src.url if src else f.source_url)


def _quality(f: Finding, sources: dict[str, Source]) -> SourceQuality:
    src = sources.get(f.source_id)
    return src.quality if src else f.source_quality


def _date(f: Finding, sources: dict[str, Source]) -> Optional[datetime]:
    if f.published_at is not None:
        return f.published_at
    src = sources.get(f.source_id)
    return src.published_at if src else None


def score_entity(
    entity: Entity,
    findings: list[Finding],
    sources: list[Source],
    contradictions: list[Contradiction],
    now: Optional[datetime] = None,
) -> ScoreBreakdown:
    """
    Apply every rule in ``RULES`` to one entity and return the ledger.  Pure apart from the
    staleness check, which uses ``now`` (injectable) or the current UTC time.
    """
    src_by_id = {s.source_id: s for s in sources}
    wanted = set(entity.finding_ids)
    fs = [f for f in findings if f.finding_id in wanted]
    ent_sources = [src_by_id[s] for s in entity.source_ids if s in src_by_id]
    components: list[ScoreComponent] = []

    def add(rule: str, reason: str, finding_ids: list[str]) -> None:
        components.append(ScoreComponent(rule=rule, points=RULES[rule], reason=reason, finding_ids=sorted(set(finding_ids))))

    def doms(items: list[Finding]) -> list[str]:
        return sorted({_domain(f, src_by_id) for f in items if _domain(f, src_by_id)})

    # exact_phone_match
    direct = [f for f in fs if f.association == Association.DIRECT and f.number_displayed]
    if direct:
        add("exact_phone_match",
            f"The subject number is literally displayed on {join_human(doms(direct))}",
            [f.finding_id for f in direct])

    # same_name_multiple_sources
    primary = entity.label if entity.label != UNRESOLVED_LABEL else ""
    if primary:
        if entity.kind == EntityKind.PERSON:
            name_fs = [f for f in fs if f.field in (FieldType.NAME, FieldType.ALIAS) and f.number_displayed
                       and names_fuzzy_equal(f.value, primary)]
        else:
            name_fs = [f for f in fs if f.field in (FieldType.BUSINESS, FieldType.ORGANIZATION, FieldType.NAME)
                       and f.number_displayed and normalise_business(f.value) == normalise_business(primary)]
        name_doms = doms(name_fs)
        if len(name_doms) >= 2:
            add("same_name_multiple_sources",
                f"Name '{primary}' appears with the number on {len(name_doms)} distinct domains ({join_human(name_doms)})",
                [f.finding_id for f in name_fs])

    # same_business
    biz_fs = [f for f in fs if f.field in (FieldType.BUSINESS, FieldType.ORGANIZATION)
              or (f.field == FieldType.NAME and normalise_business(f.value) in {normalise_business(b) for b in entity.businesses})]
    by_biz: dict[str, list[Finding]] = {}
    for f in biz_fs:
        by_biz.setdefault(normalise_business(f.value), []).append(f)
    for key in sorted(by_biz):
        group = by_biz[key]
        with_number = [f for f in group if f.number_displayed]
        n_sources = len({f.source_id for f in group})
        if (with_number and len(entity.source_ids) >= 2) or n_sources >= 2:
            add("same_business",
                f"Business '{group[0].value}' co-occurs with the number on {len(with_number)} source(s) and is "
                f"named on {n_sources} source(s) in total",
                [f.finding_id for f in group])
            break

    # same_location
    by_city: dict[str, list[Finding]] = {}
    for f in fs:
        if f.field == FieldType.LOCATION:
            city = normalise_city(str((f.metadata or {}).get("city") or f.normalized_value or f.value))
            by_city.setdefault(city, []).append(f)
    for city in sorted(by_city):
        cdoms = doms(by_city[city])
        if len(cdoms) >= 2:
            add("same_location", f"Location '{by_city[city][0].value}' is reported by {len(cdoms)} domains ({join_human(cdoms)})",
                [f.finding_id for f in by_city[city]])
            break

    # same_email / same_username
    for rule, field, word in (("same_email", FieldType.EMAIL, "E-mail"), ("same_username", FieldType.USERNAME, "Username")):
        by_val: dict[str, list[Finding]] = {}
        for f in fs:
            if f.field == field:
                key = normalise_email(f.normalized_value or f.value) if field == FieldType.EMAIL else (f.normalized_value or f.value).lower()
                by_val.setdefault(key, []).append(f)
        for key in sorted(by_val):
            group = by_val[key]
            gdoms = doms(group)
            displayed = [f for f in group if f.number_displayed]
            # a username/e-mail on a public page that also carries the entity's name/e-mail/business is
            # corroborated within the cluster (e.g. a profile page naming the person)
            identity_sources = {x.source_id for x in fs
                                if x.field in (FieldType.NAME, FieldType.EMAIL, FieldType.BUSINESS)}
            corroborated = [f for f in group if f.source_id in identity_sources]
            if len(gdoms) >= 2 or displayed or corroborated:
                if len(gdoms) >= 2:
                    how = f"links {len(gdoms)} domains ({join_human(gdoms)})"
                elif displayed:
                    how = f"is displayed alongside the number on {join_human(doms(displayed))}"
                else:
                    how = f"appears on a public page that also names the entity ({join_human(doms(corroborated))})"
                add(rule, f"{word} '{group[0].value}' {how}", [f.finding_id for f in group])
                break

    # multiple_independent_sources
    if entity.independent_source_count >= 3:
        add("multiple_independent_sources",
            f"{entity.independent_source_count} independent domains reference this entity",
            [f.finding_id for f in fs])

    # official_or_primary_source
    official = [f for f in direct if _quality(f, src_by_id) == SourceQuality.A]
    if official:
        add("official_or_primary_source",
            f"An official / primary (A-quality) source displays the number: {join_human(doms(official))}",
            [f.finding_id for f in official])

    # direct_association
    if entity.association == Association.DIRECT:
        add("direct_association", "At least one finding is a DIRECT association (number on the same page)",
            [f.finding_id for f in fs if f.association == Association.DIRECT])

    # contradictions referencing this entity
    mine = [c for c in contradictions if entity.entity_id in c.entity_ids]
    for rule, kind in (("contradictory_location", ContradictionKind.LOCATION_CONFLICT),
                       ("contradictory_name", ContradictionKind.NAME_CONFLICT),
                       ("evidence_belongs_to_other_person", ContradictionKind.OWNERSHIP_CONFLICT)):
        hits = [c for c in mine if c.kind == kind]
        if hits:
            add(rule, hits[0].description, [fid for c in hits for fid in c.finding_ids if fid in wanted])

    # low_quality_sources_only
    qualities = {s.quality for s in ent_sources} or {_quality(f, src_by_id) for f in fs}
    if qualities and qualities <= _LOW:
        add("low_quality_sources_only", "Every source for this entity is user-generated or of unknown reliability (D/E)",
            [f.finding_id for f in fs])

    # inferred_only
    if fs and not any(f.association in (Association.DIRECT, Association.INDIRECT) for f in fs):
        add("inferred_only", "No DIRECT or INDIRECT finding: the association is inferred from correlated attributes only",
            [f.finding_id for f in fs])

    # stale_evidence_only
    ref_now = now or datetime.now(timezone.utc)
    dated = [(d, f) for f in fs if (d := _date(f, src_by_id)) is not None]
    undated_direct = [f for f in fs if _date(f, src_by_id) is None and f.association == Association.DIRECT]
    if dated and all(ref_now - d > STALE_AFTER for d, _ in dated) and not undated_direct:
        newest = max(d for d, _ in dated)
        add("stale_evidence_only", f"All dated evidence is older than 3 years (newest {newest.date().isoformat()})",
            [f.finding_id for _, f in dated])

    total = sum(c.points for c in components)
    percent = _clamp(total)
    has_official_direct = bool(official) or any(
        f.association == Association.DIRECT and f.number_displayed and _quality(f, src_by_id) in _OFFICIAL for f in fs
    )
    has_conflict = any(c.kind in (ContradictionKind.NAME_CONFLICT, ContradictionKind.OWNERSHIP_CONFLICT) for c in mine)
    label = label_for(percent, has_official_direct, entity.independent_source_count, has_conflict, bool(mine))
    if entity.label == UNRESOLVED_LABEL:
        label = ConfidenceLabel.UNVERIFIED
    return ScoreBreakdown(components=components, total_points=total, percent=percent, label=label)


def summarize_confidence(entities: list[Entity]) -> ConfidenceSummary:
    """Top entity (highest percent, ties by list order) plus the rule table used."""
    summary = ConfidenceSummary(rules=dict(RULES), per_entity={e.entity_id: e.score.percent for e in entities})
    candidates = [e for e in entities if e.label != UNRESOLVED_LABEL] or list(entities)
    if candidates:
        top = max(candidates, key=lambda e: e.score.percent)  # max keeps the first on ties
        summary.top_entity_id = top.entity_id
        summary.top_percent = top.score.percent
        summary.top_label = top.score.label
    return summary


def build_executive_summary(inv: Investigation) -> ExecutiveSummary:
    """One honest paragraph plus counts.  The candidate identity is the highest-scoring entity."""
    candidates = [e for e in inv.entities if e.label != UNRESOLVED_LABEL]
    top = max(candidates, key=lambda e: e.score.percent) if candidates else None
    years = sorted({d.year for d in (
        [f.published_at for f in inv.findings if f.published_at] + [s.published_at for s in inv.sources if s.published_at]
    )})
    es = ExecutiveSummary(
        candidate_identity=top.label if top else "No candidate identity established from public sources",
        candidate_kind=top.kind if top else EntityKind.UNKNOWN,
        confidence_percent=top.score.percent if top else 0,
        confidence_label=top.score.label if top else ConfidenceLabel.UNVERIFIED,
        possible_location=(top.locations[0] if top and top.locations else ""),
        public_businesses=len(inv.businesses),
        public_emails=len(inv.emails),
        public_usernames=len(inv.usernames),
        public_profiles=len(inv.social_profiles),
        public_documents=len(inv.documents),
        associated_public_numbers=len(inv.associated_numbers),
        candidate_count=len(candidates),
        contradiction_count=len(inv.contradictions),
        sources_consulted=len(inv.sources),
        queries_executed=len(inv.queries),
    )
    if top:
        head = (f"Public sources most often associate {inv.phone.masked or inv.phone.e164} with "
                f"'{top.label}' ({top.kind.value}, {top.score.label.value}, {top.score.percent}%)"
                + (f" in {top.locations[0]}" if top.locations else "") + ".")
    else:
        head = f"No candidate identity could be established for {inv.phone.masked or inv.phone.e164} from public sources."
    parts = [head, f"{len(candidates)} candidate identit{'y was' if len(candidates) == 1 else 'ies were'} found across "
                   f"{len(inv.sources)} source(s)."]
    if inv.contradictions:
        kinds = sorted({c.kind.value.replace('_', ' ') for c in inv.contradictions})
        parts.append(f"{len(inv.contradictions)} contradiction(s) were recorded ({join_human(kinds)}); they are described, not resolved.")
    else:
        parts.append("No contradictions were recorded.")
    if years:
        parts.append(f"Dated evidence spans {years[0]}" + (f" to {years[-1]}" if years[-1] != years[0] else "") + ".")
    parts.append("All scores are analytical estimates from public-source correlation, not factual certainty; "
                 "the number may be shared, outdated or reassigned.")
    es.headline = " ".join(parts)
    return es


__all__ = ["RULES", "score_entity", "label_for", "summarize_confidence", "build_executive_summary"]
