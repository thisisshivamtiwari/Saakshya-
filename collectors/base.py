"""
Collector framework.

A collector is one investigation stage.  It receives a ``CollectorContext``
(configuration, normalised phone, provider registry, HTTP client, evidence
sink, query planner, search budget, progress callback) and writes everything
it discovers into the sink.  ``run_planned_queries`` is the shared helper
that executes ``PlannedQuery`` lists across every enabled search provider
with budget / information-gain control and snippet-level extraction.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Optional

from config.settings import Settings
from core.evidence import EvidenceSink
from core.http import HttpClient
from core.logging import get_logger
from core.models import (
    InvestigationConfig,
    Lead,
    NormalizedPhone,
    ProgressEvent,
    QueryRecord,
    SearchResult,
    Stage,
    StageResult,
    StageStatus,
    utcnow,
)
from core.registry import ProviderRegistry
from core.strategy import PlannedQuery, QueryPlanner, SearchBudget
from providers.base import SearchProvider

log = get_logger("collectors")

ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class CollectorContext:
    config: InvestigationConfig
    phone: NormalizedPhone
    registry: ProviderRegistry
    http: HttpClient
    sink: EvidenceSink
    planner: QueryPlanner
    budget: SearchBudget
    settings: Settings
    progress: ProgressCallback = lambda e: None  # noqa: E731
    snapshot_store: Optional[object] = None  # storage.snapshots.SnapshotStore (duck-typed to avoid import cycle)
    extras: dict = field(default_factory=dict)

    def emit(self, stage: Stage, status: StageStatus, message: str = "", **counts: int) -> None:
        try:
            self.progress(ProgressEvent(stage=stage, status=status, message=message, counts=dict(counts)))
        except Exception:  # pragma: no cover - progress callbacks must never break the engine
            log.debug("progress callback failed", stage=stage.value)


class BaseCollector(abc.ABC):
    name: str = "base"
    stage: Stage = Stage.SEARCH

    def enabled(self, ctx: CollectorContext) -> bool:  # noqa: D401
        return True

    async def execute(self, ctx: CollectorContext) -> StageResult:
        """Wrapper adding timing, progress events and error isolation around ``run``."""
        result = StageResult(stage=self.stage, started_at=utcnow())
        if not self.enabled(ctx):
            result.status = StageStatus.SKIPPED
            result.message = "disabled by configuration or depth"
            result.finished_at = utcnow()
            ctx.emit(self.stage, StageStatus.SKIPPED, result.message)
            return result
        ctx.emit(self.stage, StageStatus.RUNNING, f"{self.name} started")
        try:
            inner = await self.run(ctx)
            result.status = inner.status if inner.status != StageStatus.PENDING else StageStatus.DONE
            result.message = inner.message
            result.counts = inner.counts
            result.errors = inner.errors
        except Exception as exc:  # a failing stage must not abort the investigation
            log.error("stage failed", stage=self.stage.value, error=f"{type(exc).__name__}: {exc}")
            result.status = StageStatus.FAILED
            result.message = f"{type(exc).__name__}: {exc}"
            result.errors.append(result.message)
        result.finished_at = utcnow()
        ctx.emit(self.stage, result.status, result.message, **result.counts)
        return result

    @abc.abstractmethod
    async def run(self, ctx: CollectorContext) -> StageResult:
        ...


# --------------------------------------------------------------------------- #
# Shared query runner
# --------------------------------------------------------------------------- #


def _provider_supports(provider: SearchProvider, pq: PlannedQuery) -> bool:
    if pq.requires_site_operator and not provider.supports_site_operator:
        return False
    if pq.requires_filetype_operator and not provider.supports_filetype_operator:
        return False
    return True


async def _run_one(ctx: CollectorContext, provider: SearchProvider, pq: PlannedQuery, stage: Stage,
                   *, extract: bool, lead_depth: int) -> tuple[QueryRecord, list[SearchResult]]:
    from extractors.page_extractor import extract_from_text  # local import: keeps layering flexible

    record = QueryRecord(provider=provider.name, query=pq.query, stage=stage, purpose=pq.purpose, lead_id=pq.lead_id)
    cache_hits_before = ctx.http.cache_hits
    try:
        results = await provider.search(pq.query, max_results=ctx.config.results_per_query)
    except Exception as exc:  # providers should not raise, but be defensive
        record.error = f"{type(exc).__name__}: {exc}"
        results = []
        log.warning("search provider error", provider=provider.name, error=record.error)
    record.cached = ctx.http.cache_hits > cache_hits_before
    new = 0
    for r in results:
        if not r.url or not r.url.lower().startswith(("http://", "https://")):
            continue
        r.query = pq.query
        r.query_id = record.query_id
        r.provider = r.provider or provider.name
        src, is_new = ctx.sink.add_source(r.url, title=r.title, provider=provider.name, snippet=r.snippet,
                                          published_at=r.published_at, query_id=record.query_id,
                                          extra={"file_type": r.file_type} if r.file_type else None)
        new += int(is_new)
        ctx.sink.raw_results.append(r)
        if extract:
            text = f"{r.title}\n{r.snippet}"
            if r.extra.get("extra_snippets"):
                text += "\n" + str(r.extra["extra_snippets"])
            ext = extract_from_text(text, phone=ctx.phone, source=src, query_id=record.query_id, title=r.title,
                                    url=r.url, is_full_page=False, extractor_tag=f"snippet:{provider.name}")
            ctx.sink.add_findings(ext.findings)
            if ext.number_displayed:
                src.extra["number_displayed"] = True
            for lead in ext.leads:
                lead.depth = lead_depth
                ctx.sink.add_lead(lead)
    record.results_count = len(results)
    record.new_results_count = new
    return record, results


async def run_planned_queries(
    ctx: CollectorContext,
    queries: list[PlannedQuery],
    *,
    stage: Stage,
    extract: bool = True,
    lead_depth: int = 0,
    providers: Optional[list[SearchProvider]] = None,
) -> list[SearchResult]:
    """
    Execute planned queries across all enabled search providers.

    * respects the global query budget and per-branch information-gain cut-off;
    * skips providers that do not support the operators a query needs;
    * records one ``QueryRecord`` per (provider, query);
    * adds sources, findings and leads to the sink.
    """
    provs = providers if providers is not None else ctx.registry.search_providers()
    all_results: list[SearchResult] = []
    if not provs:
        ctx.sink.note_limitation(
            "No search provider is configured (set BRAVE_API_KEY, SERPAPI_KEY, SERPER_API_KEY or TAVILY_API_KEY); "
            "web discovery stages produced no results."
        )
        return all_results
    for pq in sorted(queries, key=lambda p: -p.priority):
        if not ctx.budget.can_run():
            ctx.sink.note_limitation(
                f"Query budget of {ctx.budget.max_queries} reached; remaining planned queries were not executed."
            )
            log.info("query budget exhausted", executed=ctx.budget.executed)
            break
        if ctx.budget.branch_exhausted(pq.branch):
            log.debug("branch exhausted; skipping query", branch=pq.branch)
            continue
        eligible = [p for p in provs if _provider_supports(p, pq)]
        if not eligible:
            continue
        outcomes = await asyncio.gather(
            *[_run_one(ctx, p, pq, stage, extract=extract, lead_depth=lead_depth) for p in eligible]
        )
        for record, results in outcomes:
            record.information_gain = ctx.budget.record(pq.branch, record.results_count, record.new_results_count)
            ctx.sink.add_query(record)
            all_results.extend(results)
            log.info("query executed", provider=record.provider, stage=stage.value, results=record.results_count,
                     new=record.new_results_count, gain=round(record.information_gain, 2), cached=record.cached)
            if not ctx.budget.can_run():
                break
    return all_results


def leads_snapshot(ctx: CollectorContext) -> list[Lead]:
    return list(ctx.sink.leads.values())
