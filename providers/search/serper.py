"""
Serper.dev Google-SERP provider (PAID after a free allowance).

Source   : Serper - POST https://google.serper.dev/search with JSON body
           ``{"q", "gl": "in", "hl": "en", "num", "page"}``.
Auth     : ``X-API-KEY`` header (setting ``SERPER_API_KEY``).  Header only - the shared
           ``HttpClient.get_json`` cache key is URL + params + body, so the key is never cached
           or logged.
Pricing  : as of 2026-09 new accounts get 2,500 free queries; afterwards credits are bought in
           packs (about USD 50 per 50,000 queries).  ``paid = True``.
Docs     : https://serper.dev/  (API playground and reference)
Stored   : only ``SearchResult`` fields (url, title, snippet, position, date when present).
Operators: Google syntax - ``site:``, ``filetype:`` and quoted phrases are supported.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

import httpx

from core.http import RateLimitedError
from core.models import SearchResult
from extractors.url_utils import file_type_from_url
from providers.base import SearchProvider

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


class SerperSearchProvider(SearchProvider):
    name: ClassVar[str] = "serper"
    requires: ClassVar[tuple[str, ...]] = ("serper_api_key",)
    paid: ClassVar[bool] = True
    docs_url: ClassVar[str] = "https://serper.dev/"
    rate_per_second: ClassVar[float] = 2.0
    max_results_per_call: ClassVar[int] = 100

    ENDPOINT: ClassVar[str] = "https://google.serper.dev/search"

    async def search(self, query: str, *, max_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        if not self.available:
            self.errors.append(f"{self.name}: {self.unavailable_reason()}")
            return []
        num = max(1, min(int(max_results), self.max_results_per_call))
        body: dict[str, Any] = {
            "q": query,
            "gl": kwargs.get("gl", "in"),
            "hl": kwargs.get("hl", "en"),
            "num": num,
            "page": max(1, int(kwargs.get("page", 1) or 1)),
        }
        headers = {"X-API-KEY": self.secret("serper_api_key"), "Content-Type": "application/json"}
        self.calls += 1
        try:
            payload, cached = await self.http.get_json(
                self.ENDPOINT, method="POST", json_body=body, headers=headers, namespace="serper",
                rate=self.rate_per_second, cache_ttl=self.default_cache_ttl,
            )
        except RateLimitedError:
            return self._fail("rate limited (429 persisted)")
        except httpx.HTTPStatusError as exc:
            return self._fail(f"HTTP {exc.response.status_code}")
        except (httpx.HTTPError, ValueError) as exc:
            return self._fail(type(exc).__name__)
        results = self._parse(payload, query)[:max_results]
        self.log.info("serper search done", results=len(results), cached=cached)
        return results

    def _fail(self, reason: str) -> list[SearchResult]:
        self.log.warning("serper search failed", reason=reason)
        self.errors.append(f"{self.name}: {reason}")
        return []

    def _parse(self, payload: Any, query: str) -> list[SearchResult]:
        out: list[SearchResult] = []
        items = payload.get("organic") if isinstance(payload, dict) else None
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            if not url:
                continue
            extra: dict[str, Any] = {}
            if item.get("position") is not None:
                extra["position"] = item["position"]
            if item.get("date"):
                extra["date_raw"] = str(item["date"])
            if item.get("sitelinks"):
                extra["sitelinks"] = [str(s.get("link", "")) for s in item["sitelinks"] if isinstance(s, dict)]
            out.append(SearchResult(
                url=url, title=str(item.get("title") or ""), snippet=str(item.get("snippet") or ""),
                provider=self.name, query=query, rank=len(out) + 1, published_at=_parse_date(item.get("date")),
                file_type=file_type_from_url(url), extra=extra,
            ))
        return out
