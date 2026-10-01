"""respx-mocked tests for the API search providers (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from config.settings import Settings
from core.http import HttpClient
from core.models import ProviderState, SearchResult
from providers.search.brave import BraveSearchProvider
from providers.search.google_cse import DEPRECATION_NOTICE, GoogleCSEProvider
from providers.search.serpapi import SerpApiSearchProvider
from providers.search.serper import SerperSearchProvider
from providers.search.tavily import TavilySearchProvider, translate_query
from storage.cache import ResponseCache

KEY_VARS = ("BRAVE_API_KEY", "SERPAPI_KEY", "SERPER_API_KEY", "TAVILY_API_KEY",
            "GOOGLE_CSE_API_KEY", "GOOGLE_CSE_CX")
SECRET = "sk-test-SECRET-0123456789abcdef"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)


def make_settings(**keys: str) -> Settings:
    # no retries so a 429 surfaces immediately; high per-host rate so tests never sleep
    return Settings(_env_file=None, OSINT_HTTP_MAX_RETRIES=0, OSINT_PER_HOST_RATE=1000, **keys)


def make(cls: type, cache: ResponseCache | None = None, **keys: str) -> Any:
    settings = make_settings(**keys)
    return cls(settings, HttpClient(settings, cache))


def cache_rows(cache: ResponseCache) -> list[tuple[Any, ...]]:
    return cache._conn.execute("SELECT key, url, query, payload FROM cache").fetchall()


# --------------------------------------------------------------------------- #
# Brave
# --------------------------------------------------------------------------- #
BRAVE_PAYLOAD = {
    "web": {"results": [
        {"url": "https://www.example.in/contact", "title": "Contact", "description": "Call 98765 43210",
         "page_age": "2023-08-15T00:00:00", "extra_snippets": ["snippet one", "snippet two"]},
        {"url": "https://docs.example.in/brochure.pdf", "title": "Brochure", "description": "pdf"},
    ]},
    "news": {"results": [{"url": "https://news.example.in/a", "title": "News", "description": "n"}]},
    "discussions": {"results": [{"url": "https://forum.example.in/t/1", "title": "Thread", "description": "d"}]},
}


@respx.mock
async def test_brave_request_and_parse() -> None:
    route = respx.get(BraveSearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json=BRAVE_PAYLOAD))
    p = make(BraveSearchProvider, BRAVE_API_KEY=SECRET)
    results = await p.search('"9876543210" Lucknow', max_results=10)
    req = route.calls.last.request
    assert req.headers["X-Subscription-Token"] == SECRET
    assert req.headers["Accept"] == "application/json"
    assert req.url.params["q"] == '"9876543210" Lucknow'
    assert req.url.params["count"] == "10"
    assert req.url.params["country"] == "IN"
    assert req.url.params["search_lang"] == "en"
    assert req.url.params["safesearch"] == "off"
    assert req.url.params["extra_snippets"] == "true"
    assert len(results) == 4 and all(isinstance(r, SearchResult) for r in results)
    first = results[0]
    assert first.provider == "brave" and first.url == "https://www.example.in/contact"
    assert first.snippet == "Call 98765 43210"
    assert first.extra["extra_snippets"] == "snippet one | snippet two"
    assert first.extra["section"] == "web"
    assert first.published_at is not None and first.published_at.year == 2023
    assert results[1].file_type == "pdf"
    assert {r.extra["section"] for r in results} == {"web", "news", "discussions"}
    assert p.errors == []


@respx.mock
async def test_brave_max_results_and_count_cap() -> None:
    many = {"web": {"results": [{"url": f"https://s{i}.example.in/", "title": str(i), "description": ""}
                                for i in range(20)]}}
    route = respx.get(BraveSearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json=many))
    p = make(BraveSearchProvider, BRAVE_API_KEY=SECRET)
    assert len(await p.search("x", max_results=3)) == 3
    assert route.calls.last.request.url.params["count"] == "3"
    p2 = make(BraveSearchProvider, BRAVE_API_KEY=SECRET)
    await p2.search("x", max_results=50)
    assert route.calls.last.request.url.params["count"] == "20"


@respx.mock
async def test_brave_empty_and_rate_limited() -> None:
    respx.get(BraveSearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json={"web": {"results": []}}))
    p = make(BraveSearchProvider, BRAVE_API_KEY=SECRET)
    assert await p.search("nothing") == []
    assert p.errors == []
    respx.get(BraveSearchProvider.ENDPOINT).mock(return_value=httpx.Response(429, json={"error": "slow down"}))
    p = make(BraveSearchProvider, BRAVE_API_KEY=SECRET)
    assert await p.search("x") == []
    assert p.errors and "rate limited" in p.errors[0]
    assert SECRET not in " ".join(p.errors)


async def test_brave_missing_key() -> None:
    p = make(BraveSearchProvider)
    assert p.state == ProviderState.MISSING_KEY
    assert p.available is False
    assert "brave_api_key" in p.unavailable_reason()
    assert await p.search("x") == []


# --------------------------------------------------------------------------- #
# SerpApi
# --------------------------------------------------------------------------- #
SERPAPI_PAYLOAD = {
    "search_metadata": {"status": "Success"},
    "organic_results": [
        {"position": 1, "title": "Verma Agro", "link": "https://www.example.in/x", "snippet": "call 9876543210",
         "date": "Jun 12, 2019"},
        {"position": 2, "title": "Two", "link": "https://www.example.in/y", "snippet": "two"},
    ],
}


@respx.mock
async def test_serpapi_request_parse_and_key_not_cached() -> None:
    route = respx.get(SerpApiSearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json=SERPAPI_PAYLOAD))
    cache = ResponseCache(":memory:")
    p = make(SerpApiSearchProvider, cache, SERPAPI_KEY=SECRET)
    results = await p.search('"9876543210"', max_results=10)
    req = route.calls.last.request
    assert req.url.params["api_key"] == SECRET
    assert req.url.params["engine"] == "google"
    assert req.url.params["google_domain"] == "google.co.in"
    assert req.url.params["gl"] == "in" and req.url.params["hl"] == "en"
    assert req.url.params["num"] == "10" and req.url.params["start"] == "0"
    assert [r.url for r in results] == ["https://www.example.in/x", "https://www.example.in/y"]
    assert results[0].provider == "serpapi" and results[0].extra["position"] == 1
    assert results[0].published_at is not None and results[0].published_at.year == 2019
    rows = cache_rows(cache)
    assert rows, "response should be cached"
    assert SECRET not in json.dumps(rows)
    # second call is served from the cache
    again = await p.search('"9876543210"', max_results=10)
    assert len(again) == 2 and route.call_count == 1
    assert SECRET not in " ".join(p.errors)


@respx.mock
async def test_serpapi_engine_kwarg_and_max_results() -> None:
    route = respx.get(SerpApiSearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json=SERPAPI_PAYLOAD))
    p = make(SerpApiSearchProvider, None, SERPAPI_KEY=SECRET)
    results = await p.search("x", max_results=1, engine="bing")
    assert len(results) == 1
    assert route.calls.last.request.url.params["engine"] == "bing"
    assert "google_domain" not in route.calls.last.request.url.params
    p2 = SerpApiSearchProvider(make_settings(SERPAPI_KEY=SECRET), HttpClient(make_settings(SERPAPI_KEY=SECRET)),
                               engine="duckduckgo")
    await p2.search("x")
    assert route.calls.last.request.url.params["engine"] == "duckduckgo"


@respx.mock
async def test_serpapi_empty_error_and_429() -> None:
    respx.get(SerpApiSearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json={"organic_results": []}))
    p = make(SerpApiSearchProvider, None, SERPAPI_KEY=SECRET)
    assert await p.search("x") == [] and p.errors == []
    respx.get(SerpApiSearchProvider.ENDPOINT).mock(return_value=httpx.Response(429, text="Too Many Requests"))
    p = make(SerpApiSearchProvider, None, SERPAPI_KEY=SECRET)
    assert await p.search("x") == []
    assert p.errors and "rate limited" in p.errors[0] and SECRET not in p.errors[0]
    respx.get(SerpApiSearchProvider.ENDPOINT).mock(return_value=httpx.Response(401, json={"error": "Invalid API key"}))
    p = make(SerpApiSearchProvider, None, SERPAPI_KEY=SECRET)
    assert await p.search("x") == []
    assert p.errors == ["serpapi: HTTP 401"]


async def test_serpapi_missing_key() -> None:
    p = make(SerpApiSearchProvider)
    assert p.state == ProviderState.MISSING_KEY and not p.available
    assert p.paid is True
    assert await p.search("x") == []


# --------------------------------------------------------------------------- #
# Serper
# --------------------------------------------------------------------------- #
SERPER_PAYLOAD = {"organic": [
    {"title": "A", "link": "https://a.example.in/", "snippet": "sa", "position": 1, "date": "Mar 5, 2024"},
    {"title": "B", "link": "https://b.example.in/doc.docx", "snippet": "sb", "position": 2},
    {"title": "C", "link": "https://c.example.in/", "snippet": "sc", "position": 3},
]}


@respx.mock
async def test_serper_request_and_parse() -> None:
    route = respx.post(SerperSearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json=SERPER_PAYLOAD))
    p = make(SerperSearchProvider, SERPER_API_KEY=SECRET)
    results = await p.search('"9876543210"', max_results=2)
    req = route.calls.last.request
    assert req.headers["X-API-KEY"] == SECRET
    assert req.headers["Content-Type"] == "application/json"
    body = json.loads(req.content)
    assert body == {"q": '"9876543210"', "gl": "in", "hl": "en", "num": 2, "page": 1}
    assert len(results) == 2  # max_results honoured even though 3 came back
    assert results[0].provider == "serper" and results[0].published_at is not None
    assert results[0].published_at.year == 2024
    assert results[1].file_type == "docx"


@respx.mock
async def test_serper_empty_429_and_missing_key() -> None:
    respx.post(SerperSearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json={"organic": []}))
    p = make(SerperSearchProvider, SERPER_API_KEY=SECRET)
    assert await p.search("x") == [] and p.errors == []
    respx.post(SerperSearchProvider.ENDPOINT).mock(return_value=httpx.Response(429))
    p = make(SerperSearchProvider, SERPER_API_KEY=SECRET)
    assert await p.search("x") == []
    assert p.errors and "rate limited" in p.errors[0]
    p = make(SerperSearchProvider)
    assert p.state == ProviderState.MISSING_KEY and not p.available
    assert await p.search("x") == []


# --------------------------------------------------------------------------- #
# Tavily
# --------------------------------------------------------------------------- #
TAVILY_PAYLOAD = {"query": "x", "results": [
    {"title": "T1", "url": "https://www.linkedin.example/in/x", "content": "c1", "score": 0.91},
    {"title": "T2", "url": "https://www.linkedin.example/in/y", "content": "c2", "score": 0.5},
]}


def test_tavily_translate_query() -> None:
    clean, inc, exc, ft = translate_query('site:linkedin.com "Rohan Verma" -site:facebook.com')
    assert clean == '"Rohan Verma"'
    assert inc == ["linkedin.com"] and exc == ["facebook.com"]
    assert ft is False
    assert translate_query('"9876543210" filetype:pdf')[3] is True


@respx.mock
async def test_tavily_site_translation_and_parse() -> None:
    route = respx.post(TavilySearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json=TAVILY_PAYLOAD))
    p = make(TavilySearchProvider, TAVILY_API_KEY=SECRET)
    results = await p.search('site:linkedin.com "Rohan Verma" Lucknow', max_results=1)
    req = route.calls.last.request
    assert req.headers["Authorization"] == f"Bearer {SECRET}"
    body = json.loads(req.content)
    assert body["query"] == '"Rohan Verma" Lucknow'
    assert body["include_domains"] == ["linkedin.com"]
    assert body["exact_match"] is True
    assert body["search_depth"] == "basic" and body["country"] == "india" and body["max_results"] == 1
    assert "site:" not in body["query"]
    assert len(results) == 1
    assert results[0].provider == "tavily" and results[0].snippet == "c1" and results[0].extra["score"] == 0.91
    assert TavilySearchProvider.supports_filetype_operator is False
    assert TavilySearchProvider.supports_site_operator is True


@respx.mock
async def test_tavily_no_exact_match_filetype_skip_empty_429_missing_key() -> None:
    route = respx.post(TavilySearchProvider.ENDPOINT).mock(return_value=httpx.Response(200, json={"results": []}))
    p = make(TavilySearchProvider, TAVILY_API_KEY=SECRET)
    assert await p.search("rohan verma lucknow") == []
    assert "exact_match" not in json.loads(route.calls.last.request.content)
    assert await p.search('"9876543210" filetype:pdf') == []
    assert route.call_count == 1  # filetype query never sent
    respx.post(TavilySearchProvider.ENDPOINT).mock(return_value=httpx.Response(429))
    p = make(TavilySearchProvider, TAVILY_API_KEY=SECRET)
    assert await p.search("x") == []
    assert p.errors and "rate limited" in p.errors[0]
    p = make(TavilySearchProvider)
    assert p.state == ProviderState.MISSING_KEY and not p.available
    assert await p.search("x") == []


# --------------------------------------------------------------------------- #
# Google CSE
# --------------------------------------------------------------------------- #
CSE_PAYLOAD = {"items": [
    {"title": "G1", "link": "https://g1.example.in/", "snippet": "s1",
     "pagemap": {"metatags": [{"article:published_time": "2022-06-30T10:00:00Z"}]}},
    {"title": "G2", "link": "https://g2.example.in/file", "snippet": "s2", "mime": "application/pdf"},
    {"title": "G3", "link": "https://g3.example.in/", "snippet": "s3"},
]}


@respx.mock
async def test_google_cse_request_parse_key_not_cached(caplog: pytest.LogCaptureFixture) -> None:
    GoogleCSEProvider._warned = False
    route = respx.get(GoogleCSEProvider.ENDPOINT).mock(return_value=httpx.Response(200, json=CSE_PAYLOAD))
    cache = ResponseCache(":memory:")
    p = make(GoogleCSEProvider, cache, GOOGLE_CSE_API_KEY=SECRET, GOOGLE_CSE_CX="cx-123")
    assert p.deprecated is True and p.paid is True
    with caplog.at_level("WARNING", logger="osint"):
        results = await p.search('"9876543210"', max_results=2)
    assert any(DEPRECATION_NOTICE in r.getMessage() for r in caplog.records)
    req = route.calls.last.request
    assert req.url.params["key"] == SECRET and req.url.params["cx"] == "cx-123"
    assert req.url.params["q"] == '"9876543210"'
    assert req.url.params["num"] == "2" and req.url.params["start"] == "1" and req.url.params["gl"] == "in"
    assert len(results) == 2
    assert results[0].provider == "google_cse"
    assert results[0].published_at is not None and results[0].published_at.year == 2022
    assert results[1].file_type == "pdf" and results[1].extra["mime"] == "application/pdf"
    rows = cache_rows(cache)
    assert rows and SECRET not in json.dumps(rows)
    await p.search('"9876543210"', max_results=2)
    assert route.call_count == 1
    p2 = make(GoogleCSEProvider, None, GOOGLE_CSE_API_KEY=SECRET, GOOGLE_CSE_CX="cx-123")
    await p2.search("x", max_results=50)
    assert route.calls.last.request.url.params["num"] == "10"


@respx.mock
async def test_google_cse_empty_429_and_missing_key() -> None:
    respx.get(GoogleCSEProvider.ENDPOINT).mock(return_value=httpx.Response(200, json={"kind": "customsearch#search"}))
    p = make(GoogleCSEProvider, None, GOOGLE_CSE_API_KEY=SECRET, GOOGLE_CSE_CX="cx")
    assert await p.search("x") == [] and p.errors == []
    respx.get(GoogleCSEProvider.ENDPOINT).mock(return_value=httpx.Response(429))
    p = make(GoogleCSEProvider, None, GOOGLE_CSE_API_KEY=SECRET, GOOGLE_CSE_CX="cx")
    assert await p.search("x") == []
    assert p.errors and "rate limited" in p.errors[0] and SECRET not in p.errors[0]
    p = make(GoogleCSEProvider, None, GOOGLE_CSE_API_KEY=SECRET)  # cx missing
    assert p.state == ProviderState.MISSING_KEY and not p.available
    assert "2027-01-01" in p.unavailable_reason()
    assert await p.search("x") == []
