"""
Stage DOCUMENTS: public document discovery (spec section 13).

1. filetype: dorks for every configured search provider that supports them;
2. safe fetch of surfaced documents only (never crawled): robots.txt, size and
   content-type limits enforced by ``HttpClient.fetch_page``; parsed in-process
   with pure-Python parsers (pypdf / python-docx / openpyxl) - no macros, no
   external viewers;
3. document metadata + full-text extraction into Findings and ``Document``
   objects.
"""

from __future__ import annotations

from collectors.base import BaseCollector, CollectorContext, run_planned_queries
from core.logging import get_logger
from core.models import DatePrecision, Document, Source, SourceType, Stage, StageResult
from extractors.url_utils import file_type_from_url
from storage.cache import content_hash

log = get_logger("collectors.documents")

_BLOCKED_SCHEMES = ("ftp://", "file://", "data:")


def _is_document_source(src: Source) -> bool:
    if src.source_type == SourceType.DOCUMENT:
        return True
    if file_type_from_url(src.url):
        return True
    return bool(src.extra.get("file_type"))


class DocumentCollector(BaseCollector):
    name = "documents"
    stage = Stage.DOCUMENTS

    def enabled(self, ctx: CollectorContext) -> bool:
        return ctx.config.enable_documents

    async def run(self, ctx: CollectorContext) -> StageResult:
        from extractors.document_extractor import doc_type_from, extract_document
        from extractors.page_extractor import extract_from_text

        result = StageResult(stage=self.stage)
        await run_planned_queries(ctx, ctx.planner.document_queries(), stage=self.stage)

        candidates = [s for s in ctx.sink.sources.values() if _is_document_source(s) and not s.fetched]
        # prefer documents whose snippet already showed the number, then by quality
        candidates.sort(key=lambda s: (not s.extra.get("number_displayed", False), s.quality.value, s.url))
        budget = max(0, ctx.config.max_pages_to_fetch // 2) if ctx.config.enable_page_fetch else 0
        fetched = parsed = 0
        for src in candidates[:budget]:
            if src.url.lower().startswith(_BLOCKED_SCHEMES):
                continue
            res = await ctx.http.fetch_page(src.url)
            src.http_status = res.status or None
            src.robots_allowed = res.robots_allowed
            if not res.ok:
                log.info("document not fetched", domain=src.domain, reason=res.error or res.status)
                continue
            fetched += 1
            doc_text = extract_document(res.content, res.content_type, src.url)
            if doc_text.error and not doc_text.text:
                result.errors.append(f"{src.domain}: {doc_text.error}")
                continue
            parsed += 1
            src.fetched = True
            src.content_hash = res.content_hash or content_hash(res.content)
            if doc_text.title and not src.title:
                src.title = doc_text.title[:300]
            if doc_text.created and not src.published_at:
                src.published_at, src.date_precision = doc_text.created, DatePrecision.DAY
            text = doc_text.text[:200_000]
            ext = extract_from_text(text, phone=ctx.phone, source=src, title=src.title, url=src.url,
                                    is_full_page=True, extractor_tag="document")
            ctx.sink.add_findings(ext.findings)
            for lead in ext.leads:
                ctx.sink.add_lead(lead)
            if ext.number_displayed:
                src.extra["number_displayed"] = True
            src.excerpt = _excerpt(text, ctx.phone.subscriber) or src.excerpt
            doc = Document(
                title=src.title or doc_text.title, url=src.url,
                doc_type=doc_text.doc_type or doc_type_from(res.content_type, src.url),
                author=doc_text.author, organization=doc_text.organization, published_at=src.published_at,
                date_precision=src.date_precision, phones=sorted(set([ctx.phone.e164] if ext.number_displayed else [])
                                                                | set(ext.other_numbers)),
                emails=ext.emails, names=ext.names, addresses=ext.addresses, urls=[], fetched=True,
                content_hash=src.content_hash, source_id=src.source_id,
                finding_ids=[f.finding_id for f in ext.findings],
            )
            ctx.sink.documents.append(doc)
            if ctx.snapshot_store is not None:
                try:
                    ctx.snapshot_store.save(src, src.excerpt)  # type: ignore[attr-defined]
                except Exception as exc:  # pragma: no cover
                    log.debug("snapshot save failed", error=str(exc))
        # documents surfaced but not fetched still get a Document stub so the report lists them
        for src in candidates[budget:] + [s for s in candidates[:budget] if not s.fetched]:
            if any(d.source_id == src.source_id for d in ctx.sink.documents):
                continue
            ctx.sink.documents.append(Document(
                title=src.title, url=src.url, doc_type=file_type_from_url(src.url) or str(src.extra.get("file_type", "")),
                published_at=src.published_at, date_precision=src.date_precision, fetched=False,
                source_id=src.source_id, phones=[ctx.phone.e164] if src.extra.get("number_displayed") else [],
            ))
        if len(candidates) > budget and budget > 0:
            ctx.sink.note_limitation(
                f"{len(candidates) - budget} discovered document(s) were not downloaded because of the fetch budget."
            )
        result.counts = {"documents": len(ctx.sink.documents), "fetched": fetched, "parsed": parsed}
        result.message = f"{len(ctx.sink.documents)} documents ({parsed} parsed)"
        return result


def _excerpt(text: str, subscriber: str, radius: int = 300) -> str:
    if not text:
        return ""
    digits_only = "".join(ch for ch in text if ch.isdigit() or ch.isspace() or ch.isalpha() or ch in ".,:;@-/")
    idx = text.find(subscriber)
    if idx < 0 and subscriber:
        idx = digits_only.find(subscriber)
        base = digits_only
    else:
        base = text
    if idx < 0:
        return " ".join(text[:600].split())
    start, end = max(0, idx - radius), min(len(base), idx + len(subscriber) + radius)
    return " ".join(base[start:end].split())
