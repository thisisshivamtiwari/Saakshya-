"""
Stage BUSINESS: business / directory discovery (spec section 11).

Search-engine mediated dorks over Indian business directories + optional
documented place APIs (Google Places phone-number search).  Builds
``Business`` objects from BUSINESS findings, attaching owner / address / city /
website / email / co-listed numbers only when they come from the *same*
public source.
"""

from __future__ import annotations

from collections import defaultdict

from collectors.base import BaseCollector, CollectorContext, run_planned_queries
from core.logging import get_logger
from core.models import Business, FieldType, Finding, Stage, StageResult

log = get_logger("collectors.business")

_OWNER_TITLES = ("proprietor", "owner", "founder", "director", "managing director", "partner", "ceo")


class BusinessCollector(BaseCollector):
    name = "business"
    stage = Stage.BUSINESS

    def enabled(self, ctx: CollectorContext) -> bool:
        return ctx.config.enable_business

    async def run(self, ctx: CollectorContext) -> StageResult:
        result = StageResult(stage=self.stage)
        await run_planned_queries(ctx, ctx.planner.business_queries(), stage=self.stage)
        await self._place_providers(ctx, result)
        built = build_businesses(ctx)
        result.counts = {"businesses": len(built)}
        result.message = f"{len(built)} public business references"
        return result

    async def _place_providers(self, ctx: CollectorContext, result: StageResult) -> None:
        for p in ctx.registry.place_providers():
            try:
                businesses = await p.find_by_phone(ctx.phone)
            except Exception as exc:  # defensive
                log.warning("place provider failed", provider=p.name, error=type(exc).__name__)
                result.errors.append(f"{p.name}: {type(exc).__name__}")
                continue
            for biz in businesses:
                url = biz.website or (biz.social_urls[0] if biz.social_urls else "")
                src_url = url or f"https://www.google.com/maps/search/?api=1&query={ctx.phone.e164}"
                src, _ = ctx.sink.add_source(src_url, title=biz.name, provider=p.name,
                                             snippet=f"{biz.name} {biz.address} {biz.city}".strip())
                src.extra["number_displayed"] = True
                f = Finding(phone=ctx.phone.e164, field=FieldType.BUSINESS, value=biz.name,
                            normalized_value=biz.name.lower().strip(), source_id=src.source_id, source_url=src.url,
                            source_type=src.source_type, source_quality=src.quality,
                            evidence_text=f"Place listing returned for the phone number: {biz.name}, {biz.address}",
                            confidence=0.85, number_displayed=True, provider=p.name, extractor=p.name,
                            metadata={"city": biz.city, "category": biz.category, "address": biz.address})
                f, _ = ctx.sink.add_finding(f)
                biz.source_ids.append(src.source_id)
                biz.finding_ids.append(f.finding_id)
                if biz.address:
                    af = Finding(phone=ctx.phone.e164, field=FieldType.ADDRESS, value=biz.address,
                                 source_id=src.source_id, source_url=src.url, source_type=src.source_type,
                                 source_quality=src.quality, evidence_text=f"Listing address: {biz.address}",
                                 confidence=0.8, number_displayed=True, provider=p.name, extractor=p.name,
                                 metadata={"city": biz.city, "address_class": "commercial"})
                    af, _ = ctx.sink.add_finding(af)
                    biz.finding_ids.append(af.finding_id)
                ctx.sink.businesses.append(biz)


def build_businesses(ctx: CollectorContext) -> list[Business]:
    """Group BUSINESS findings by normalised name and enrich from same-source findings."""
    existing = {b.name.lower().strip(): b for b in ctx.sink.businesses}
    by_name: dict[str, list[Finding]] = defaultdict(list)
    for f in ctx.sink.findings_by_field(FieldType.BUSINESS.value):
        by_name[f.normalized_value or f.value.lower().strip()].append(f)
    for key, findings in by_name.items():
        biz = existing.get(key)
        if biz is None:
            biz = Business(name=max((f.value for f in findings), key=len))
            existing[key] = biz
            ctx.sink.businesses.append(biz)
        for f in findings:
            if f.source_id not in biz.source_ids:
                biz.source_ids.append(f.source_id)
            if f.finding_id not in biz.finding_ids:
                biz.finding_ids.append(f.finding_id)
            if not biz.category and f.metadata.get("category"):
                biz.category = str(f.metadata["category"])
            same_source = ctx.sink.findings_for_source(f.source_id)
            for g in same_source:
                if g.field == FieldType.ADDRESS and not biz.address:
                    biz.address = g.value
                    biz.city = biz.city or str(g.metadata.get("city") or "")
                elif g.field == FieldType.LOCATION and not biz.city:
                    biz.city = str(g.metadata.get("city") or g.value)
                elif g.field == FieldType.WEBSITE and not biz.website:
                    biz.website = g.value
                elif g.field == FieldType.EMAIL and not biz.email:
                    biz.email = g.value
                elif g.field == FieldType.SOCIAL_PROFILE:
                    purl = str(g.metadata.get("profile_url") or g.value)
                    if purl not in biz.social_urls:
                        biz.social_urls.append(purl)
                elif g.field == FieldType.PHONE and g.metadata.get("co_listed") and g.value not in biz.other_numbers:
                    biz.other_numbers.append(g.value)
                elif g.field == FieldType.JOB_TITLE and not biz.owner:
                    title = g.value.lower()
                    if any(t in title for t in _OWNER_TITLES) and g.metadata.get("for_name"):
                        biz.owner = str(g.metadata["for_name"])
            if not biz.owner:
                # a person name on the same source as a proprietor-style label in the evidence text
                for g in same_source:
                    if g.field == FieldType.NAME and any(t in g.evidence_text.lower() for t in _OWNER_TITLES):
                        biz.owner = g.value
                        break
                if not biz.owner:
                    for g in same_source:
                        if g.field == FieldType.NAME and (f.number_displayed and g.number_displayed):
                            biz.owner = g.value
                            break
    return ctx.sink.businesses
