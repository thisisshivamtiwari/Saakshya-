"""
Brave Search API provider.

Source   : Brave Web Search API - GET https://api.search.brave.com/res/v1/web/search
Auth     : ``X-Subscription-Token`` header (setting ``BRAVE_API_KEY``).  The key travels only in
           the request header; ``HttpClient.get_json`` keys its cache on URL + params, so the key
           never reaches the cache database or the logs.
Pricing  : as of 2026-09 every Brave Search API account receives a free USD 5 credit per month
           (pay-as-you-go beyond that, roughly USD 5 per 1,000 requests); the free tier is limited
           to 1 request per second, hence ``rate_per_second = 1.0``.  ``paid = False``.
Docs     : https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
           Parameter names (q, count<=20, offset 0-9, country, search_lang, safesearch,
           extra_snippets boolean, freshness) and response fields (web/news/discussions ->
           results[].url/title/description/page_age/extra_snippets) verified against the docs.
Stored   : only ``SearchResult`` fields (url, title, description as snippet, extra snippets,
           page_age, result section).  The raw JSON payload is cached by the shared HttpClient.
Operators: supports ``site:``, ``filetype:`` and quoted phrases natively.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

import httpx

from core.http import RateLimitedError
from core.models import SearchResult
from extractors.url_utils import file_type_from_url
from providers.base import SearchProvider

_SECTIONS = ("web", "news", "discussions")


def _parse_date(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class BraveSearchProvider(SearchProvider):
    name: ClassVar[str] = "brave"
    requires: ClassVar[tuple[str, ...]] = ("brave_api_key",)
    paid: ClassVar[bool] = False
    docs_url: ClassVar[str] = "https://api-dashboard.search.brave.com/app/documentation/web-search/get-started"
    rate_per_second: ClassVar[float] = 1.0
    max_results_per_call: ClassVar[int] = 20

    ENDPOINT: ClassVar[str] = "https://api.search.brave.com/res/v1/web/search"

    async def search(self, query: str, *, max_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        if not self.available:
            self.errors.append(f"{self.name}: {self.unavailable_reason()}")
            return []
        count = max(1, min(int(max_results), self.max_results_per_call))
        params: dict[str, Any] = {
            "q": query,
            "count": count,
            "offset": max(0, min(int(kwargs.get("offset", 0) or 0), 9)),
            "country": kwargs.get("country", "IN"),
            "search_lang": kwargs.get("search_lang", "en"),
            "safesearch": "off",
            "extra_snippets": "true",
        }
        if kwargs.get("freshness"):
            params["freshness"] = str(kwargs["freshness"])
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.secret("brave_api_key"),
        }
        self.calls += 1
        try:
            payload, cached = await self.http.get_json(
                self.ENDPOINT, params=params, headers=headers, namespace="brave",
                rate=self.rate_per_second, cache_ttl=self.default_cache_ttl,
            )
        except RateLimitedError:
            return self._fail("rate limited (429 persisted)")
        except httpx.HTTPStatusError as exc:
            return self._fail(f"HTTP {exc.response.status_code}")
        except (httpx.HTTPError, ValueError) as exc:
            return self._fail(f"{type(exc).__name__}")
        results = self._parse(payload, query)[:max_results]
        self.log.info("brave search done", results=len(results), cached=cached)
        return results

    def _fail(self, reason: str) -> list[SearchResult]:
        self.log.warning("brave search failed", reason=reason)
        self.errors.append(f"{self.name}: {reason}")
        return []

    def _parse(self, payload: Any, query: str) -> list[SearchResult]:
        out: list[SearchResult] = []
        if not isinstance(payload, dict):
            return out
        seen: set[str] = set()
        for section in _SECTIONS:
            block = payload.get(section) or {}
            items = block.get("results") if isinstance(block, dict) else None
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                snippet = str(item.get("description") or "")
                extras = [str(s) for s in (item.get("extra_snippets") or []) if s]
                extra: dict[str, Any] = {"section": section}
                if extras:
                    extra["extra_snippets"] = " | ".join(extras)
                if item.get("age"):
                    extra["age"] = str(item["age"])
                out.append(SearchResult(
                    url=url, title=str(item.get("title") or ""), snippet=snippet, provider=self.name,
                    query=query, rank=len(out) + 1, published_at=_parse_date(item.get("page_age")),
                    file_type=file_type_from_url(url), extra=extra,
                ))
        return out
