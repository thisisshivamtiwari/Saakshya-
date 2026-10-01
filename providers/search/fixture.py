"""
Offline fixture search provider (demo + tests).

Source   : ``fixtures/synthetic_investigation.json`` - an ENTIRELY FICTIONAL scenario for the
           placeholder number +91 98765 43210.  Every host uses the reserved ``.example`` TLD so
           nothing real is ever referenced (``scoring.source_quality.demo_host_alias`` maps them
           to real domain names for classification only).
Auth     : none.   Pricing: free (local file).   Network: none.
Stored   : only ``SearchResult`` objects built from the fixture; nothing is cached.

Public API
----------
* ``FixtureSearchProvider(settings=None, http=None, fixture_path=None)`` - a ``SearchProvider``
  running a tiny local search engine over ``fixture["documents"]``.  It honours quoted phrases
  (digit-aware, so ``"98765 43210"``, ``"+919876543210"`` and ``"09876543210"`` all hit the same
  page while a number that merely shares 8 digits does not), ``site:<host>``, ``filetype:<ext>``,
  ``-term`` exclusion, ``a OR b`` groups and plain terms (any-match, ranked by hit count).
* ``search_documents(documents, query, max_results)`` - the engine itself.
* ``load_fixture(path)`` - read and minimally validate a fixture file.
* ``build_offline_transport(fixture)`` - ``httpx.MockTransport`` serving every document's ``text``
  at its exact URL (HTML wrapped in a minimal page, PDFs rendered as a tiny valid PDF), a
  ``robots.txt`` per known host (``Disallow`` for documents flagged ``robots_disallow``) and 404
  for anything else, so ``HttpClient.fetch_page`` works with no network.
"""

from __future__ import annotations

import html
import json
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Optional
from urllib.parse import urlsplit

import httpx

from config.settings import Settings
from core.http import HttpClient
from core.models import ProviderState, SearchResult, TelecomResult
from extractors.url_utils import file_type_from_url, host_of
from providers.base import SearchProvider

DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_investigation.json"
REQUIRED_DOCUMENT_FIELDS = ("url", "title", "snippet", "text", "content_type", "published_at", "file_type")

_TOKEN_RE = re.compile(r'(-?)"([^"]*)"|(\S+)')
_NUMBER_RUN_RE = re.compile(r"[+\d][\d\-().\s]*\d")


# --------------------------------------------------------------------------- #
# Fixture loading
# --------------------------------------------------------------------------- #
def load_fixture(path: str | Path | None = None) -> dict[str, Any]:
    """Load a fixture JSON file and check the minimum structure (raises ValueError if malformed)."""
    p = Path(path) if path else DEFAULT_FIXTURE_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        raise ValueError(f"fixture {p} must be an object with a 'documents' list")
    for i, doc in enumerate(data["documents"]):
        missing = [k for k in REQUIRED_DOCUMENT_FIELDS if k not in doc]
        if missing:
            raise ValueError(f"fixture document #{i} is missing fields: {', '.join(missing)}")
    return data


def parse_iso_date(value: Any) -> Optional[datetime]:
    """'2023-04-01' / '2023-04-01T10:00:00Z' -> aware UTC datetime; None when absent or invalid."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Query parsing
# --------------------------------------------------------------------------- #
@dataclass
class ParsedQuery:
    phrases: list[str] = field(default_factory=list)
    excluded_phrases: list[str] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)
    filetypes: list[str] = field(default_factory=list)
    excluded_terms: list[str] = field(default_factory=list)
    groups: list[list[str]] = field(default_factory=list)  # each group = OR alternatives


def parse_query(query: str) -> ParsedQuery:
    pq = ParsedQuery()
    pending_or = False
    for m in _TOKEN_RE.finditer(query or ""):
        neg, phrase, word = m.groups()
        if phrase is not None:
            if phrase.strip():
                (pq.excluded_phrases if neg else pq.phrases).append(phrase.strip())
            pending_or = False
            continue
        if word == "OR":
            pending_or = True
            continue
        low = word.lower()
        if low.startswith("site:") and len(low) > 5:
            pq.sites.append(low[5:].strip('"').lstrip("*.").lstrip("."))
        elif (low.startswith("filetype:") or low.startswith("ext:")) and ":" in low:
            pq.filetypes.append(low.split(":", 1)[1].strip('"').lstrip("."))
        elif low.startswith("-") and len(low) > 1:
            pq.excluded_terms.append(low[1:])
        elif pending_or and pq.groups:
            pq.groups[-1].append(low)
        else:
            pq.groups.append([low])
        pending_or = False
    return pq


# --------------------------------------------------------------------------- #
# Digit-aware matching
# --------------------------------------------------------------------------- #
def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def _is_numeric(term: str) -> bool:
    d = _digits(term)
    compact = re.sub(r"[\s\-().+]", "", term)
    return len(d) >= 7 and compact and len(d) >= 0.6 * len(compact)


def _subscriber(digits: str) -> str:
    for prefix in ("0091", "091", "91", "0"):
        if digits.startswith(prefix) and len(digits) - len(prefix) == 10:
            return digits[len(prefix):]
    return digits


def number_present(haystack: str, term: str) -> bool:
    """
    True if the phone number written in ``term`` appears in ``haystack`` in any common Indian
    spelling.  A 10-digit subscriber number must appear in full (with an optional 0 / 91 / +91
    prefix); it never matches a different number that merely shares a digit prefix.
    """
    digits = _digits(term)
    sub = _subscriber(digits)
    if len(sub) == 10:
        allowed = {sub, "0" + sub, "91" + sub, "091" + sub, "0091" + sub}
    else:
        allowed = {digits}
    for run in _NUMBER_RUN_RE.finditer(haystack):
        parts = [p for p in (_digits(x) for x in run.group(0).split()) if p]
        for i in range(len(parts)):
            acc = ""
            for j in range(i, min(len(parts), i + 4)):
                acc += parts[j]
                if acc in allowed:
                    return True
                if len(acc) > 14:
                    break
    return False


def _norm_ws(s: str) -> str:
    return " ".join(s.lower().split())


def _phrase_hits(hay: str, phrase: str) -> int:
    if _is_numeric(phrase):
        return 1 if number_present(hay, phrase) else 0
    return _norm_ws(hay).count(_norm_ws(phrase))


def _term_hits(hay: str, term: str) -> int:
    if _is_numeric(term):
        return 1 if number_present(hay, term) else 0
    return len(re.findall(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", hay.lower()))


def _host_matches(host: str, site: str) -> bool:
    """Match ``site:`` filters; synthetic ``.example`` hosts also match their real-world alias
    (``www.olx.example`` satisfies ``site:olx.in``) so the planner's dorks work offline."""
    from scoring.source_quality import demo_host_alias

    host, site = host.lower(), site.lower()
    if site.startswith("www."):
        site = site[4:]
    candidates = {host}
    alias_host, alias_domain = demo_host_alias(host)
    candidates.update({alias_host, alias_domain})
    return any(h == site or h.endswith("." + site) for h in candidates if h)


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
def score_document(doc: dict[str, Any], pq: ParsedQuery) -> int:
    """Return a relevance score > 0 when the document matches the parsed query, else 0."""
    url = str(doc.get("url", ""))
    hay = " ".join(str(doc.get(k, "") or "") for k in ("url", "title", "snippet", "text"))
    if pq.sites and not any(_host_matches(host_of(url), s) for s in pq.sites):
        return 0
    if pq.filetypes:
        ftype = (str(doc.get("file_type") or "") or file_type_from_url(url)).lower()
        if ftype not in pq.filetypes:
            return 0
    if any(_phrase_hits(hay, p) for p in pq.excluded_phrases):
        return 0
    if any(_term_hits(hay, t) for t in pq.excluded_terms):
        return 0
    score = 0
    for phrase in pq.phrases:
        hits = _phrase_hits(hay, phrase)
        if not hits:
            return 0
        score += 10 + min(hits, 5)
    if pq.groups:
        matched_any = False
        for group in pq.groups:
            best = max((min(_term_hits(hay, t), 5) for t in group), default=0)
            if best:
                matched_any = True
                score += best + (2 if any(t in str(doc.get("title", "")).lower() for t in group) else 0)
        if not matched_any:
            return 0
    if not pq.phrases and not pq.groups:
        # filter-only query (e.g. "site:x.example") matches everything that passed the filters;
        # a query with no terms and no filters at all matches nothing
        score = 1 if (pq.sites or pq.filetypes) else 0
    return score


def search_documents(documents: list[dict[str, Any]], query: str, max_results: int = 10,
                     *, provider: str = "fixture") -> list[SearchResult]:
    pq = parse_query(query)
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for idx, doc in enumerate(documents):
        s = score_document(doc, pq)
        if s > 0:
            scored.append((s, idx, doc))
    scored.sort(key=lambda t: (-t[0], t[1]))
    results: list[SearchResult] = []
    for rank, (s, _idx, doc) in enumerate(scored[: max(0, int(max_results))], start=1):
        url = str(doc["url"])
        results.append(SearchResult(
            url=url, title=str(doc.get("title", "")), snippet=str(doc.get("snippet", "")),
            provider=provider, query=query, rank=rank, published_at=parse_iso_date(doc.get("published_at")),
            file_type=str(doc.get("file_type") or file_type_from_url(url)),
            extra={"score": s, "content_type": doc.get("content_type", "text/html"), "fixture": True},
        ))
    return results


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class FixtureSearchProvider(SearchProvider):
    name: ClassVar[str] = "fixture"
    requires: ClassVar[tuple[str, ...]] = ()
    paid: ClassVar[bool] = False
    docs_url: ClassVar[str] = "docs/ARCHITECTURE.md#9-offline-fixture-demo--tests"
    rate_per_second: ClassVar[float] = 1000.0
    max_results_per_call: ClassVar[int] = 50

    def __init__(self, settings: Optional[Settings] = None, http: Optional[HttpClient] = None,
                 fixture_path: str | Path | None = None) -> None:
        super().__init__(settings, http)
        self.fixture_path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE_PATH
        self._fixture: Optional[dict[str, Any]] = None

    @property
    def fixture(self) -> dict[str, Any]:
        if self._fixture is None:
            self._fixture = load_fixture(self.fixture_path)
        return self._fixture

    @property
    def documents(self) -> list[dict[str, Any]]:
        return list(self.fixture.get("documents", []))

    def extra_state_check(self) -> ProviderState:
        return ProviderState.AVAILABLE if self.fixture_path.is_file() else ProviderState.NOT_INSTALLED

    def unavailable_reason(self) -> str:
        if self.state == ProviderState.NOT_INSTALLED:
            return f"fixture file not found: {self.fixture_path}"
        return super().unavailable_reason()

    def telecom_results(self) -> list[TelecomResult]:
        """Fixture telecom hints (labelled as fixture data; never identity claims)."""
        out: list[TelecomResult] = []
        for row in self.fixture.get("telecom", []):
            out.append(TelecomResult(provider=str(row.get("provider", self.name)), field=str(row.get("field", "")),
                                     value=str(row.get("value", "")), confidence=float(row.get("confidence", 0.5)),
                                     note="synthetic fixture value"))
        return out

    async def search(self, query: str, *, max_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        self.calls += 1
        try:
            docs = self.documents
        except (OSError, ValueError) as exc:
            self.log.warning("fixture unavailable", error=type(exc).__name__)
            self.errors.append(f"{self.name}: {type(exc).__name__}")
            return []
        return search_documents(docs, query, max_results, provider=self.name)


# --------------------------------------------------------------------------- #
# Offline HTTP transport
# --------------------------------------------------------------------------- #
def _pdf_escape(s: str) -> str:
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_minimal_pdf(text: str, title: str = "") -> bytes:
    """Hand-assemble a small, valid single-page PDF whose content stream draws ``text`` in Helvetica."""
    lines = textwrap.wrap(text, width=95)[:60] or [""]
    body = "BT /F1 9 Tf 36 800 Td 11 TL " + "".join(f"({_pdf_escape(ln)}) Tj T* " for ln in lines) + "ET"
    stream = body.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Title (" + _pdf_escape(title).encode("latin-1") + b") /Producer (fixture) >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for n, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


def _url_key(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return f"{(parts.hostname or '').lower()}{path}?{parts.query}" if parts.query else f"{(parts.hostname or '').lower()}{path}"


def build_offline_transport(fixture: dict[str, Any]) -> httpx.MockTransport:
    pages: dict[str, dict[str, Any]] = {}
    hosts: set[str] = set()
    disallow: dict[str, list[str]] = {}
    for doc in fixture.get("documents", []):
        url = str(doc["url"])
        pages[_url_key(url)] = doc
        host = host_of(url)
        hosts.add(host)
        if doc.get("robots_disallow"):
            disallow.setdefault(host, []).append(urlsplit(url).path or "/")

    def handler(request: httpx.Request) -> httpx.Response:
        host = (request.url.host or "").lower()
        if request.url.path == "/robots.txt":
            if host not in hosts:
                return httpx.Response(404, text="not found")
            lines = ["User-agent: *"] + [f"Disallow: {p}" for p in disallow.get(host, [])] + ["Allow: /"]
            return httpx.Response(200, text="\n".join(lines) + "\n", headers={"content-type": "text/plain"})
        doc = pages.get(_url_key(str(request.url)))
        if doc is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/plain"})
        ctype = str(doc.get("content_type") or "text/html")
        text, title = str(doc.get("text", "")), str(doc.get("title", ""))
        if ctype.startswith("application/pdf"):
            return httpx.Response(200, content=build_minimal_pdf(text, title), headers={"content-type": ctype})
        if ctype.startswith("text/html"):
            page = (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
                    f"</head><body><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p></body></html>")
            return httpx.Response(200, content=page.encode("utf-8"), headers={"content-type": f"{ctype}; charset=utf-8"})
        return httpx.Response(200, content=text.encode("utf-8"), headers={"content-type": f"{ctype}; charset=utf-8"})

    return httpx.MockTransport(handler)
