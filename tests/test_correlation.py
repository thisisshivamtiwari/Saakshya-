"""Correlation-layer tests on a fully synthetic scenario (no real person, all *.example domains)."""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone

from core.models import (
    Association,
    Business,
    ContradictionKind,
    Document,
    EntityKind,
    FieldType,
    Finding,
    SocialProfile,
    Source,
    SourceQuality,
    SourceType,
    DatePrecision,
)
from core.normalize import normalize_indian_number
from correlation._text import is_business_name, normalise_name, token_set_ratio
from correlation.alternate_numbers import find_co_listed_numbers
from correlation.contradictions import detect_contradictions
from correlation.dedup import dedup_findings, dedup_sources, group_duplicate_sources_by_content, title_similarity
from correlation.entity_resolver import UNRESOLVED_LABEL, attach_derived_objects, resolve_entities
from correlation.graph import EvidenceGraph
from correlation.timeline import build_timeline

SUBJECT = "+919876543210"
CO_LISTED = "+919123456780"
NOISE = "+919876543219"


def dt(y: int, m: int = 1, d: int = 1) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


def mk_source(sid: str, url: str, quality: SourceQuality, stype: SourceType, published: datetime | None = None,
              title: str = "", provider: str = "fixture") -> Source:
    return Source(source_id=sid, url=url, title=title, source_type=stype, quality=quality, provider=provider,
                  published_at=published, date_precision=DatePrecision.DAY if published else DatePrecision.UNKNOWN,
                  referenced_by=[provider])


def mk_finding(fid: str, src: Source, field: FieldType, value: str, *, displayed: bool = True,
               association: Association = Association.DIRECT, evidence: str = "", confidence: float = 0.8,
               metadata: dict | None = None, normalized: str = "") -> Finding:
    return Finding(finding_id=fid, phone=SUBJECT, field=field, value=value, normalized_value=normalized,
                   source_id=src.source_id, source_url=src.url, source_type=src.source_type,
                   source_quality=src.quality, evidence_text=evidence or f"... {value} ... {SUBJECT if displayed else ''}",
                   published_at=src.published_at, date_precision=src.date_precision, confidence=confidence,
                   association=association, number_displayed=displayed, metadata=metadata or {})


def scenario() -> tuple[list[Source], list[Finding]]:
    s1 = mk_source("s1", "https://www.justdial.example/lucknow/verma-agro-traders", SourceQuality.C,
                   SourceType.BUSINESS_DIRECTORY, dt(2023, 4, 1), "Verma Agro Traders - Lucknow | Justdial")
    s2 = mk_source("s2", "https://vermaagrotraders.example.in/contact", SourceQuality.C,
                   SourceType.COMPANY_WEBSITE, dt(2024, 1, 15), "Contact Us - Verma Agro Traders")
    s3 = mk_source("s3", "https://eprocure.gov.example/tenders/2024/bid-4711.pdf", SourceQuality.A,
                   SourceType.TENDER, dt(2024, 3, 10), "Bid document 4711 - supply of agro inputs")
    s4 = mk_source("s4", "https://www.linkedin.example/in/rohanverma-lko", SourceQuality.B,
                   SourceType.SOCIAL_PROFILE, None, "Rohan Verma - Proprietor - Verma Agro Traders")
    s5 = mk_source("s5", "https://github.example/rohanverma-dev", SourceQuality.C, SourceType.CODE_REPOSITORY,
                   None, "rohanverma-dev (Rohan Verma)")
    s6 = mk_source("s6", "https://olx.example/item/used-bike-delhi-2019", SourceQuality.D,
                   SourceType.CLASSIFIED_LISTING, dt(2019, 6, 20), "Used bike for sale in Delhi")
    s7 = mk_source("s7", "https://forum.example/thread/9876", SourceQuality.D, SourceType.FORUM, dt(2022, 8, 1),
                   "Who called me from this number?")
    s8 = mk_source("s8", "https://randomsite.example.com/page", SourceQuality.E, SourceType.OTHER, None, "Random page")
    sources = [s1, s2, s3, s4, s5, s6, s7, s8]
    email = "rohan@vermaagrotraders.example.in"
    findings = [
        mk_finding("f01", s1, FieldType.NAME, "Rohan Verma"),
        mk_finding("f02", s1, FieldType.BUSINESS, "Verma Agro Traders"),
        mk_finding("f03", s1, FieldType.LOCATION, "Lucknow"),
        mk_finding("f04", s1, FieldType.PHONE, CO_LISTED),
        mk_finding("f05", s2, FieldType.BUSINESS, "Verma Agro Traders"),
        mk_finding("f06", s2, FieldType.EMAIL, email),
        mk_finding("f07", s2, FieldType.WEBSITE, "https://vermaagrotraders.example.in"),
        mk_finding("f08", s2, FieldType.LOCATION, "Lucknow"),
        mk_finding("f09", s2, FieldType.PHONE, "+91 91234 56780"),
        mk_finding("f10", s3, FieldType.NAME, "Shri Rohan Verma"),
        mk_finding("f11", s3, FieldType.BUSINESS, "Verma Agro Traders"),
        mk_finding("f12", s3, FieldType.EMAIL, email),
        mk_finding("f13", s3, FieldType.ADDRESS, "12 Hazratganj, Lucknow 226001"),
        mk_finding("f14", s3, FieldType.LOCATION, "Lucknow"),
        mk_finding("f15", s4, FieldType.NAME, "Rohan Verma", displayed=False, association=Association.INDIRECT),
        mk_finding("f16", s4, FieldType.USERNAME, "rohanverma-lko", displayed=False,
                   association=Association.INDIRECT, metadata={"platform": "linkedin"}),
        mk_finding("f17", s4, FieldType.JOB_TITLE, "Proprietor", displayed=False, association=Association.INDIRECT),
        mk_finding("f18", s4, FieldType.EMAIL, email, displayed=False, association=Association.INDIRECT),
        mk_finding("f19", s5, FieldType.USERNAME, "rohanverma-dev", displayed=False,
                   association=Association.INDIRECT, metadata={"platform": "github"}),
        mk_finding("f20", s5, FieldType.EMAIL, email, displayed=False, association=Association.INDIRECT),
        mk_finding("f21", s6, FieldType.NAME, "Amit Kumar"),
        mk_finding("f22", s6, FieldType.LOCATION, "Delhi"),
        mk_finding("f23", s7, FieldType.MENTION, SUBJECT,
                   evidence="Someone keeps calling; this is a wrong number, it is not my number anymore."),
        mk_finding("f24", s8, FieldType.PHONE, NOISE, displayed=False, association=Association.INFERRED),
    ]
    return sources, findings


def resolved():
    sources, findings = scenario()
    phone = normalize_indian_number(SUBJECT)
    entities, rels = resolve_entities(phone, findings, sources)
    return phone, sources, findings, entities, rels


# ---------------------------------------------------------------- text helpers

def test_text_helpers():
    assert normalise_name("Shri Rohan Verma") == "rohan verma"
    assert normalise_name("Dr. A. K. Singh") == "a k singh"
    assert token_set_ratio("Rohan Verma", "Verma Rohan") == 1.0
    assert token_set_ratio("Rohan Verma", "Amit Kumar") < 0.5
    assert is_business_name("Verma Agro Traders")
    assert not is_business_name("Rohan Verma")


# ---------------------------------------------------------------- dedup

def test_dedup_sources_merges_providers():
    a = mk_source("a", "http://www.justdial.example/lucknow/x?utm_source=g", SourceQuality.E, SourceType.OTHER,
                  provider="brave", title="Short")
    b = mk_source("b", "https://justdial.example/lucknow/x", SourceQuality.C, SourceType.BUSINESS_DIRECTORY,
                  dt(2023, 1, 1), provider="serper", title="Longer title here")
    out = dedup_sources([a, b, a])
    assert len(out) == 1
    s = out[0]
    assert s.quality == SourceQuality.C and s.source_type == SourceType.BUSINESS_DIRECTORY
    assert set(s.referenced_by) == {"brave", "serper"}
    assert s.title == "Longer title here" and s.published_at == dt(2023, 1, 1)
    assert "b" in s.extra["merged_source_ids"]


def test_dedup_findings_merges_confidence_and_association():
    src = mk_source("a", "https://justdial.example/x", SourceQuality.C, SourceType.BUSINESS_DIRECTORY)
    f1 = mk_finding("x1", src, FieldType.NAME, "Rohan Verma", displayed=False, association=Association.INFERRED, confidence=0.4)
    f2 = mk_finding("x2", src, FieldType.NAME, "rohan verma", confidence=0.9)
    out = dedup_findings([f1, f2])
    assert len(out) == 1
    assert out[0].confidence == 0.9 and out[0].association == Association.DIRECT and out[0].number_displayed


def test_content_groups_and_title_similarity():
    a = mk_source("a", "https://justdial.example/x", SourceQuality.C, SourceType.BUSINESS_DIRECTORY, title="Verma Agro Traders Lucknow")
    b = mk_source("b", "https://sulekha.example/y", SourceQuality.C, SourceType.BUSINESS_DIRECTORY, title="Verma Agro Traders - Lucknow")
    c = mk_source("c", "https://olx.example/z", SourceQuality.D, SourceType.CLASSIFIED_LISTING, title="Used bike")
    assert title_similarity(a.title, b.title) >= 0.92
    groups = group_duplicate_sources_by_content([a, b, c])
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2]
    assert a.extra["duplicate_group"]["size"] == 2 and "duplicate_group" not in c.extra


# ---------------------------------------------------------------- entity resolution

def test_two_candidates_never_merged_and_a_ranked_first():
    _, sources, findings, entities, rels = resolved()
    labels = [e.label for e in entities]
    assert labels[0] == "Rohan Verma"
    assert "Amit Kumar" in labels
    assert labels[-1] == UNRESOLVED_LABEL
    a = entities[0]
    assert a.kind == EntityKind.PERSON
    assert a.businesses == ["Verma Agro Traders"]
    assert a.emails == ["rohan@vermaagrotraders.example.in"]
    assert set(a.usernames) == {"linkedin:rohanverma-lko", "github:rohanverma-dev"}
    assert a.websites == ["vermaagrotraders.example.in"]
    assert a.locations == ["Lucknow"] and a.job_titles == ["Proprietor"]
    assert a.independent_source_count == 5
    assert a.association == Association.DIRECT
    assert a.first_seen == dt(2023, 4, 1) and a.last_seen == dt(2024, 3, 10)
    assert a.associated_numbers == [CO_LISTED]
    assert any("Rohan Verma" in w and "independent source" in w for w in a.why_linked)
    b = next(e for e in entities if e.label == "Amit Kumar")
    assert b.kind == EntityKind.PERSON and b.locations == ["Delhi"] and b.independent_source_count == 1
    # every finding is attributed
    assert all(f.entity_id for f in findings)
    # relationships
    relations = {r.relation for r in rels}
    assert {"HAS_CANDIDATE", "HAS_NAME", "HAS_EMAIL", "HAS_USERNAME", "RUNS_BUSINESS", "HAS_WEBSITE",
            "LOCATED_IN", "HAS_ADDRESS", "CO_LISTED_WITH", "MENTIONED_IN", "HAS_JOB_TITLE"} <= relations
    co = [r for r in rels if r.relation == "CO_LISTED_WITH"]
    assert co and co[0].to_id == f"phone:{CO_LISTED}" and co[0].from_id == f"ent:{a.entity_id}"
    assert all(r.from_id.startswith(("phone:", "ent:")) for r in rels)


def test_strong_key_merges_conflicting_names_but_fuzzy_does_not():
    phone = normalize_indian_number(SUBJECT)
    x = mk_source("x", "https://siteone.example.in/a", SourceQuality.C, SourceType.COMPANY_WEBSITE)
    y = mk_source("y", "https://sitetwo.example.in/b", SourceQuality.C, SourceType.COMPANY_WEBSITE)
    without_key = [mk_finding("k1", x, FieldType.NAME, "Rohan Verma"), mk_finding("k2", y, FieldType.NAME, "R Verma")]
    ents, _ = resolve_entities(phone, without_key, [x, y])
    assert len(ents) == 2, "different full names must not merge without a strong key"
    with_key = without_key + [mk_finding("k3", x, FieldType.EMAIL, "rv@siteone.example.in"),
                              mk_finding("k4", y, FieldType.EMAIL, "RV@siteone.example.in")]
    ents, _ = resolve_entities(phone, with_key, [x, y])
    assert len(ents) == 1
    assert set(ents[0].names) == {"Rohan Verma", "R Verma"}
    assert any("strong key" in w for w in ents[0].why_linked)


def test_business_only_source_is_business_entity():
    phone = normalize_indian_number(SUBJECT)
    x = mk_source("x", "https://indiamart.example/shop", SourceQuality.C, SourceType.BUSINESS_DIRECTORY)
    ents, _ = resolve_entities(phone, [mk_finding("b1", x, FieldType.BUSINESS, "Sharma Electricals")], [x])
    assert ents[0].kind == EntityKind.BUSINESS and ents[0].label == "Sharma Electricals"


def test_attach_derived_objects():
    _, sources, findings, entities, _ = resolved()
    a = entities[0]
    prof = SocialProfile(platform="linkedin", username="rohanverma-lko", finding_ids=["f16"])
    biz = Business(name="Verma Agro Traders", finding_ids=["f02"])
    doc = Document(url=sources[2].url, finding_ids=["f10"])
    attach_derived_objects(entities, [prof], [biz], [doc], [])
    assert prof.entity_id == a.entity_id and biz.entity_id == a.entity_id and doc.entity_id == a.entity_id
    assert prof.profile_id in a.social_profile_ids and doc.document_id in a.document_ids


# ---------------------------------------------------------------- contradictions

def test_name_conflict_temporal_change_and_ownership():
    phone, sources, findings, entities, _ = resolved()
    ctrs = detect_contradictions(phone, entities, findings, sources)
    kinds = {c.kind for c in ctrs}
    assert ContradictionKind.NAME_CONFLICT in kinds
    assert ContradictionKind.TEMPORAL_CHANGE in kinds
    assert ContradictionKind.OWNERSHIP_CONFLICT in kinds
    assert ContradictionKind.LOCATION_CONFLICT not in kinds
    name = next(c for c in ctrs if c.kind == ContradictionKind.NAME_CONFLICT)
    a = entities[0]
    b = next(e for e in entities if e.label == "Amit Kumar")
    assert set(name.entity_ids) == {a.entity_id, b.entity_id}
    assert name.severity == "medium"  # B has only one independent source
    assert name.resolution_hint
    assert name.contradiction_id in a.contradiction_ids and name.contradiction_id in b.contradiction_ids
    temporal = next(c for c in ctrs if c.kind == ContradictionKind.TEMPORAL_CHANGE)
    assert "2019" in temporal.description and "2024" in temporal.description
    own = next(c for c in ctrs if c.kind == ContradictionKind.OWNERSHIP_CONFLICT)
    assert own.finding_ids == ["f23"] and "wrong number" in own.description


def test_location_conflict_within_entity():
    phone = normalize_indian_number(SUBJECT)
    x = mk_source("x", "https://justdial.example/a", SourceQuality.C, SourceType.BUSINESS_DIRECTORY)
    y = mk_source("y", "https://sulekha.example/b", SourceQuality.C, SourceType.BUSINESS_DIRECTORY)
    fs = [mk_finding("l1", x, FieldType.NAME, "Rohan Verma"), mk_finding("l2", x, FieldType.LOCATION, "Lucknow"),
          mk_finding("l3", y, FieldType.NAME, "Rohan Verma"), mk_finding("l4", y, FieldType.LOCATION, "Kanpur")]
    ents, _ = resolve_entities(phone, fs, [x, y])
    assert len(ents) == 1
    ctrs = detect_contradictions(phone, ents, fs, [x, y])
    assert [c.kind for c in ctrs] == [ContradictionKind.LOCATION_CONFLICT]


# ---------------------------------------------------------------- timeline

def test_timeline_order_unknown_last():
    _, sources, findings, entities, _ = resolved()
    tl = build_timeline(findings, sources, entities)
    dated = [e for e in tl if e.date]
    assert [e.date for e in dated] == sorted(e.date for e in dated)
    assert dated[0].date == dt(2019, 6, 20) and "Amit Kumar" in dated[0].description
    undated = [e for e in tl if e.date is None]
    assert undated and tl[-1].date is None
    assert all(e.date is not None for e in tl[: len(dated)])
    assert any("Number displayed on justdial.example (business_directory) with Rohan Verma" in e.description for e in tl)
    assert any(e.kind == "entity_first_seen" and "Rohan Verma" in e.description for e in tl)


# ---------------------------------------------------------------- co-listed numbers

def test_co_listed_only_when_subject_displayed():
    phone, sources, findings, entities, _ = resolved()
    nums = find_co_listed_numbers(phone, findings, sources, entities)
    assert [n.e164 for n in nums] == [CO_LISTED]
    n = nums[0]
    assert n.masked == "+91******6780" and n.relation == "publicly_co_listed"
    assert n.confidence == 0.8 and n.entity_id == entities[0].entity_id
    assert "also listed on" in n.reason and "Rohan Verma" in n.reason
    assert NOISE not in {x.e164 for x in nums}
    # same PHONE finding on a page that does NOT display the subject -> nothing
    src = mk_source("q", "https://noise.example/p", SourceQuality.C, SourceType.OTHER)
    only = [mk_finding("n1", src, FieldType.PHONE, "+919111111111", displayed=False)]
    assert find_co_listed_numbers(phone, only, [src]) == []


# ---------------------------------------------------------------- graph

def test_graph_counts_and_json_roundtrip():
    phone, sources, findings, entities, rels = resolved()
    g = EvidenceGraph.from_investigation_parts(phone, entities, rels, findings, sources)
    st = g.stats()
    assert st["nodes"] >= 1 + len(entities) + 7  # phone + entities + at least the referenced sources
    assert st["edges"] == len(rels)
    assert st["relations"]["HAS_CANDIDATE"] == len(entities)
    data = g.to_node_link()
    text = json.dumps(data)
    back = json.loads(text)
    assert len(back["nodes"]) == st["nodes"] and len(back["edges"]) == st["edges"]
    tree = g.to_ascii_tree()
    assert tree.startswith(f"PHONE {SUBJECT}") and "├── " in tree and "└── " in tree and "Rohan Verma" in tree
    assert g.to_pyvis_html() is None or "<html" in g.to_pyvis_html().lower()
    # incremental API
    g2 = EvidenceGraph(phone)
    g2.add_entity(entities[0])
    g2.add_finding(findings[0], sources[0])
    assert g2.G.has_node("name:rohan verma") and g2.G.has_node("doc:s1")


# ---------------------------------------------------------------- determinism

def test_determinism_under_input_shuffle():
    phone = normalize_indian_number(SUBJECT)
    base_sources, base_findings = scenario()
    ents1, rels1 = resolve_entities(phone, base_findings, base_sources)
    rng = random.Random(7)
    sources, findings = scenario()
    rng.shuffle(sources)
    rng.shuffle(findings)
    ents2, rels2 = resolve_entities(phone, findings, sources)
    assert [e.entity_id for e in ents1] == [e.entity_id for e in ents2]
    assert [e.label for e in ents1] == [e.label for e in ents2]
    assert [r.relationship_id for r in rels1] == [r.relationship_id for r in rels2]
    assert [sorted(e.finding_ids) for e in ents1] == [sorted(e.finding_ids) for e in ents2]
