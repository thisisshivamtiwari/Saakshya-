"""
Stage PAGE_FETCH: full-text extraction of the most promising surfaced pages.

Only URLs that a search provider returned are fetched (never crawled);
robots.txt, size and content-type limits are enforced by ``HttpClient``.
Platforms that require login or forbid automated access are skipped up
front.  Each fetched page yields our *own* excerpt (so the report does not
depend on provider snippets), a content hash, a page date when detectable and
full-page extraction into Findings / Leads.
"""

from __future__ import annotations

from collectors.base import BaseCollector, CollectorContext
from core.logging import get_logger
from core.models import DatePrecision, Source, SourceType, Stage, StageResult
from extractors.url_utils import file_type_from_url
from scoring.source_quality import QUALITY_RANK, platform_for_url

log = get_logger("collectors.page_fetch")

# Public pages on these platforms are served behind login walls / JS shells or their robots.txt
# forbids automated fetching.  We rely on search-engine snippets for them instead.
SKIP_PLATFORMS = {"facebook", "instagram", "linkedin", "x", "threads", "tiktok", "pinterest"}


def _fetch_priority(src: Source) -> tuple:
    return (
        not src.extra.get("number_displayed", False),
        -QUALITY_RANK[src.quality],
        src.source_type not in (SourceType.COMPANY_WEBSITE, SourceType.BUSINESS_DIRECTORY, SourceType.OTHER),
        len(src.referenced_by) * -1,
        src.url,
    )


class PageFetchCollector(BaseCollector):
    name = "page_fetch"
    stage = Stage.PAGE_FETCH

    def enabled(self, ctx: CollectorContext) -> bool:
        return ctx.config.enable_page_fetch and ctx.config.max_pages_to_fetch > 0

    async def run(self, ctx: CollectorContext) -> StageResult:
        from extractors.date_extractor import best_page_date
        from extractors.page_extractor import extract_from_text
        from extractors.text_utils import strip_html

        result = StageResult(stage=self.stage)
        candidates = [
            s for s in ctx.sink.sources.values()
            if not s.fetched and not file_type_from_url(s.url) and s.source_type != SourceType.DOCUMENT
            and platform_for_url(s.url) not in SKIP_PLATFORMS and s.url.lower().startswith(("http://", "https://"))
        ]
        candidates.sort(key=_fetch_priority)
        budget = ctx.config.max_pages_to_fetch
        fetched = blocked = failed = 0
        new_findings = 0
        for src in candidates[:budget]:
            res = await ctx.http.fetch_page(src.url)
            src.http_status = res.status or None
            src.robots_allowed = res.robots_allowed
            if res.error == "robots_disallowed":
                blocked += 1
                continue
            if not res.ok or not res.text:
                failed += 1
                continue
            fetched += 1
            page = strip_html(res.text)
            text = page.text[:200_000]
            src.fetched = True
            src.content_hash = res.content_hash
            if page.title and (not src.title or len(page.title) > len(src.title)):
                src.title = page.title[:300]
            if not src.published_at:
                dt, precision = best_page_date(text, page.meta)
                if dt:
                    src.published_at, src.date_precision = dt, precision
            before = len(ctx.sink.findings)
            ext = extract_from_text(text, phone=ctx.phone, source=src, title=src.title, url=src.url,
                                    is_full_page=True, extractor_tag="page")
            ctx.sink.add_findings(ext.findings)
            new_findings += len(ctx.sink.findings) - before
            for lead in ext.leads:
                ctx.sink.add_lead(lead)
            if ext.number_displayed:
                src.extra["number_displayed"] = True
            src.excerpt = _own_excerpt(text, ctx.phone.subscriber, ctx.settings.snapshot_excerpt_chars)
            src.extra["excerpt_origin"] = "own_fetch"
            if ctx.snapshot_store is not None:
                try:
                    ctx.snapshot_store.save(src, src.excerpt)  # type: ignore[attr-defined]
                except Exception as exc:  # pragma: no cover
                    log.debug("snapshot save failed", error=str(exc))
        if len(candidates) > budget:
            ctx.sink.note_limitation(
                f"{len(candidates) - budget} surfaced page(s) were not fetched because of the page-fetch budget "
                f"({budget}); their evidence relies on search-engine snippets only."
            )
        if blocked:
            ctx.sink.note_limitation(f"{blocked} page(s) were not fetched because robots.txt disallows automated access.")
        result.counts = {"fetched": fetched, "robots_blocked": blocked, "failed": failed, "new_findings": new_findings}
        result.message = f"{fetched} pages fetched, {blocked} blocked by robots.txt, {new_findings} new findings"
        return result


def _own_excerpt(text: str, subscriber: str, max_chars: int) -> str:
    """Excerpt centred on the first occurrence of the subject number (digit-aware), bounded to max_chars."""
    if not text:
        return ""
    compact = "".join(ch for ch in text if ch.isdigit())
    idx = text.find(subscriber)
    if idx < 0 and subscriber and subscriber in compact:
        # find approximate position by walking the digits
        count, pos = 0, 0
        target = compact.find(subscriber)
        for pos, ch in enumerate(text):
            if ch.isdigit():
                if count == target:
                    idx = pos
                    break
                count += 1
    if idx < 0:
        return " ".join(text[:max_chars].split())
    half = max_chars // 2
    start, end = max(0, idx - half), min(len(text), idx + half)
    return " ".join(text[start:end].split())[:max_chars]


class DatePrecisionHelper:  # pragma: no cover - re-export for type checkers
    DAY = DatePrecision.DAY
