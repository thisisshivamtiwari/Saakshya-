"""End-to-end offline investigation on the synthetic fixture (no network)."""

import asyncio
from pathlib import Path

import pytest

from config.settings import Settings
from core.engine import InvestigationEngine
from core.models import (
    Association,
    ConfidenceLabel,
    ContradictionKind,
    Depth,
    EntityKind,
    InvestigationConfig,
    ProgressEvent,
    Stage,
    StageStatus,
)


@pytest.fixture(scope="module")
def offline_result(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    events: list[ProgressEvent] = []
    settings = Settings(_env_file=None, OSINT_DATA_DIR=str(out / "data"), OSINT_OUTPUT_DIR=str(out))
    engine = InvestigationEngine(settings, progress=events.append, persist=True)
    cfg = InvestigationConfig.for_depth("+91 98765 43210", Depth.STANDARD, offline=True, output_dir=str(out),
                                        formats=["json", "markdown", "html", "csv"], case_reference="TEST-1",
                                        authorization_note="synthetic fixture test")
    inv = engine.run_sync(cfg)
    return inv, engine, events, out


def test_stages_and_progress(offline_result):
    inv, engine, events, _ = offline_result
    done = {s.stage for s in inv.investigation.stages if s.status == StageStatus.DONE}
    for stage in (Stage.NORMALIZE, Stage.TELECOM, Stage.SEARCH, Stage.DOCUMENTS, Stage.SOCIAL, Stage.BUSINESS,
                  Stage.REGISTRIES, Stage.CLASSIFIEDS, Stage.PAGE_FETCH, Stage.LEAD_EXPANSION, Stage.CORRELATION,
                  Stage.SCORING, Stage.REPORT):
        assert stage in done, stage
    assert any(e.stage == Stage.CORRELATION for e in events)
    assert inv.investigation.case_reference == "TEST-1" and inv.investigation.finished_at


def test_candidates_contradictions_and_alternate_numbers(offline_result):
    inv, *_ = offline_result
    assert inv.entities and inv.entities[0].label == "Rohan Verma"
    top = inv.entities[0]
    assert top.kind == EntityKind.PERSON and top.score.percent >= 75
    assert top.score.label in (ConfidenceLabel.STRONG_MATCH, ConfidenceLabel.FACT)
    assert any(c.rule == "exact_phone_match" for c in top.score.components)
    assert top.why_linked
    labels = {e.label for e in inv.entities}
    assert "Amit Kumar" in labels  # the older Delhi association is a SEPARATE candidate, never merged
    amit = next(e for e in inv.entities if e.label == "Amit Kumar")
    assert amit.score.percent < top.score.percent
    kinds = {c.kind for c in inv.contradictions}
    assert ContradictionKind.NAME_CONFLICT in kinds and ContradictionKind.TEMPORAL_CHANGE in kinds
    nums = {a.e164 for a in inv.associated_numbers}
    assert "+919123456780" in nums and "+919876543210" not in nums
    assert all(a.source_url and a.reason for a in inv.associated_numbers)


def test_evidence_provenance(offline_result):
    inv, *_ = offline_result
    assert inv.findings and all(f.source_url and f.evidence_text for f in inv.findings)
    assert all(f.source_id in {s.source_id for s in inv.sources} for f in inv.findings)
    assert any(f.association == Association.DIRECT and f.number_displayed for f in inv.findings)
    assert any(s.fetched for s in inv.sources)
    assert any(s.robots_allowed is False for s in inv.sources)  # robots.txt was respected
    assert inv.queries and all(q.provider == "fixture" for q in inv.queries)
    assert inv.documents and any(d.fetched for d in inv.documents)
    assert inv.social_profiles and any(p.platform == "linkedin" for p in inv.social_profiles)
    assert inv.businesses and any("Verma Agro" in b.name for b in inv.businesses)
    assert inv.listings
    assert inv.timeline and inv.graph.get("nodes") and inv.graph.get("ascii")
    assert inv.limitations and any("Portability" in l for l in inv.limitations)
    assert "rohan@vermaagrotraders.example.in" in inv.emails


def test_reports_and_store_written(offline_result):
    inv, engine, _, out = offline_result
    assert {"json", "markdown", "html"} <= set(engine.last_paths)
    for p in engine.last_paths.values():
        assert Path(p).exists()
    assert (out / "data" / "evidence.sqlite").exists()
    snaps = list((out / "data" / "snapshots").rglob("*.json"))
    assert snaps


def test_invalid_number_aborts_cleanly(tmp_path):
    engine = InvestigationEngine(Settings(_env_file=None), persist=False)
    inv = engine.run_sync(InvestigationConfig.for_depth("+1 415 555 2671", Depth.QUICK, formats=[]))
    assert not inv.phone.ok and inv.limitations and not inv.entities
    assert inv.investigation.stages[0].status == StageStatus.FAILED


def test_quick_depth_skips_stages():
    engine = InvestigationEngine(Settings(_env_file=None), persist=False)
    inv = engine.run_sync(InvestigationConfig.for_depth("9876543210", Depth.QUICK, offline=True, formats=[]))
    skipped = {s.stage for s in inv.investigation.stages if s.status == StageStatus.SKIPPED}
    assert Stage.DOCUMENTS in skipped and Stage.SOCIAL in skipped and Stage.LEAD_EXPANSION in skipped
    assert len(inv.queries) <= 12


def test_no_search_provider_is_reported():
    async def run():
        engine = InvestigationEngine(Settings(_env_file=None), persist=False)
        return await engine.run(InvestigationConfig.for_depth("9876543210", Depth.STANDARD, formats=[]))

    inv = asyncio.run(run())
    assert inv.phone.ok and not inv.queries
    assert any("No search provider" in l for l in inv.limitations)
    assert inv.telecom  # libphonenumber still ran offline
