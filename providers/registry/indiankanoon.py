"""
Indian Kanoon API - full-text search over public Indian judgments and orders.

Source: https://api.indiankanoon.org/documentation/ (verified 2026-09-08)
Endpoint: POST https://api.indiankanoon.org/search/?formInput=<query>&pagenum=<n>   (pagenum starts at 0)
Auth: header ``Authorization: Token <token>``.  PAID OPTIONAL PROVIDER (per-request pricing; documentation
states "You will be charged for only the number of pages that are returned").
Response: {"docs": [{"tid", "title", "headline", "docsource", "publishdate"?}], "found": "...", "categories": [...]}
Public judgments are A-quality primary sources; phone numbers occasionally appear in witness/party details.
We only run the exact-number query; we never download whole judgments unless surfaced and robots-allowed.
"""

from __future__ import annotations

from typing import ClassVar, Optional

import httpx

from core.http import RateLimitedError
from core.models import SearchResult
from extractors.date_extractor import parse_iso
from providers.base import RegistryProvider

ENDPOINT = "https://api.indiankanoon.org/search/"


class IndianKanoonProvider(RegistryProvider):
    name: ClassVar[str] = "indiankanoon"
    requires: ClassVar[tuple[str, ...]] = ("indiankanoon_api_token",)
    paid: ClassVar[bool] = True
    docs_url: ClassVar[str] = "https://api.indiankanoon.org/documentation/"
    rate_per_second: ClassVar[float] = 1.0

    async def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]:
        if not self.available:
            return []
        headers = {"Authorization": f"Token {self.secret('indiankanoon_api_token')}", "Accept": "application/json"}
        params = {"formInput": query, "pagenum": 0}
        self.calls += 1
        try:
            payload, _ = await self.http.get_json(ENDPOINT, method="POST", params=params, headers=headers,
                                                  namespace="indiankanoon", rate=self.rate_per_second)
        except RateLimitedError:
            self.errors.append("rate limited")
            return []
        except httpx.HTTPStatusError as exc:
            self.errors.append(f"http {exc.response.status_code}")
            self.log.warning("indiankanoon error", status=exc.response.status_code)
            return []
        except (httpx.HTTPError, ValueError) as exc:
            self.errors.append(type(exc).__name__)
            return []
        out: list[SearchResult] = []
        for i, d in enumerate((payload or {}).get("docs", []) or []):
            tid = d.get("tid")
            if not tid:
                continue
            headline = _strip_tags(str(d.get("headline") or ""))
            published: Optional[object] = parse_iso(str(d.get("publishdate") or "")) if d.get("publishdate") else None
            out.append(SearchResult(
                url=f"https://indiankanoon.org/doc/{tid}/", title=_strip_tags(str(d.get("title") or "")),
                snippet=headline, provider=self.name, rank=i + 1, published_at=published,  # type: ignore[arg-type]
                extra={"docsource": d.get("docsource", ""), "tid": tid},
            ))
            if len(out) >= max_results:
                break
        return out


def _strip_tags(s: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", s).replace("&amp;", "&").strip()
