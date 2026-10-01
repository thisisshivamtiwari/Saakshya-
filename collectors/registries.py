"""
Stage REGISTRIES: public government / court / company-record discovery.

Indian registries (MCA21, eCourts, GST, RERA ...) are mostly searchable by
name/ID only and are CAPTCHA-protected, so we reach them *indirectly*: via
search-engine ``site:`` dorks on their public pages and on aggregators of
official data, plus documented registry APIs (Indian Kanoon).  We never
submit registry search forms, never solve CAPTCHAs and never log in.
"""

from __future__ import annotations

from collectors.base import BaseCollector, CollectorContext, run_planned_queries
from core.logging import get_logger
from core.models import QueryRecord, Stage, StageResult

log = get_logger("collectors.registries")


class RegistryCollector(BaseCollector):
    name = "registries"
    stage = Stage.REGISTRIES

    def enabled(self, ctx: CollectorContext) -> bool:
        return ctx.config.enable_registries

    async def run(self, ctx: CollectorContext) -> StageResult:
        from extractors.page_extractor import extract_from_text

        result = StageResult(stage=self.stage)
        await run_planned_queries(ctx, ctx.planner.registry_queries(), stage=self.stage)

        api_results = 0
        for p in ctx.registry.registry_providers():
            for q in ctx.phone.quoted_variants[:2] or [f'"{ctx.phone.subscriber}"']:
                if not ctx.budget.can_run():
                    break
                record = QueryRecord(provider=p.name, query=q, stage=self.stage, purpose="registry api search")
                try:
                    results = await p.search(q, max_results=ctx.config.results_per_query)
                except Exception as exc:  # defensive
                    record.error = f"{type(exc).__name__}: {exc}"
                    results = []
                new = 0
                for r in results:
                    src, is_new = ctx.sink.add_source(r.url, title=r.title, provider=p.name, snippet=r.snippet,
                                                      published_at=r.published_at, query_id=record.query_id)
                    new += int(is_new)
                    ext = extract_from_text(f"{r.title}\n{r.snippet}", phone=ctx.phone, source=src,
                                            query_id=record.query_id, title=r.title, url=r.url,
                                            extractor_tag=f"registry:{p.name}")
                    ctx.sink.add_findings(ext.findings)
                    if ext.number_displayed:
                        src.extra["number_displayed"] = True
                    for lead in ext.leads:
                        ctx.sink.add_lead(lead)
                record.results_count, record.new_results_count = len(results), new
                record.information_gain = ctx.budget.record(f"registry-api:{p.name}", len(results), new)
                ctx.sink.add_query(record)
                api_results += len(results)
        registry_sources = [s for s in ctx.sink.sources.values()
                            if s.source_type.value in ("government_registry", "court_record", "tender")]
        result.counts = {"registry_sources": len(registry_sources), "api_results": api_results}
        result.message = f"{len(registry_sources)} public registry / court / tender sources"
        return result
