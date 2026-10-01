"""
Google Lens / reverse image via SerpAPI - PAID OPTIONAL PROVIDER (shares SERPAPI_KEY).

Source: https://serpapi.com/google-lens-api  (engine=google_lens, url=<image_url>, country=in)
Response: visual_matches[] {title, link, source, thumbnail}.  Only public image URLs are submitted; results are
page URLs that show a visually similar image - never facial identification.
The API key is a query parameter, so responses are cached manually (the key never enters the cache DB).
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from core.http import RateLimitedError
from core.models import SearchResult
from providers.base import ImageSearchProvider
from storage.cache import cache_key

ENDPOINT = "https://serpapi.com/search.json"


class SerpApiLensProvider(ImageSearchProvider):
    name: ClassVar[str] = "serpapi_lens"
    requires: ClassVar[tuple[str, ...]] = ("serpapi_key",)
    paid: ClassVar[bool] = True
    docs_url: ClassVar[str] = "https://serpapi.com/google-lens-api"
    rate_per_second: ClassVar[float] = 1.0

    async def reverse_search(self, image_url: str, *, max_results: int = 10) -> list[SearchResult]:
        if not self.available or not image_url.lower().startswith(("http://", "https://")):
            return []
        key = cache_key("serpapi_lens", image_url)
        payload = None
        if self.http.cache is not None:
            entry = self.http.cache.get(key)
            if entry:
                payload = entry.payload
        if payload is None:
            params = {"engine": "google_lens", "url": image_url, "country": "in", "hl": "en",
                      "api_key": self.secret("serpapi_key")}
            self.calls += 1
            try:
                resp = await self.http.request("GET", ENDPOINT, params=params, rate=self.rate_per_second)
                resp.raise_for_status()
                payload = resp.json()
            except RateLimitedError:
                self.errors.append("rate limited")
                return []
            except httpx.HTTPStatusError as exc:
                self.errors.append(f"http {exc.response.status_code}")
                return []
            except (httpx.HTTPError, ValueError) as exc:
                self.errors.append(type(exc).__name__)
                return []
            payload = {"visual_matches": (payload or {}).get("visual_matches", [])}
            if self.http.cache is not None:
                self.http.cache.set(key, payload, url=ENDPOINT, query="google_lens")
        out: list[SearchResult] = []
        for i, m in enumerate(payload.get("visual_matches") or []):
            link = m.get("link")
            if not link:
                continue
            out.append(SearchResult(url=link, title=m.get("title") or "", snippet=m.get("source") or "",
                                    provider=self.name, rank=i + 1, extra={"thumbnail": m.get("thumbnail")}))
            if len(out) >= max_results:
                break
        return out
