"""Scoring-layer tests: transparent ledger, labels, executive summary and lead ranking."""

from __future__ import annotations

from datetime import datetime, timezone

from core.models import (
    Association,
    ConfidenceLabel,
    ContradictionKind,
    EntityKind,
    FieldType,
    Investigation,
    Lead,
    LeadType,
    QueryRecord,
    SourceQuality,
    SourceType,
)
from core.normalize import normalize_indian_number
from core.strategy import SearchBudget
from correlation.alternate_numbers import find_co_listed_numbers
from correlation.contradictions import detect_contradictions
from correlation.entity_resolver import resolve_entities
from scoring.confidence import RULES, build_executive_summary, label_for, score_entity, summarize_confidence
from scoring.information_gain import branch_summary, information_gain
from scoring.relevance import rank_leads, score_lead
from tests.test_correlation import SUBJECT, mk_finding, mk_source, scenario

NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


def scored():
    sources, findings = scenario()
    phone = normalize_indian_number(SUBJECT)
    entities, rels = resolve_entities(phone, findings, sources)
    ctrs = detect_contradictions(phone, entities, findings, sources)
    for e in entities:
        e.score = score_entity(e, findings, sources, ctrs, now=NOW)
    return phone, sources, findings, entities, rels, ctrs


def test_rules_table_matches_spec():
    assert RULES == {
        "exact_phone_match": 40, "same_name_multiple_sources": 25, "same_business": 15, "same_location": 10,
        "same_email": 10, "same_username": 10, "multiple_independent_sources": 10,
        "official_or_primary_source": 10, "direct_association": 5,
        "contradictory_location": -30, "contradictory_name": -30, "evidence_belongs_to_other_person": -50,
        "low_quality_sources_only": -15, "inferred_only": -20, "stale_evidence_only": -10,
    }


def test_candidate_a_ledger_and_label():
    _, _, _, entities, _, ctrs = scored()
    a = entities[0]
    rules = {c.rule: c for c in a.score.components}
    for r in ("exact_phone_match", "same_name_multiple_sources", "same_business", "same_location", "same_email",
              "same_username", "multiple_independent_sources", "official_or_primary_source", "direct_association",
              "contradictory_name"):
        assert r in rules, r
    assert "low_quality_sources_only" not in rules and "stale_evidence_only" not in rules and "inferred_only" not in rules
    assert rules["exact_phone_match"].points == 40 and rules["exact_phone_match"].finding_ids
    assert "eprocure.gov.in" in rules["official_or_primary_source"].reason
    assert all(c.reason for c in a.score.components)
    assert a.score.total_points == sum(c.points for c in a.score.components)
    assert a.score.percent >= 75
    assert a.score.label in (ConfidenceLabel.STRONG_MATCH, ConfidenceLabel.FACT)
    # a name conflict is on record, so FACT must be withheld
    assert a.score.label == ConfidenceLabel.STRONG_MATCH
    assert "estimate" in a.score.note


def test_candidate_b_is_lower_and_contradictory():
    _, _, _, entities, _, _ = scored()
    a = entities[0]
    b = next(e for e in entities if e.label == "Amit Kumar")
    rules = {c.rule for c in b.score.components}
    assert {"exact_phone_match", "direct_association", "contradictory_name", "low_quality_sources_only",
            "stale_evidence_only"} <= rules
    assert b.score.percent < a.score.percent
    assert b.score.label in (ConfidenceLabel.CONTRADICTORY, ConfidenceLabel.WEAK_ASSOCIATION, ConfidenceLabel.UNVERIFIED)
    assert b.score.label == ConfidenceLabel.CONTRADICTORY


def test_fact_requires_official_direct_and_no_contradictions():
    phone = normalize_indian_number(SUBJECT)
    gov = mk_source("g", "https://mca.gov.example/company/123", SourceQuality.A, SourceType.GOVERNMENT_REGISTRY)
    jd = mk_source("j", "https://justdial.example/x", SourceQuality.C, SourceType.BUSINESS_DIRECTORY)
    fs = [mk_finding("a1", gov, FieldType.NAME, "Rohan Verma"), mk_finding("a2", gov, FieldType.BUSINESS, "Verma Agro Traders"),
          mk_finding("a3", jd, FieldType.NAME, "Rohan Verma"), mk_finding("a4", jd, FieldType.BUSINESS, "Verma Agro Traders")]
    ents, _ = resolve_entities(phone, fs, [gov, jd])
    ctrs = detect_contradictions(phone, ents, fs, [gov, jd])
    assert ctrs == []
    score = score_entity(ents[0], fs, [gov, jd], ctrs, now=NOW)
    assert score.label == ConfidenceLabel.FACT and score.percent >= 75
    # inferred-only evidence can never be FACT
    inf = [mk_finding("i1", gov, FieldType.NAME, "Rohan Verma", displayed=False, association=Association.INFERRED)]
    ents2, _ = resolve_entities(phone, inf, [gov])
    s2 = score_entity(ents2[0], inf, [gov], [], now=NOW)
    assert "inferred_only" in {c.rule for c in s2.components} and s2.label == ConfidenceLabel.UNVERIFIED


def test_label_for_bands():
    assert label_for(90, True, 3, False) == ConfidenceLabel.FACT
    assert label_for(90, False, 3, False) == ConfidenceLabel.STRONG_MATCH
    assert label_for(90, True, 1, False) == ConfidenceLabel.STRONG_MATCH
    assert label_for(90, True, 3, False, has_any_contradiction=True) == ConfidenceLabel.STRONG_MATCH
    assert label_for(60, False, 1, False) == ConfidenceLabel.POSSIBLE_MATCH
    assert label_for(30, False, 1, False) == ConfidenceLabel.WEAK_ASSOCIATION
    assert label_for(10, False, 1, False) == ConfidenceLabel.UNVERIFIED
    assert label_for(60, False, 1, True) == ConfidenceLabel.CONTRADICTORY
    assert label_for(80, False, 1, True) == ConfidenceLabel.STRONG_MATCH


def test_stale_evidence_uses_injected_now():
    phone = normalize_indian_number(SUBJECT)
    old = mk_source("o", "https://olx.example/old", SourceQuality.D, SourceType.CLASSIFIED_LISTING,
                    datetime(2019, 1, 1, tzinfo=timezone.utc))
    fs = [mk_finding("o1", old, FieldType.NAME, "Amit Kumar")]
    ents, _ = resolve_entities(phone, fs, [old])
    stale = score_entity(ents[0], fs, [old], [], now=NOW)
    fresh = score_entity(ents[0], fs, [old], [], now=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert "stale_evidence_only" in {c.rule for c in stale.components}
    assert "stale_evidence_only" not in {c.rule for c in fresh.components}


def test_summary_and_executive_summary_counts():
    phone, sources, findings, entities, rels, ctrs = scored()
    summary = summarize_confidence(entities)
    assert summary.top_entity_id == entities[0].entity_id and summary.top_percent == entities[0].score.percent
    assert summary.rules == RULES and set(summary.per_entity) == {e.entity_id for e in entities}
    numbers = find_co_listed_numbers(phone, findings, sources, entities)
    inv = Investigation(
        phone=phone, entities=entities, findings=findings, sources=sources, relationships=rels,
        contradictions=ctrs, associated_numbers=numbers,
        emails=sorted({f.value.lower() for f in findings if f.field == FieldType.EMAIL}),
        usernames=sorted({f.value for f in findings if f.field == FieldType.USERNAME}),
        queries=[QueryRecord(provider="fixture", query='"9876543210"')],
    )
    es = build_executive_summary(inv)
    assert es.candidate_identity == "Rohan Verma" and es.candidate_kind == EntityKind.PERSON
    assert es.confidence_percent == entities[0].score.percent and es.confidence_label == entities[0].score.label
    assert es.possible_location == "Lucknow"
    assert es.candidate_count == 2  # the unresolved pseudo-entity is not a candidate
    assert es.contradiction_count == len(ctrs) and es.sources_consulted == 8 and es.queries_executed == 1
    assert es.public_emails == 1 and es.public_usernames == 2 and es.associated_public_numbers == 1
    assert "2019" in es.headline and "2024" in es.headline and "estimate" in es.headline
    assert "2 candidate" in es.headline and "contradiction" in es.headline
    empty = build_executive_summary(Investigation(phone=phone))
    assert empty.candidate_identity == "No candidate identity established from public sources"


def test_lead_ranking_email_above_generic_name():
    sources, findings = scenario()
    email = Lead(lead_type=LeadType.EMAIL, value="rohan@vermaagrotraders.example.in", origin_finding_ids=["f06", "f12", "f18"])
    generic = Lead(lead_type=LeadType.NAME, value="Rohan", origin_finding_ids=["f01"])
    full = Lead(lead_type=LeadType.NAME, value="Rohan Verma", origin_finding_ids=["f01", "f10"])
    biz = Lead(lead_type=LeadType.BUSINESS, value="Verma Agro Traders", origin_finding_ids=["f02", "f05", "f11"])
    generic_biz = Lead(lead_type=LeadType.BUSINESS, value="Services", origin_finding_ids=["f02"])
    deep = Lead(lead_type=LeadType.EMAIL, value="x@y.example", origin_finding_ids=["f06"], depth=2)
    ranked = rank_leads([generic, deep, generic_biz, biz, full, email], findings, sources, limit=4)
    assert len(ranked) == 4
    assert ranked[0].value == email.value
    assert ranked[0].relevance == 1.0
    assert email.relevance > full.relevance > generic.relevance
    assert biz.relevance > generic_biz.relevance
    assert deep.relevance < email.relevance
    assert all(0.0 <= l.relevance <= 1.0 for l in [generic, deep, generic_biz, biz, full, email])
    assert any("single-token" in r for r in generic.reasons)
    assert score_lead(generic, findings, sources) == generic.relevance


def test_information_gain_reexport_and_branch_summary():
    assert information_gain(10, 5) == 0.5 and information_gain(0, 0) == 0.0
    budget = SearchBudget(max_queries=10)
    budget.record("exact", 10, 8)
    budget.record("social", 10, 0)
    budget.record("social", 10, 0)
    text = branch_summary(budget)
    assert "Queries executed: 3/10" in text and "social" in text and "(exhausted)" in text
