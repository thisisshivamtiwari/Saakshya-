"""
Lead relevance (ARCHITECTURE section 6 / spec section 8).

``score_lead`` decides which discovered attributes deserve their own follow-up searches.
It is additive and bounded to ``0..1``: a lead type weight, a bonus for the number of distinct
domains that produced it, a bonus for DIRECT evidence and A/B source quality, and penalties for
generic values (single-token names, bare business words) and for recursion depth.
"""

from __future__ import annotations

from core.models import Association, Finding, Lead, LeadType, Source, SourceQuality

from correlation._text import independent_domain, is_generic_business, name_tokens

TYPE_WEIGHTS: dict[LeadType, float] = {
    LeadType.EMAIL: 0.9,
    LeadType.USERNAME: 0.7,
    LeadType.BUSINESS: 0.7,
    LeadType.NAME: 0.6,
    LeadType.DOMAIN: 0.5,
    LeadType.PHONE: 0.5,
    LeadType.ADDRESS: 0.4,
}
DOMAIN_BONUS_PER_SOURCE = 0.05
DOMAIN_BONUS_CAP = 0.15
DIRECT_BONUS = 0.05
QUALITY_BONUS = 0.05
GENERIC_NAME_PENALTY = 0.3
GENERIC_BUSINESS_PENALTY = 0.25
DEPTH_PENALTY = 0.1
LOW_CONFIDENCE = 0.5


def score_lead(lead: Lead, findings: list[Finding], sources: list[Source]) -> float:
    """Compute, store (``lead.relevance``) and return the 0..1 relevance of a lead; appends reasons."""
    src_by_id = {s.source_id: s for s in sources}
    wanted = set(lead.origin_finding_ids)
    origin = [f for f in findings if f.finding_id in wanted]
    reasons: list[str] = []

    score = TYPE_WEIGHTS.get(lead.lead_type, 0.4)
    reasons.append(f"type {lead.lead_type.value}: +{score:.2f}")

    domains = {independent_domain(src_by_id[f.source_id].url if f.source_id in src_by_id else f.source_url) for f in origin}
    domains.discard("")
    if domains:
        bonus = min(DOMAIN_BONUS_CAP, DOMAIN_BONUS_PER_SOURCE * len(domains))
        score += bonus
        reasons.append(f"{len(domains)} distinct source domain(s): +{bonus:.2f}")
    if any(f.association == Association.DIRECT for f in origin):
        score += DIRECT_BONUS
        reasons.append(f"DIRECT evidence: +{DIRECT_BONUS:.2f}")
    qualities = {src_by_id[f.source_id].quality if f.source_id in src_by_id else f.source_quality for f in origin}
    if qualities & {SourceQuality.A, SourceQuality.B}:
        score += QUALITY_BONUS
        reasons.append(f"A/B quality source: +{QUALITY_BONUS:.2f}")

    value = lead.normalized_value or lead.value
    if lead.lead_type == LeadType.NAME:
        max_conf = max((f.confidence for f in origin), default=1.0)
        if len(name_tokens(value)) <= 1:
            score -= GENERIC_NAME_PENALTY
            reasons.append(f"single-token name: -{GENERIC_NAME_PENALTY:.2f}")
        elif max_conf < LOW_CONFIDENCE:
            score -= GENERIC_NAME_PENALTY
            reasons.append(f"low extraction confidence ({max_conf:.2f}): -{GENERIC_NAME_PENALTY:.2f}")
    if lead.lead_type == LeadType.BUSINESS and is_generic_business(value):
        score -= GENERIC_BUSINESS_PENALTY
        reasons.append(f"generic business word: -{GENERIC_BUSINESS_PENALTY:.2f}")
    if lead.depth > 0:
        score -= DEPTH_PENALTY * lead.depth
        reasons.append(f"depth {lead.depth}: -{DEPTH_PENALTY * lead.depth:.2f}")

    score = max(0.0, min(1.0, round(score, 4)))
    lead.relevance = score
    for r in reasons:
        if r not in lead.reasons:
            lead.reasons.append(r)
    return score


def rank_leads(leads: list[Lead], findings: list[Finding], sources: list[Source], *, limit: int) -> list[Lead]:
    """Score every lead and return the top ``limit`` (relevance desc, then type, then value)."""
    for lead in leads:
        score_lead(lead, findings, sources)
    # tie-break by lead-type weight (e-mail beats business beats name) so equal scores stay deterministic
    ordered = sorted(leads, key=lambda l: (-l.relevance, -TYPE_WEIGHTS.get(l.lead_type, 0.4), l.lead_type.value,
                                           (l.normalized_value or l.value).lower()))
    return ordered[: max(0, limit)] if limit is not None else ordered


__all__ = ["score_lead", "rank_leads", "TYPE_WEIGHTS"]
