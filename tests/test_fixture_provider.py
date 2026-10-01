"""Tests for the offline fixture search engine, transport and the synthetic fixture file."""

from __future__ import annotations

import io
from datetime import datetime
from urllib.parse import urlsplit

import httpx
import pytest
from pypdf import PdfReader

from config.settings import Settings
from core.http import HttpClient
from core.models import SearchResult
from extractors.url_utils import host_of
from providers.search.fixture import (
    DEFAULT_FIXTURE_PATH,
    REQUIRED_DOCUMENT_FIELDS,
    FixtureSearchProvider,
    build_minimal_pdf,
    build_offline_transport,
    load_fixture,
    number_present,
    parse_query,
    search_documents,
)

CONTACT = "https://www.vermaagrotraders.example.in/contact.html"
NOISE = "https://www.lucknowbizlist.example.in/listing/gupta-hardware-and-sanitary-aliganj"
TOFLER = "https://www.tofler.example/company/verma-agro-traders-private-limited/U01100UP2021PTC148231"
TENDER = "https://eprocure.gov.example/eprocure/app/tenders/2024/UPAGRI-2024-017/bid-document.pdf"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return load_fixture()


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, OSINT_PER_HOST_RATE=1000, OSINT_HTTP_MAX_RETRIES=0)


@pytest.fixture
def provider(settings: Settings, fixture: dict) -> FixtureSearchProvider:
    http = HttpClient(settings, transport=build_offline_transport(fixture))
    return FixtureSearchProvider(settings, http)


def urls(results: list[SearchResult]) -> list[str]:
    return [r.url for r in results]


# --------------------------------------------------------------------------- #
# Fixture file validation
# --------------------------------------------------------------------------- #
def test_fixture_file_is_valid(fixture: dict) -> None:
    assert DEFAULT_FIXTURE_PATH.is_file()
    assert fixture["phone"] == "+919876543210"
    docs = fixture["documents"]
    assert 18 <= len(docs) <= 25
    seen: set[str] = set()
    for d in docs:
        for k in REQUIRED_DOCUMENT_FIELDS:
            assert k in d, (d["url"], k)
        host = host_of(d["url"])
        assert host.endswith((".example", ".example.in", ".example.com")), host
        assert d["url"] not in seen
        seen.add(d["url"])
        assert 300 <= len(d["text"]) <= 1500, d["url"]
        assert d["content_type"] in ("text/html", "application/pdf", "text/plain")
        if d["published_at"] is not None:
            datetime.fromisoformat(d["published_at"])
        if d["content_type"] == "application/pdf":
            assert d["file_type"] == "pdf"
    assert any(d.get("robots_disallow") for d in docs)
    assert fixture["telecom"] == [{"provider": "fixture", "field": "carrier",
                                   "value": "Example Telecom (original allocation)", "confidence": 0.4}]
    # scenario landmarks
    assert any(d["url"] == CONTACT for d in docs)
    assert any("olx.example" in d["url"] and "2019" in (d["published_at"] or "") for d in docs)
    assert any("9876543299" in d["text"] for d in docs)
    assert any("wrong number" in d["text"].lower() for d in docs)


# --------------------------------------------------------------------------- #
# Query parsing and digit-aware matching
# --------------------------------------------------------------------------- #
def test_parse_query_operators() -> None:
    pq = parse_query('"98765 43210" site:linkedin.example filetype:pdf -spam olx OR quikr -"not this" lucknow')
    assert pq.phrases == ["98765 43210"]
    assert pq.excluded_phrases == ["not this"]
    assert pq.sites == ["linkedin.example"]
    assert pq.filetypes == ["pdf"]
    assert pq.excluded_terms == ["spam"]
    assert pq.groups == [["olx", "quikr"], ["lucknow"]]


def test_number_present_variants() -> None:
    hay = "Call +91 98765 43210 or office 0522-4098765. Pincode 226010."
    for variant in ("9876543210", "98765 43210", "+919876543210", "09876543210", "+91 98765 43210", "0091 9876543210"):
        assert number_present(hay, variant), variant
    assert not number_present(hay, "9876543299")
    assert not number_present(hay, "98765432")
    assert not number_present("Phone: 9876543299", "9876543210")
    assert number_present(hay, "0522-4098765")
    assert not number_present("Pin 226010 then 9876543210", "2260109876")


@pytest.mark.parametrize("variant", ['"98765 43210"', '"+919876543210"', '"09876543210"', '"9876543210"',
                                     '"+91 98765 43210"', '"+91-98765-43210"'])
async def test_all_phone_variants_hit_the_same_documents(provider: FixtureSearchProvider, variant: str) -> None:
    results = await provider.search(variant, max_results=50)
    found = urls(results)
    assert CONTACT in found
    assert TENDER in found
    assert NOISE not in found
    assert all(r.provider == "fixture" for r in results)
    assert len(found) >= 15


async def test_noise_number_does_not_match_subject(provider: FixtureSearchProvider) -> None:
    results = await provider.search('"9876543299"', max_results=50)
    assert urls(results) == [NOISE]
    landline = await provider.search('"0522-4098765"', max_results=50)
    assert urls(landline) == ["https://www.facebook.example/SharmaElectricalsLucknow"]


async def test_site_filter(provider: FixtureSearchProvider) -> None:
    results = await provider.search('site:linkedin.example "Rohan Verma"', max_results=50)
    assert urls(results) == ["https://www.linkedin.example/in/rohan-verma-lko"]
    results = await provider.search('site:vermaagrotraders.example.in', max_results=50)
    assert len(results) == 2 and all(host_of(u).endswith("vermaagrotraders.example.in") for u in urls(results))
    assert await provider.search('site:nothing.example "9876543210"') == []


async def test_filetype_filter(provider: FixtureSearchProvider) -> None:
    results = await provider.search('"9876543210" filetype:pdf', max_results=50)
    assert set(urls(results)) == {TENDER,
                                  "https://www.scribd.example/document/612345678/Verma-Agro-Traders-Product-Brochure-2023.pdf"}
    assert all(r.file_type == "pdf" for r in results)
    assert await provider.search('"9876543210" filetype:xlsx') == []


async def test_exclusion_and_or_groups(provider: FixtureSearchProvider) -> None:
    results = await provider.search('"9876543210" -verma', max_results=50)
    assert results and all("verma" not in (r.title + r.snippet).lower() for r in results)
    assert "https://www.olx.example/item/maruti-swift-vdi-2014-dwarka-delhi-iid-1573349876" in urls(results)
    results = await provider.search('"9876543210" olx OR quikr', max_results=50)
    assert len(results) == 2 and all(("olx" in u or "quikr" in u) for u in urls(results))


async def test_ranking_and_max_results(provider: FixtureSearchProvider) -> None:
    results = await provider.search("Verma Agro Traders Lucknow", max_results=50)
    scores = [r.extra["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert [r.rank for r in results] == list(range(1, len(results) + 1))
    assert "verma agro" in results[0].title.lower()
    assert results[0].extra["score"] > results[-1].extra["score"]
    # plain terms are any-match: the noise page only contains "Lucknow" so it ranks last
    assert urls(results)[-1] == NOISE
    limited = await provider.search("Verma Agro Traders Lucknow", max_results=3)
    assert len(limited) == 3 and urls(limited) == urls(results)[:3]
    assert await provider.search("zzzz-no-such-term") == []
    assert await provider.search("") == []


def test_search_documents_dates_and_extra(fixture: dict) -> None:
    results = search_documents(fixture["documents"], '"Rohan Verma" site:eprocure.gov.example', 10)
    assert len(results) == 1
    r = results[0]
    assert r.published_at is not None and r.published_at.tzinfo is not None and r.published_at.year == 2024
    assert r.extra["content_type"] == "application/pdf" and r.file_type == "pdf"


def test_provider_metadata(provider: FixtureSearchProvider, tmp_path) -> None:
    assert provider.name == "fixture" and provider.requires == () and provider.available
    assert provider.telecom_results()[0].field == "carrier"
    missing = FixtureSearchProvider(provider.settings, provider.http, fixture_path=tmp_path / "nope.json")
    assert not missing.available and "nope.json" in missing.unavailable_reason()


# --------------------------------------------------------------------------- #
# Offline transport
# --------------------------------------------------------------------------- #
async def test_transport_serves_pages_pdfs_robots_and_404(settings: Settings, fixture: dict) -> None:
    http = HttpClient(settings, transport=build_offline_transport(fixture))
    page = await http.fetch_page(CONTACT)
    assert page.ok and page.status == 200 and page.content_type == "text/html"
    assert "98765 43210" in page.text and "<title>" in page.text
    assert page.robots_allowed is True

    blocked = await http.fetch_page(TOFLER)
    assert not blocked.ok and blocked.error == "robots_disallowed" and blocked.robots_allowed is False

    missing = await http.fetch_page("https://www.vermaagrotraders.example.in/nope.html")
    assert missing.status == 404 and not missing.ok

    pdf = await http.fetch_page(TENDER)
    assert pdf.ok and pdf.content_type == "application/pdf" and pdf.content.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(pdf.content))
    assert reader.metadata is not None and "Bid Document" in str(reader.metadata.title)
    assert "9876543210" in reader.pages[0].extract_text().replace("\n", " ")

    robots = await http.raw_get("https://www.tofler.example/robots.txt")
    assert robots.status_code == 200
    assert f"Disallow: {urlsplit(TOFLER).path}" in robots.text and "Allow: /" in robots.text
    assert (await http.raw_get("https://unknown.example/robots.txt")).status_code == 404
    await http.aclose()


def test_minimal_pdf_is_parseable() -> None:
    data = build_minimal_pdf("Hello (world) \\ 9876543210", title="T (1)")
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 1
    assert "9876543210" in reader.pages[0].extract_text()
    assert reader.metadata.title == "T (1)"


def test_transport_direct_handler(fixture: dict) -> None:
    transport = build_offline_transport(fixture)
    client = httpx.Client(transport=transport)
    r = client.get("https://www.vermaagrotraders.example.in/contact.html")
    assert r.status_code == 200 and "rohan@vermaagrotraders.example.in" in r.text
    assert client.get("https://www.vermaagrotraders.example.in/robots.txt").text.startswith("User-agent: *")
