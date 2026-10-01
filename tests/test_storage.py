"""Evidence store, snapshots and response cache."""

import time
from pathlib import Path

from core.models import Source
from storage.cache import ResponseCache, cache_key
from storage.evidence_store import EvidenceStore
from storage.snapshots import SnapshotStore
from tests.factories import make_sample_investigation


def test_evidence_store_round_trip_and_snippet_policy(tmp_path: Path):
    inv = make_sample_investigation()
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    inv_id = store.save(inv, store_provider_snippets=False)
    loaded = store.load(inv_id)
    assert loaded is not None and loaded.phone.e164 == inv.phone.e164
    assert len(loaded.findings) == len(inv.findings) and len(loaded.entities) == len(inv.entities)
    # provider snippets (unfetched sources) are blanked; our own excerpts are kept
    for orig, back in zip(inv.sources, loaded.sources):
        if orig.fetched:
            assert back.excerpt == orig.excerpt
        else:
            assert back.excerpt == ""
    store.save(inv, store_provider_snippets=True)
    kept = store.load(inv_id)
    assert any(s.excerpt for s in kept.sources if not s.fetched) or all(s.fetched for s in inv.sources)
    rows = store.list()
    assert rows and rows[0]["investigation_id"] == inv_id and "****" in rows[0]["phone_masked"]
    store.delete(inv_id)
    assert store.load(inv_id) is None
    store.close()


def test_snapshot_bound(tmp_path: Path):
    snap = SnapshotStore(tmp_path / "snaps")
    src = Source(url="https://www.example.in/x", title="T", content_hash="abc")
    p = snap.save(src, "x" * 5000, max_chars=100)
    data = snap.load(src.source_id)
    assert p.exists() and data and len(data["excerpt"]) == 100 and data["content_hash"] == "abc"
    assert snap.load("missing") is None


def test_response_cache_ttl_and_stats():
    c = ResponseCache(":memory:", ttl_seconds=1)
    k = cache_key("t", "q")
    digest = c.set(k, {"a": 1}, url="u", query="q", status=200)
    e = c.get(k)
    assert e and e.payload == {"a": 1} and e.content_hash == digest and e.status == 200
    time.sleep(1.1)
    assert c.get(k) is None  # expired
    assert c.get(k, max_age=-1) is not None  # negative max_age disables TTL
    assert c.stats()["entries"] == 1 and c.purge_expired() == 1
    c.close()
