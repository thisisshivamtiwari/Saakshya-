"""
Google Custom Search JSON API provider (PAID, DEPRECATED - existing customers only).

DEPRECATION: Google Custom Search JSON API is closed to new customers and shuts down on
2027-01-01; this provider only works for existing customers who still hold a key + search
engine id (cx).  A warning is logged on first use.

Source   : GET https://customsearch.googleapis.com/customsearch/v1
Auth     : ``key`` and ``cx`` *query parameters* (settings ``GOOGLE_CSE_API_KEY`` and
           ``GOOGLE_CSE_CX``).
Pricing  : as of 2026-09 (existing customers) 100 queries/day free, then USD 5 per 1,000 queries,
           capped at 10,000 queries/day.  ``paid = True``.
Docs     : https://developers.google.com/custom-search/v1/overview

Cache / secret handling
-----------------------
Because the key is a query parameter, this provider does NOT go through
``HttpClient.get_json`` (whose cache key embeds the params).  Like ``providers.search.serpapi``
it calls ``HttpClient.request`` directly and caches a trimmed payload (``items`` only) under
``cache_key("google_cse", cx, q, num, start)``; the key never reaches the cache database, the
logs or ``self.errors``.

Stored   : only ``SearchResult`` fields (url, title, snippet, mime/fileFormat, pagemap dates).
Operators: ``site:``, ``filetype:`` and quoted phrases are supported; ``num`` <= 10 per call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

import httpx

from core.http import RateLimitedError
from core.models import ProviderState, SearchResult
from extractors.url_utils import file_type_from_url
from providers.base import SearchProvider
from storage.cache import cache_key

DEPRECATION_NOTICE = (
    "Google Custom Search JSON API is closed to new customers and shuts down 2027-01-01; "
    "only for existing customers"
)
_DATE_META_KEYS = ("article:published_time", "datepublished", "date", "og:updated_time", "pubdate")


def _parse_date(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class GoogleCSEProvider(SearchProvider):
    name: ClassVar[str] = "google_cse"
    requires: ClassVar[tuple[str, ...]] = ("google_cse_api_key", "google_cse_cx")
    paid: ClassVar[bool] = True
    deprecated: ClassVar[bool] = True
    docs_url: ClassVar[str] = "https://developers.google.com/custom-search/v1/overview"
    rate_per_second: ClassVar[float] = 1.0
    max_results_per_call: ClassVar[int] = 10

    ENDPOINT: ClassVar[str] = "https://customsearch.googleapis.com/customsearch/v1"
    _warned: ClassVar[bool] = False

    def unavailable_reason(self) -> str:
        base = super().unavailable_reason()
        if self.state == ProviderState.MISSING_KEY:
            return f"{base} (deprecated: {DEPRECATION_NOTICE})"
        return base

    async def search(self, query: str, *, max_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        if not self.available:
            self.errors.append(f"{self.name}: {self.unavailable_reason()}")
            return []
        if not GoogleCSEProvider._warned:
            self.log.warning(DEPRECATION_NOTICE)
            GoogleCSEProvider._warned = True
        num = max(1, min(int(max_results), self.max_results_per_call))
        start = max(1, int(kwargs.get("start", 1) or 1))
        cx = self.secret("google_cse_cx")
        key = cache_key("google_cse", cx, query, str(num), str(start))
        cache = self.http.cache
        entry = cache.get(key, max_age=self.default_cache_ttl) if cache is not None else None
        self.calls += 1
        if entry is not None:
            payload, cached = entry.payload, True
        else:
            params: dict[str, Any] = {"key": self.secret("google_cse_api_key"), "cx": cx, "q": query,
                                      "num": num, "start": start, "gl": kwargs.get("gl", "in")}
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
            payload = {"items": raw.get("items") or []}  # trimmed: never the key
            cached = False
            if cache is not None:
                cache.set(key, payload, url=self.ENDPOINT, query=query, status=response.status_code)
        results = self._parse(payload, query)[:max_results]
        self.log.info("google_cse search done", results=len(results), cached=cached)
        return results

    def _fail(self, reason: str) -> list[SearchResult]:
        self.log.warning("google_cse search failed", reason=reason)
        self.errors.append(f"{self.name}: {reason}")
        return []

    def _parse(self, payload: Any, query: str) -> list[SearchResult]:
        out: list[SearchResult] = []
        items = payload.get("items") if isinstance(payload, dict) else None
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            if not url:
                continue
            extra: dict[str, Any] = {}
            if item.get("mime"):
                extra["mime"] = str(item["mime"])
            if item.get("fileFormat"):
                extra["file_format"] = str(item["fileFormat"])
            published: Optional[datetime] = None
            pagemap = item.get("pagemap") if isinstance(item.get("pagemap"), dict) else {}
            for meta in pagemap.get("metatags") or []:
                if not isinstance(meta, dict):
                    continue
                for k in _DATE_META_KEYS:
                    published = published or _parse_date(meta.get(k))
            ftype = file_type_from_url(url) or ("pdf" if extra.get("mime") == "application/pdf" else "")
            out.append(SearchResult(
                url=url, title=str(item.get("title") or ""), snippet=str(item.get("snippet") or ""),
                provider=self.name, query=query, rank=len(out) + 1, published_at=published,
                file_type=ftype, extra=extra,
            ))
        return out
