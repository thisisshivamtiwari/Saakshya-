"""
TinEye reverse image search - PAID OPTIONAL PROVIDER.

Source: https://tineye.com/rest/ (official REST API; documentation requires JavaScript/login, so the
request shape below follows TinEye's published client libraries, pytineye/tineye-api: GET
https://api.tineye.com/rest/search/?url=<image_url>&limit=&offset=&sort=&order= with the key in the
``x-api-key`` header).  Pricing is per search bundle (see https://tineye.com/rest/ - not verified here).
Only PUBLIC image URLs that appeared in public sources are submitted.  No facial recognition.
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from core.http import RateLimitedError
from core.models import SearchResult
from providers.base import ImageSearchProvider

ENDPOINT = "https://api.tineye.com/rest/search/"


class TinEyeProvider(ImageSearchProvider):
    name: ClassVar[str] = "tineye"
    requires: ClassVar[tuple[str, ...]] = ("tineye_api_key",)
    paid: ClassVar[bool] = True
    docs_url: ClassVar[str] = "https://tineye.com/rest/"
    rate_per_second: ClassVar[float] = 1.0

    async def reverse_search(self, image_url: str, *, max_results: int = 10) -> list[SearchResult]:
        if not self.available or not image_url.lower().startswith(("http://", "https://")):
            return []
        headers = {"x-api-key": self.secret("tineye_api_key")}
        params = {"url": image_url, "limit": max_results, "offset": 0, "sort": "score", "order": "desc"}
        self.calls += 1
        try:
            payload, _ = await self.http.get_json(ENDPOINT, params=params, headers=headers, namespace="tineye",
                                                  rate=self.rate_per_second)
        except RateLimitedError:
            self.errors.append("rate limited")
            return []
        except httpx.HTTPStatusError as exc:
            self.errors.append(f"http {exc.response.status_code}")
            self.log.warning("tineye error", status=exc.response.status_code)
            return []
        except (httpx.HTTPError, ValueError) as exc:
            self.errors.append(type(exc).__name__)
            return []
        out: list[SearchResult] = []
        matches = ((payload or {}).get("results") or {}).get("matches") or []
        for i, m in enumerate(matches):
            for bl in m.get("backlinks") or []:
                page = bl.get("backlink") or bl.get("url")
                if not page:
                    continue
                out.append(SearchResult(url=page, title=m.get("domain") or "", snippet=f"image match score {m.get('score')}",
                                        provider=self.name, rank=i + 1,
                                        extra={"image_url": m.get("image_url"), "crawl_date": bl.get("crawl_date"),
                                               "score": m.get("score")}))
                if len(out) >= max_results:
                    return out
        return out
