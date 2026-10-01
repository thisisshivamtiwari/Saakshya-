"""HTTP client safeguards (retry, rate limit, robots, size) and the query strategy engine."""

import asyncio

import httpx
import pytest
import respx

from config.settings import Settings
from core.http import HttpClient, RateLimitedError
from core.models import Depth, InvestigationConfig, Lead, LeadType
from core.normalize import normalize_indian_number
from core.strategy import LeadContext, QueryPlanner, SearchBudget, information_gain
from storage.cache import ResponseCache


def _settings(**kw):
    return Settings(_env_file=None, OSINT_HTTP_MAX_RETRIES=2, OSINT_PER_HOST_RATE=100, **kw)


@respx.mock
def test_retry_then_success_and_cache():
    route = respx.get("https://api.example.com/x").mock(side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": 1})])

    async def run():
        async with HttpClient(_settings(), ResponseCache(":memory:")) as http:
            p1, c1 = await http.get_json("https://api.example.com/x", params={"q": "1"}, headers={"X-Key": "secret"})
            p2, c2 = await http.get_json("https://api.example.com/x", params={"q": "1"}, headers={"X-Key": "secret"})
            return p1, c1, p2, c2, http.cache

    p1, c1, p2, c2, cache = asyncio.run(run())
    assert p1 == {"ok": 1} and not c1 and p2 == {"ok": 1} and c2
    assert route.call_count == 2
    # secrets in headers never reach the cache
    import sqlite3

    rows = cache._conn.execute("SELECT key, url, query, payload FROM cache").fetchall()
    assert rows and not any("secret" in " ".join(map(str, r)) for r in rows)


@respx.mock
def test_persistent_429_raises_rate_limited():
    respx.get("https://api.example.com/y").mock(return_value=httpx.Response(429, headers={"Retry-After": "0"}))

    async def run():
        async with HttpClient(_settings()) as http:
            await http.get_json("https://api.example.com/y")

    with pytest.raises(RateLimitedError):
        asyncio.run(run())


@respx.mock
def test_fetch_page_robots_size_and_content_type():
    respx.get("https://www.site.example/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private/\n"))
    respx.get("https://www.site.example/public").mock(return_value=httpx.Response(200, text="<p>hi 9876543210</p>", headers={"content-type": "text/html"}))
    respx.get("https://www.site.example/private/x").mock(return_value=httpx.Response(200, text="secret"))
    respx.get("https://www.site.example/big").mock(return_value=httpx.Response(200, content=b"x" * 200, headers={"content-type": "text/html"}))
    respx.get("https://www.site.example/bin").mock(return_value=httpx.Response(200, content=b"\x00", headers={"content-type": "application/octet-stream"}))

    async def run():
        async with HttpClient(_settings(OSINT_MAX_FETCH_BYTES=100)) as http:
            return (await http.fetch_page("https://www.site.example/public"),
                    await http.fetch_page("https://www.site.example/private/x"),
                    await http.fetch_page("https://www.site.example/big"),
                    await http.fetch_page("https://www.site.example/bin"))

    ok, blocked, big, binary = asyncio.run(run())
    assert ok.ok and "9876543210" in ok.text and ok.robots_allowed is True and ok.content_hash
    assert blocked.error == "robots_disallowed" and blocked.robots_allowed is False and not blocked.text
    assert "too large" in big.error
    assert "unsupported content-type" in binary.error


def test_planner_depths_and_budget():
    ph = normalize_indian_number("+919876543210")
    sizes = {}
    for d in Depth:
        plan = QueryPlanner(InvestigationConfig.for_depth(ph.raw, d, cities=["Lucknow"]), ph).preview()
        sizes[d] = len(plan)
        assert len({p.query.lower() for p in plan}) == len(plan)  # no duplicates
    assert sizes[Depth.QUICK] < sizes[Depth.STANDARD] < sizes[Depth.DEEP]
    std = QueryPlanner(InvestigationConfig.for_depth(ph.raw, Depth.STANDARD), ph)
    plan = std.preview()
    assert plan[0].query == '"+919876543210"'
    assert any(p.requires_filetype_operator and "filetype:pdf" in p.query for p in plan)
    assert any(p.requires_site_operator and "site:linkedin.com" in p.query for p in plan)
    lead = Lead(lead_type=LeadType.NAME, value="Rohan Verma", relevance=0.9)
    lq = std.lead_queries(lead, LeadContext(cities=["Lucknow"], businesses=["Verma Agro Traders"]))
    assert lq and lq[0].query == '"Rohan Verma" "9876543210"' and len(lq) <= 4
    low = Lead(lead_type=LeadType.NAME, value="Rohan Verma", relevance=0.0, lead_id="l2")
    assert len(std.lead_queries(low)) <= 2
    assert std.lead_queries(Lead(lead_type=LeadType.PHONE, value="+919123456780"))[0].query.startswith('"+919123456780"')

    b = SearchBudget(max_queries=3, info_gain_threshold=0.15)
    assert b.record("exact", 10, 8) == 0.8 and not b.branch_exhausted("exact")
    b.record("exact", 10, 1)
    b.record("exact", 10, 0)
    assert b.branch_exhausted("exact") and not b.can_run()
    assert information_gain(0, 0) == 0.0 and information_gain(4, 2) == 0.5
