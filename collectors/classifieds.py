"""Stage CLASSIFIEDS: public classified / marketplace listings (spec section 12).  Never contacts sellers."""

from __future__ import annotations

import re

from collectors.base import BaseCollector, CollectorContext, run_planned_queries
from core.models import FieldType, Listing, SourceType, Stage, StageResult

_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("vehicles", re.compile(r"\b(car|bike|scooter|maruti|honda|hyundai|swift|activa|vehicle|suv|tata nexon|kia)\b", re.I)),
    ("real_estate", re.compile(r"\b(flat|apartment|bhk|plot|villa|house for|rent|lease|property|acre|sq\.? ?ft)\b", re.I)),
    ("jobs", re.compile(r"\b(job|vacancy|hiring|walk-?in|recruit|salary)\b", re.I)),
    ("tutoring", re.compile(r"\b(tuition|tutor|coaching|classes|home tutor)\b", re.I)),
    ("services", re.compile(r"\b(service|repair|plumber|electrician|cleaning|catering|photograph|pest)\b", re.I)),
    ("business_services", re.compile(r"\b(consult|gst|accounting|legal|registration|loan|insurance)\b", re.I)),
    ("electronics", re.compile(r"\b(mobile phone|laptop|iphone|samsung|tv|refrigerator|ac for)\b", re.I)),
    ("furniture", re.compile(r"\b(sofa|bed|furniture|almirah|dining)\b", re.I)),
]


def _category(text: str, url: str) -> str:
    for name, pat in _CATEGORY_RULES:
        if pat.search(text) or pat.search(url.replace("-", " ").replace("/", " ")):
            return name
    return "local_commerce"


class ClassifiedsCollector(BaseCollector):
    name = "classifieds"
    stage = Stage.CLASSIFIEDS

    def enabled(self, ctx: CollectorContext) -> bool:
        return ctx.config.enable_classifieds

    async def run(self, ctx: CollectorContext) -> StageResult:
        result = StageResult(stage=self.stage)
        await run_planned_queries(ctx, ctx.planner.classified_queries(), stage=self.stage)
        known = {l.url for l in ctx.sink.listings}
        for src in list(ctx.sink.sources.values()):
            if src.source_type not in (SourceType.CLASSIFIED_LISTING, SourceType.MARKETPLACE) or src.url in known:
                continue
            findings = ctx.sink.findings_for_source(src.source_id)
            seller = next((f.value for f in findings if f.field == FieldType.NAME), "")
            location = next((f.value for f in findings if f.field == FieldType.LOCATION), "")
            others = [f.value for f in findings if f.field == FieldType.PHONE and f.metadata.get("co_listed")]
            emails = [f.value for f in findings if f.field == FieldType.EMAIL]
            ctx.sink.listings.append(Listing(
                title=src.title or src.url, seller_name=seller, category=_category(f"{src.title} {src.excerpt}", src.url),
                location=location, url=src.url, published_at=src.published_at, other_contacts=others + emails,
                source_id=src.source_id, finding_ids=[f.finding_id for f in findings],
            ))
            known.add(src.url)
        result.counts = {"listings": len(ctx.sink.listings)}
        result.message = f"{len(ctx.sink.listings)} classified / marketplace listings"
        return result
