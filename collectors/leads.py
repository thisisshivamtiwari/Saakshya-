"""
Stage LEAD_EXPANSION: recursive investigation of extracted entities
(spec sections 8, 9, 10, 32).

Round r investigates the best-ranked, not-yet-investigated leads of depth
<= r.  Each lead gets a bounded number of queries (from the planner); the
branch is abandoned as soon as its information gain falls below the
threshold.  Leads found while investigating a depth-d lead get depth d+1, so
``max_depth`` bounds the recursion and ``max_leads`` bounds the fan-out.
"""

from __future__ import annotations

from collections import Counter

from collectors.base import BaseCollector, CollectorContext, run_planned_queries
from core.logging import get_logger
from core.models import FieldType, Lead, LeadType, Stage, StageResult
from core.strategy import LeadContext

log = get_logger("collectors.leads")


def build_lead_context(ctx: CollectorContext) -> LeadContext:
    """Most frequent cities / businesses / names / emails / domains seen with the number."""
    def top(field: FieldType, n: int, key: str | None = None) -> list[str]:
        c: Counter[str] = Counter()
        label: dict[str, str] = {}
        for f in ctx.sink.findings_by_field(field.value):
            v = str(f.metadata.get(key) or f.value) if key else f.value
            k = v.strip().lower()
            if not k:
                continue
            c[k] += 2 if f.number_displayed else 1
            label.setdefault(k, v.strip())
        return [label[k] for k, _ in c.most_common(n)]

    return LeadContext(
        cities=top(FieldType.LOCATION, 3, "city"),
        businesses=top(FieldType.BUSINESS, 3),
        names=top(FieldType.NAME, 3),
        emails=top(FieldType.EMAIL, 3),
        domains=top(FieldType.WEBSITE, 3),
    )


class LeadExpansionCollector(BaseCollector):
    name = "lead_expansion"
    stage = Stage.LEAD_EXPANSION

    def enabled(self, ctx: CollectorContext) -> bool:
        return ctx.config.max_depth > 0 and ctx.config.max_leads > 0

    async def run(self, ctx: CollectorContext) -> StageResult:
        from scoring.relevance import rank_leads

        result = StageResult(stage=self.stage)
        investigated = 0
        rounds = 0
        low_gain_streak = 0
        for depth in range(0, ctx.config.max_depth):
            rounds += 1
            pool = [l for l in ctx.sink.leads.values() if not l.investigated and l.depth <= depth]
            if not pool or not ctx.budget.can_run():
                break
            remaining = ctx.config.max_leads - investigated
            if remaining <= 0:
                ctx.sink.note_limitation(f"Lead limit ({ctx.config.max_leads}) reached; further leads were not expanded.")
                break
            ranked = rank_leads(pool, list(ctx.sink.findings.values()), list(ctx.sink.sources.values()),
                                limit=remaining)
            context = build_lead_context(ctx)
            for lead in ranked:
                if not ctx.budget.can_run():
                    break
                if lead.lead_type == LeadType.PHONE and not _is_co_listed(ctx, lead):
                    lead.investigated = True  # never expand a number that is not publicly co-listed
                    continue
                queries = ctx.planner.lead_queries(lead, context)
                before_q = len(ctx.sink.queries)
                before_src = len(ctx.sink.sources)
                await run_planned_queries(ctx, queries, stage=self.stage, lead_depth=lead.depth + 1)
                lead.investigated = True
                lead.queries_run = len(ctx.sink.queries) - before_q
                lead.information_gain = ctx.budget.branch_gain(f"lead:{lead.lead_id}")
                investigated += 1
                new_sources = len(ctx.sink.sources) - before_src
                log.info("lead investigated", lead_type=lead.lead_type.value, depth=lead.depth,
                         queries=lead.queries_run, new_sources=new_sources, gain=round(lead.information_gain, 2))
                low_gain_streak = low_gain_streak + 1 if lead.information_gain < ctx.config.info_gain_threshold else 0
                if low_gain_streak >= 3 and investigated >= 3:
                    ctx.sink.note_limitation("Lead expansion stopped early: three consecutive leads produced "
                                             "no new public sources (information gain below threshold).")
                    break
            else:
                continue
            break
        result.counts = {"leads_investigated": investigated, "rounds": rounds,
                         "leads_total": len(ctx.sink.leads)}
        result.message = f"{investigated} leads investigated over {rounds} round(s)"
        return result


def _is_co_listed(ctx: CollectorContext, lead: Lead) -> bool:
    for fid in lead.origin_finding_ids:
        f = ctx.sink.findings.get(fid)
        if f and f.field == FieldType.PHONE and f.metadata.get("co_listed"):
            return True
    return False
