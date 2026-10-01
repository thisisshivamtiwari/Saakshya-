"""Stage SEARCH: exact-match phone discovery across search providers (strategy stage 1)."""

from __future__ import annotations

from collectors.base import BaseCollector, CollectorContext, run_planned_queries
from core.models import Stage, StageResult


class SearchCollector(BaseCollector):
    name = "search"
    stage = Stage.SEARCH

    async def run(self, ctx: CollectorContext) -> StageResult:
        before = ctx.sink.counts()
        queries = ctx.planner.exact_match_queries() + ctx.planner.india_queries()
        await run_planned_queries(ctx, queries, stage=self.stage)
        after = ctx.sink.counts()
        result = StageResult(stage=self.stage)
        result.counts = {
            "queries": after["queries"] - before["queries"],
            "sources": after["sources"] - before["sources"],
            "findings": after["findings"] - before["findings"],
            "leads": after["leads"] - before["leads"],
        }
        result.message = (f"{result.counts['sources']} sources, {result.counts['findings']} findings, "
                          f"{result.counts['leads']} leads from {result.counts['queries']} queries")
        return result
