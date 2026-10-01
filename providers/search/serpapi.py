"""
SerpApi search provider (PAID, optional).

Source   : SerpApi - GET https://serpapi.com/search.json (raw REST, no SDK).  Default engine is
           ``google`` localised to India (google_domain=google.co.in, gl=in, hl=en); ``bing`` and
           ``duckduckgo`` can be selected with ``engine=`` (constructor or ``search(..., engine=)``).
Auth     : ``api_key`` *query parameter* (setting ``SERPAPI_KEY``).
Pricing  : as of 2026-09 the free developer plan allows 250 searches/month; paid plans start at
           about USD 75/month for 5,000 searches.  ``paid = True``.
Docs     : https://serpapi.com/search-api

Cache / secret handling
-----------------------
``HttpClient.get_json`` builds its cache key from URL + params, which for SerpApi would write the
API key into the SQLite cache.  This provider therefore does NOT use ``get_json``: it calls
``HttpClient.request`` directly and caches a *trimmed* payload (``organic_results`` only) under a
key derived from ``(engine, query, num, start)`` via ``storage.cache.cache_key`` - the key never
reaches the cache database, the log, or ``self.errors`` (httpx error strings that embed the URL
are deliberately never logged).  The same pattern is used by ``providers.search.google_cse``.

Stored   : only ``SearchResult`` fields (url, title, snippet, position, date when present).
Operators: Google supports ``site:``, ``filetype:`` and quoted phrases.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

import httpx

from config.settings import Settings
from core.http import HttpClient, RateLimitedError
from core.models import SearchResult
from extractors.url_utils import file_type_from_url
from providers.base import SearchProvider
from storage.cache import cache_key

_ENGINE_LOCALE: dict[str, dict[str, str]] = {
    "google": {"google_domain": "google.co.in", "gl": "in", "hl": "en"},
    "bing": {"cc": "IN", "setlang": "en"},
    "duckduckgo": {"kl": "in-en"},
}
_DATE_FORMATS = ("%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d")


def _parse_date(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class SerpApiSearchProvider(SearchProvider):
    name: ClassVar[str] = "serpapi"
    requires: ClassVar[tuple[str, ...]] = ("serpapi_key",)
    paid: ClassVar[bool] = True
    docs_url: ClassVar[str] = "https://serpapi.com/search-api"
    rate_per_second: ClassVar[float] = 1.0
    max_results_per_call: ClassVar[int] = 100

    ENDPOINT: ClassVar[str] = "https://serpapi.com/search.json"

    def __init__(self, settings: Optional[Settings] = None, http: Optional[HttpClient] = None,
                 *, engine: str = "google") -> None:
        super().__init__(settings, http)
        self.engine = engine if engine in _ENGINE_LOCALE else "google"

    async def search(self, query: str, *, max_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        if not self.available:
            self.errors.append(f"{self.name}: {self.unavailable_reason()}")
            return []
        engine = str(kwargs.get("engine") or self.engine)
        if engine not in _ENGINE_LOCALE:
            engine = "google"
        num = max(1, min(int(max_results), self.max_results_per_call))
        start = max(0, int(kwargs.get("start", 0) or 0))
        key = cache_key("serpapi", engine, query, str(num), str(start))
        cache = self.http.cache
        entry = cache.get(key, max_age=self.default_cache_ttl) if cache is not None else None
        self.calls += 1
        if entry is not None:
            payload, cached = entry.payload, True
        else:
            params: dict[str, Any] = {"engine": engine, "q": query, "num": num, "start": start,
                                      **_ENGINE_LOCALE[engine], "api_key": self.secret("serpapi_key")}
            try:
                response = await self.http.request("GET", self.ENDPOINT, params=params, rate=self.rate_per_second)
                response.raise_for_status()
                raw = response.json()
            except RateLimitedError:
                return self._fail("rate limited (429 persisted)")
            except httpx.HTTPStatusError as exc:
                return self._fail(f"HTTP {exc.response.status_code}")
            except (httpx.HTTPError, ValueError) as exc:
                return self._fail(type(exc).__name__)
            if not isinstance(raw, dict):
                return self._fail("unexpected payload")
            if raw.get("error"):
                return self._fail(f"api error: {str(raw['error'])[:120]}")
            payload = {"organic_results": raw.get("organic_results") or []}  # trimmed: never the key
            cached = False
            if cache is not None:
                cache.set(key, payload, url=self.ENDPOINT, query=query, status=response.status_code)
        results = self._parse(payload, query, engine)[:max_results]
        self.log.info("serpapi search done", engine=engine, results=len(results), cached=cached)
        return results

    def _fail(self, reason: str) -> list[SearchResult]:
        self.log.warning("serpapi search failed", reason=reason)
        self.errors.append(f"{self.name}: {reason}")
        return []

    def _parse(self, payload: Any, query: str, engine: str) -> list[SearchResult]:
        out: list[SearchResult] = []
        items = payload.get("organic_results") if isinstance(payload, dict) else None
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            if not url:
                continue
            extra: dict[str, Any] = {"engine": engine}
            if item.get("position") is not None:
                extra["position"] = item["position"]
            if item.get("date"):
                extra["date_raw"] = str(item["date"])
            out.append(SearchResult(
                url=url, title=str(item.get("title") or ""), snippet=str(item.get("snippet") or ""),
                provider=self.name, query=query, rank=len(out) + 1, published_at=_parse_date(item.get("date")),
                file_type=file_type_from_url(url), extra=extra,
            ))
        return out
