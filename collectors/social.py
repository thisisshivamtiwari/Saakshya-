"""
Stage SOCIAL: public social / profile discovery (spec section 7).

Everything here is search-engine mediated (``site:`` dorks) plus optional
public-profile checks for usernames (Maigret / builtin) that only perform
unauthenticated GETs on public profile URLs.  We never log in, never call
private APIs, and never claim "number belongs to account X"; every profile
carries DIRECT / INDIRECT / INFERRED association and the evidence text.
"""

from __future__ import annotations

from collectors.base import BaseCollector, CollectorContext, run_planned_queries
from core.logging import get_logger
from core.models import Association, FieldType, Lead, LeadType, SocialProfile, Source, Stage, StageResult
from scoring.source_quality import platform_for_url

log = get_logger("collectors.social")


def _profile_from_source(ctx: CollectorContext, src: Source) -> SocialProfile | None:
    from extractors.username_extractor import extract_profiles

    platform = platform_for_url(src.url)
    if not platform:
        return None
    matches = extract_profiles(src.url, url=src.url)
    username = matches[0].username if matches else ""
    findings = ctx.sink.findings_for_source(src.source_id)
    displayed = bool(src.extra.get("number_displayed")) or any(f.number_displayed for f in findings)
    text = src.excerpt or src.title
    return SocialProfile(
        platform=platform, username=username, display_name=(src.title or "").split(" - ")[0].split(" | ")[0][:120],
        profile_url=src.url, source_url=src.url, matching_text=text[:400],
        confidence=0.7 if displayed else 0.45, number_displayed=displayed,
        association=Association.DIRECT if displayed else Association.INDIRECT,
        finding_ids=[f.finding_id for f in findings],
    )


def assemble_profiles(ctx: CollectorContext) -> set[str]:
    """
    Build ``SocialProfile`` objects from (1) sources that are public profile pages and
    (2) profile URLs mentioned on other public pages.  Idempotent; returns the set of
    profile URLs now known.
    """
    seen: set[str] = {p.profile_url for p in ctx.sink.social_profiles}
    for src in list(ctx.sink.sources.values()):
        if src.canonical_url in seen or src.url in seen:
            continue
        prof = _profile_from_source(ctx, src)
        if prof and prof.username:
            seen.add(src.canonical_url)
            seen.add(src.url)
            ctx.sink.social_profiles.append(prof)
    for f in ctx.sink.findings_by_field(FieldType.SOCIAL_PROFILE.value):
        purl = str(f.metadata.get("profile_url") or f.value)
        if purl in seen or not purl.startswith("http"):
            continue
        seen.add(purl)
        ctx.sink.social_profiles.append(SocialProfile(
            platform=str(f.metadata.get("platform") or platform_for_url(purl) or "unknown"),
            username=str(f.metadata.get("username") or ""), profile_url=purl, source_url=f.source_url,
            matching_text=f.evidence_text, confidence=min(0.6, f.confidence),
            number_displayed=f.number_displayed,
            association=Association.INDIRECT if f.number_displayed else Association.INFERRED,
            finding_ids=[f.finding_id],
        ))
    return seen


class SocialCollector(BaseCollector):
    name = "social"
    stage = Stage.SOCIAL

    def enabled(self, ctx: CollectorContext) -> bool:
        return ctx.config.enable_social

    async def run(self, ctx: CollectorContext) -> StageResult:
        result = StageResult(stage=self.stage)
        await run_planned_queries(ctx, ctx.planner.social_queries(), stage=self.stage)
        seen = assemble_profiles(ctx)
        # optional username enumeration on public profile pages (opt-in, DEEP)
        checked = 0
        if ctx.config.enable_username_enum:
            checked = await self._username_enumeration(ctx, seen)
        result.counts = {"profiles": len(ctx.sink.social_profiles), "username_checks": checked}
        result.message = f"{len(ctx.sink.social_profiles)} public profile references"
        return result

    async def _username_enumeration(self, ctx: CollectorContext, seen: set[str]) -> int:
        providers = ctx.registry.username_providers()
        if not providers:
            ctx.sink.note_limitation("Username enumeration requested but no username provider is installed "
                                     "(pip install maigret) - skipped.")
            return 0
        usernames: list[Lead] = [l for l in ctx.sink.leads.values() if l.lead_type == LeadType.USERNAME]
        usernames.sort(key=lambda l: -l.relevance)
        checked = 0
        for lead in usernames[: max(1, ctx.config.max_leads // 2)]:
            for p in providers:
                try:
                    profiles = await p.check(lead.value)
                except Exception as exc:  # defensive
                    log.warning("username provider failed", provider=p.name, error=type(exc).__name__)
                    continue
                checked += 1
                for prof in profiles:
                    if prof.profile_url in seen:
                        continue
                    seen.add(prof.profile_url)
                    prof.association = Association.INFERRED
                    prof.number_displayed = False
                    prof.confidence = min(prof.confidence, 0.35)
                    prof.matching_text = prof.matching_text or (
                        f"Username '{lead.value}' exists on {prof.platform}; identical usernames are NOT proof of the "
                        f"same person (checked via {p.name} on public profile URL)")
                    prof.finding_ids = list(lead.origin_finding_ids)
                    ctx.sink.social_profiles.append(prof)
                    src, _ = ctx.sink.add_source(prof.profile_url, title=prof.display_name or prof.username,
                                                 provider=p.name)
                    src.extra["username_enumeration"] = True
        if checked:
            ctx.sink.note_limitation("Username-enumeration results are INFERRED (same username on another platform); "
                                     "they are not evidence that the number belongs to those accounts.")
        return checked
