"""
Tavily search provider.

Source   : Tavily Search API - POST https://api.tavily.com/search
Auth     : ``Authorization: Bearer <key>`` header (setting ``TAVILY_API_KEY``).  Header only, so
           the shared ``HttpClient.get_json`` cache (URL + params + body) never sees the key.
Pricing  : as of 2026-09 the free plan includes 1,000 API credits per month (a basic search costs
           1 credit); paid plans start at about USD 30/month.  ``paid = False``.
Docs     : https://docs.tavily.com/documentation/api-reference/endpoint/search
           Verified request fields: query, search_depth (basic), max_results (0-20), topic,
           include_domains (<=300), exclude_domains, country (lower-case country name, e.g.
           "india"), exact_match (boolean).  Verified result fields: title, url, content, score.
Stored   : only ``SearchResult`` fields (url, title, content as snippet, score in ``extra``).

Operator translation
--------------------
Tavily does not understand Google-style operators inside the query string:
* ``site:<domain>`` tokens are removed from the query and sent as ``include_domains``
  (``-site:<domain>`` becomes ``exclude_domains``), so ``supports_site_operator = True``;
* ``filetype:`` has no equivalent - ``supports_filetype_operator = False`` and such queries
  return ``[]`` so the collector skips them for this provider;
* a quoted phrase in the query enables ``exact_match``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

import httpx

from core.http import RateLimitedError
from core.models import SearchResult
from extractors.url_utils import file_type_from_url
from providers.base import SearchProvider

_SITE_RE = re.compile(r'(?:(?<=\s)|^)(-?)site:"?([^\s"]+)"?', re.IGNORECASE)
_FILETYPE_RE = re.compile(r"(?:(?<=\s)|^)-?(?:filetype|ext):\S+", re.IGNORECASE)


def _parse_date(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def translate_query(query: str) -> tuple[str, list[str], list[str], bool]:
    """Return (clean_query, include_domains, exclude_domains, has_filetype_operator)."""
    include: list[str] = []
    exclude: list[str] = []
    for neg, domain in _SITE_RE.findall(query):
        d = domain.lower().lstrip("*.").lstrip(".")
        if d.startswith("www."):
            d = d[4:]
        (exclude if neg else include).append(d)
    has_filetype = bool(_FILETYPE_RE.search(query))
    clean = _SITE_RE.sub("", query)
    clean = _FILETYPE_RE.sub("", clean)
    clean = " ".join(clean.split())
    return clean, include, exclude, has_filetype


class TavilySearchProvider(SearchProvider):
    name: ClassVar[str] = "tavily"
    requires: ClassVar[tuple[str, ...]] = ("tavily_api_key",)
    paid: ClassVar[bool] = False
    docs_url: ClassVar[str] = "https://docs.tavily.com/documentation/api-reference/endpoint/search"
    rate_per_second: ClassVar[float] = 1.0
    max_results_per_call: ClassVar[int] = 20
    supports_site_operator: ClassVar[bool] = True  # via include_domains translation
    supports_filetype_operator: ClassVar[bool] = False

    ENDPOINT: ClassVar[str] = "https://api.tavily.com/search"

    async def search(self, query: str, *, max_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        if not self.available:
            self.errors.append(f"{self.name}: {self.unavailable_reason()}")
            return []
        clean, include, exclude, has_filetype = translate_query(query)
        if has_filetype:
            self.log.debug("tavily cannot express filetype: operator; skipping query")
            return []
        if not clean:
            return []
        body: dict[str, Any] = {
            "query": clean,
            "search_depth": kwargs.get("search_depth", "basic"),
            "max_results": max(1, min(int(max_results), self.max_results_per_call)),
            "topic": "general",
            "country": kwargs.get("country", "india"),
        }
        if '"' in clean:
            body["exact_match"] = True
        if include:
            body["include_domains"] = include
        if exclude:
            body["exclude_domains"] = exclude
        headers = {"Authorization": f"Bearer {self.secret('tavily_api_key')}", "Content-Type": "application/json"}
        self.calls += 1
        try:
            payload, cached = await self.http.get_json(
                self.ENDPOINT, method="POST", json_body=body, headers=headers, namespace="tavily",
                rate=self.rate_per_second, cache_ttl=self.default_cache_ttl,
            )
        except RateLimitedError:
            return self._fail("rate limited (429 persisted)")
        except httpx.HTTPStatusError as exc:
            return self._fail(f"HTTP {exc.response.status_code}")
        except (httpx.HTTPError, ValueError) as exc:
            return self._fail(type(exc).__name__)
        results = self._parse(payload, query)[:max_results]
        self.log.info("tavily search done", results=len(results), cached=cached)
        return results

    def _fail(self, reason: str) -> list[SearchResult]:
        self.log.warning("tavily search failed", reason=reason)
        self.errors.append(f"{self.name}: {reason}")
        return []

    def _parse(self, payload: Any, query: str) -> list[SearchResult]:
        out: list[SearchResult] = []
        items = payload.get("results") if isinstance(payload, dict) else None
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            extra: dict[str, Any] = {}
            if item.get("score") is not None:
                try:
                    extra["score"] = float(item["score"])
                except (TypeError, ValueError):
                    pass
            out.append(SearchResult(
                url=url, title=str(item.get("title") or ""), snippet=str(item.get("content") or ""),
                provider=self.name, query=query, rank=len(out) + 1,
                published_at=_parse_date(item.get("published_date")), file_type=file_type_from_url(url),
                extra=extra,
            ))
        return out
