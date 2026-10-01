"""
InvestigationEngine - orchestrates the full pipeline:

normalise → telecom → search → documents → social → business → registries →
classifieds → page fetch → lead expansion → correlation → scoring → report.

Every stage is isolated: a failing stage is recorded and the investigation
continues.  The engine never performs any action outside the lawful
public-source boundary described in docs/ARCHITECTURE.md §11.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Optional

from collectors.base import CollectorContext, ProgressCallback
from collectors.business import BusinessCollector, build_businesses
from collectors.classifieds import ClassifiedsCollector
from collectors.documents import DocumentCollector
from collectors.leads import LeadExpansionCollector
from collectors.page_fetch import PageFetchCollector
from collectors.registries import RegistryCollector
from collectors.search import SearchCollector
from collectors.social import SocialCollector, assemble_profiles
from collectors.telecom import TelecomCollector
from config.settings import Settings, get_settings
from core.evidence import EvidenceSink
from core.http import HttpClient
from core.logging import configure_logging, get_logger
from core.models import (
    Address,
    AddressClass,
    Association,
    ConfidenceLabel,
    Depth,
    FieldType,
    Investigation,
    InvestigationConfig,
    InvestigationMeta,
    Location,
    NormalizedPhone,
    ProgressEvent,
    ProviderState,
    Stage,
    StageResult,
    StageStatus,
    TelecomResult,
    utcnow,
)
from core.normalize import normalize_indian_number
from core.registry import ProviderRegistry
from core.strategy import QueryPlanner, SearchBudget
from storage.cache import ResponseCache

log = get_logger("engine")

STANDARD_LIMITATIONS = [
    "Public-source associations are not proof of identity; the number may be recycled, shared, or listed by a "
    "third party (employee, family member, agent).",
    "Carrier and region hints reflect numbering-plan allocation or third-party provider data; Mobile Number "
    "Portability means the current operator and service area may differ.",
    "Only publicly indexed pages were consulted; private profiles, authenticated content, breach data and "
    "telecom subscriber records were never accessed.",
    "Search-engine coverage is partial and biased towards recent, popular pages; absence of results is not "
    "evidence of absence.",
    "Confidence scores are transparent analytical estimates, not probabilities of truth.",
]


class InvestigationEngine:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        registry: Optional[ProviderRegistry] = None,
        cache: Optional[ResponseCache] = None,
        http: Optional[HttpClient] = None,
        progress: Optional[ProgressCallback] = None,
        persist: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        import core.logging as _log_mod

        if not _log_mod._CONFIGURED:  # respect a level already chosen by the CLI / UI
            configure_logging(self.settings.log_level, self.settings.log_json)
        self._registry = registry
        self._cache = cache
        self._http = http
        self.progress: ProgressCallback = progress or (lambda e: None)
        self.persist = persist
        self.last_paths: dict[str, Path] = {}

    # ------------------------------------------------------------------ #
    def run_sync(self, config: InvestigationConfig) -> Investigation:
        return asyncio.run(self.run(config))

    async def run(self, config: InvestigationConfig) -> Investigation:
        meta = InvestigationMeta(depth=config.depth, authorization_note=config.authorization_note,
                                 case_reference=config.case_reference,
                                 config=config.model_dump(mode="json"))
        self._emit(Stage.NORMALIZE, StageStatus.RUNNING, "normalising number")
        phone = normalize_indian_number(config.phone_raw)
        inv = Investigation(investigation=meta, phone=phone)
        norm_stage = StageResult(stage=Stage.NORMALIZE, started_at=utcnow(), finished_at=utcnow())
        if not phone.ok:
            norm_stage.status = StageStatus.FAILED
            norm_stage.message = "; ".join(phone.warnings) or "invalid number"
            meta.stages.append(norm_stage)
            inv.limitations = phone.warnings + ["Investigation aborted: the input is not a valid Indian number."]
            meta.finished_at = utcnow()
            self._emit(Stage.NORMALIZE, StageStatus.FAILED, norm_stage.message)
            log.warning("invalid number; aborting", masked=phone.masked or "?")
            return inv
        norm_stage.status = StageStatus.DONE
        norm_stage.message = f"{phone.masked} ({phone.kind.value}), {len(phone.variants)} search variants"
        meta.stages.append(norm_stage)
        self._emit(Stage.NORMALIZE, StageStatus.DONE, norm_stage.message)
        log.info("investigation started", investigation_id=meta.investigation_id, depth=config.depth.value,
                 number=phone.masked)

        http, registry, fixture = self._build_runtime(config)
        meta.providers = registry.infos()
        sink = EvidenceSink(phone)
        if fixture and fixture.get("telecom"):
            for t in fixture["telecom"]:
                sink.telecom.append(TelecomResult(provider=str(t.get("provider", "fixture")), field=str(t["field"]),
                                                  value=str(t["value"]), confidence=float(t.get("confidence", 0.4)),
                                                  note=str(t.get("note", "synthetic fixture value"))))
        snapshot_store = None
        if self.persist:
            try:
                from storage.snapshots import SnapshotStore

                self.settings.ensure_dirs()
                snapshot_store = SnapshotStore(self.settings.snapshot_dir / meta.investigation_id)
            except Exception as exc:  # pragma: no cover
                log.debug("snapshot store unavailable", error=str(exc))
        ctx = CollectorContext(config=config, phone=phone, registry=registry, http=http, sink=sink,
                               planner=QueryPlanner(config, phone),
                               budget=SearchBudget(config.max_queries, config.info_gain_threshold),
                               settings=self.settings, progress=self.progress, snapshot_store=snapshot_store)

        collectors = [
            TelecomCollector(), SearchCollector(), DocumentCollector(), SocialCollector(), BusinessCollector(),
            RegistryCollector(), ClassifiedsCollector(), PageFetchCollector(), LeadExpansionCollector(),
        ]
        try:
            for collector in collectors:
                meta.stages.append(await collector.execute(ctx))
            # consolidate derived objects after lead expansion added findings
            build_businesses(ctx)
            assemble_profiles(ctx)
            self._emit(Stage.CORRELATION, StageStatus.RUNNING, "resolving entities")
            meta.stages.append(self._correlate(inv, ctx))
            self._emit(Stage.SCORING, StageStatus.RUNNING, "scoring candidates")
            meta.stages.append(self._score(inv, ctx))
        finally:
            if self._http is None:
                await http.aclose()

        inv.limitations = list(dict.fromkeys(STANDARD_LIMITATIONS + sink.limitations + self._provider_limitations(registry)))
        meta.finished_at = utcnow()
        self._emit(Stage.REPORT, StageStatus.RUNNING, "writing reports")
        meta.stages.append(self._persist_and_report(inv, config))
        self._emit(Stage.REPORT, StageStatus.DONE, f"{len(self.last_paths)} report files")
        log.info("investigation finished", investigation_id=meta.investigation_id, entities=len(inv.entities),
                 sources=len(inv.sources), findings=len(inv.findings), queries=len(inv.queries))
        return inv

    # ------------------------------------------------------------------ #
    # runtime
    # ------------------------------------------------------------------ #
    def _build_runtime(self, config: InvestigationConfig) -> tuple[HttpClient, ProviderRegistry, Optional[dict]]:
        fixture: Optional[dict] = None
        if self._registry is not None and self._http is not None:
            return self._http, self._registry, None
        cache = self._cache
        if cache is None and self.persist:
            try:
                self.settings.ensure_dirs()
                cache = ResponseCache(self.settings.cache_path, ttl_seconds=self.settings.cache_ttl_hours * 3600)
            except Exception as exc:  # pragma: no cover
                log.warning("cache unavailable; continuing without cache", error=str(exc))
                cache = None
        transport = None
        if config.offline:
            from providers.search.fixture import build_offline_transport, load_fixture

            fixture = load_fixture(config.fixture_path)
            transport = build_offline_transport(fixture)
            cache = ResponseCache(":memory:")
        http = self._http or HttpClient(self.settings, cache, transport=transport)
        registry = self._registry or ProviderRegistry(self.settings, http, only=config.providers,
                                                      offline=config.offline, fixture_path=config.fixture_path)
        return http, registry, fixture

    def _emit(self, stage: Stage, status: StageStatus, message: str = "") -> None:
        try:
            self.progress(ProgressEvent(stage=stage, status=status, message=message))
        except Exception:  # pragma: no cover
            pass

    @staticmethod
    def _provider_limitations(registry: ProviderRegistry) -> list[str]:
        out: list[str] = []
        missing = [i.name for i in registry.infos() if i.state == ProviderState.MISSING_KEY]
        if missing:
            out.append("Providers not configured (no API key): " + ", ".join(sorted(missing)) + ".")
        if not registry.search_providers():
            out.append("No web search provider was available; only offline numbering intelligence was produced.")
        for i in registry.infos():
            if i.name == "google_cse" and i.state == ProviderState.AVAILABLE:
                out.append("Google Custom Search JSON API is closed to new customers and shuts down on 2027-01-01.")
        return out

    # ------------------------------------------------------------------ #
    # correlation & scoring
    # ------------------------------------------------------------------ #
    def _correlate(self, inv: Investigation, ctx: CollectorContext) -> StageResult:
        from correlation.alternate_numbers import find_co_listed_numbers
        from correlation.contradictions import detect_contradictions
        from correlation.dedup import dedup_findings, dedup_sources, group_duplicate_sources_by_content
        from correlation.entity_resolver import attach_derived_objects, resolve_entities
        from correlation.graph import EvidenceGraph
        from correlation.timeline import build_timeline

        stage = StageResult(stage=Stage.CORRELATION, started_at=utcnow())
        sink = ctx.sink
        try:
            sources = dedup_sources(list(sink.sources.values()))
            group_duplicate_sources_by_content(sources)
            findings = dedup_findings(list(sink.findings.values()))
            entities, relationships = resolve_entities(ctx.phone, findings, sources)
            inv.sources, inv.findings = sources, findings
            inv.entities, inv.relationships = entities, relationships
            inv.telecom = list(sink.telecom)
            inv.queries = list(sink.queries)
            inv.leads = sorted(sink.leads.values(), key=lambda l: -l.relevance)
            inv.social_profiles = list(sink.social_profiles)
            inv.businesses = list(sink.businesses)
            inv.listings = list(sink.listings)
            inv.documents = list(sink.documents)
            inv.addresses, inv.locations = self._addresses_and_locations(findings)
            attach_derived_objects(entities, inv.social_profiles, inv.businesses, inv.documents, inv.addresses)
            for loc in inv.locations:
                for e in entities:
                    if set(loc.finding_ids) & set(e.finding_ids):
                        loc.entity_id = e.entity_id
                        break
            for lst in inv.listings:
                for e in entities:
                    if set(lst.finding_ids) & set(e.finding_ids):
                        lst.entity_id = e.entity_id
                        break
            inv.contradictions = detect_contradictions(ctx.phone, entities, findings, sources)
            inv.timeline = build_timeline(findings, sources, entities)
            inv.associated_numbers = find_co_listed_numbers(ctx.phone, findings, sources)
            for an in inv.associated_numbers:
                for e in entities:
                    if an.finding_id in e.finding_ids:
                        an.entity_id = e.entity_id
                        if an.e164 not in e.associated_numbers:
                            e.associated_numbers.append(an.e164)
                        break
            inv.names, inv.emails, inv.usernames = self._aggregate_lists(findings)
            graph = EvidenceGraph.from_investigation_parts(ctx.phone, entities, relationships, findings, sources)
            inv.graph = graph.to_node_link()
            inv.graph["ascii"] = graph.to_ascii_tree()
            stage.status = StageStatus.DONE
            stage.counts = {"entities": len(entities), "relationships": len(relationships),
                            "contradictions": len(inv.contradictions), "associated_numbers": len(inv.associated_numbers)}
            stage.message = (f"{len(entities)} candidate entities, {len(inv.contradictions)} contradictions, "
                             f"{len(inv.associated_numbers)} co-listed numbers")
            if inv.contradictions:
                log.warning("conflicting public associations detected", count=len(inv.contradictions))
        except Exception as exc:
            log.error("correlation failed", error=f"{type(exc).__name__}: {exc}")
            stage.status = StageStatus.FAILED
            stage.message = f"{type(exc).__name__}: {exc}"
            # keep raw evidence so the report is still useful
            inv.sources = inv.sources or list(sink.sources.values())
            inv.findings = inv.findings or list(sink.findings.values())
            inv.queries = list(sink.queries)
            inv.telecom = list(sink.telecom)
        stage.finished_at = utcnow()
        self._emit(Stage.CORRELATION, stage.status, stage.message)
        return stage

    def _score(self, inv: Investigation, ctx: CollectorContext) -> StageResult:
        from scoring.confidence import build_executive_summary, score_entity, summarize_confidence

        stage = StageResult(stage=Stage.SCORING, started_at=utcnow())
        try:
            for e in inv.entities:
                e.score = score_entity(e, inv.findings, inv.sources, inv.contradictions)
            inv.entities.sort(key=lambda e: (-e.score.percent, -e.independent_source_count, e.label))
            inv.confidence = summarize_confidence(inv.entities)
            inv.summary = build_executive_summary(inv)
            stage.status = StageStatus.DONE
            top = inv.entities[0] if inv.entities else None
            stage.message = (f"top candidate '{top.label}' {top.score.percent}% ({top.score.label.value})" if top
                             else "no candidate identity established")
            stage.counts = {"entities": len(inv.entities)}
        except Exception as exc:
            log.error("scoring failed", error=f"{type(exc).__name__}: {exc}")
            stage.status = StageStatus.FAILED
            stage.message = f"{type(exc).__name__}: {exc}"
        stage.finished_at = utcnow()
        self._emit(Stage.SCORING, stage.status, stage.message)
        return stage

    # ------------------------------------------------------------------ #
    def _persist_and_report(self, inv: Investigation, config: InvestigationConfig) -> StageResult:
        stage = StageResult(stage=Stage.REPORT, started_at=utcnow())
        self.last_paths = {}
        errors: list[str] = []
        if self.persist:
            try:
                from storage.evidence_store import EvidenceStore

                self.settings.ensure_dirs()
                store = EvidenceStore(self.settings.evidence_db_path)
                store.save(inv, store_provider_snippets=self.settings.store_provider_snippets)
                store.close()
            except Exception as exc:
                errors.append(f"evidence store: {type(exc).__name__}: {exc}")
                log.warning("evidence store failed", error=str(exc))
        if config.formats:
            try:
                from reports.builder import write_reports

                out_dir = Path(config.output_dir) / inv.investigation.investigation_id
                self.last_paths = write_reports(inv, out_dir, config.formats)
            except Exception as exc:
                errors.append(f"reports: {type(exc).__name__}: {exc}")
                log.warning("report generation failed", error=str(exc))
        stage.errors = errors
        stage.status = StageStatus.DONE if not errors else StageStatus.FAILED
        stage.message = ", ".join(f"{k}={v}" for k, v in self.last_paths.items()) or "; ".join(errors) or "no output"
        stage.finished_at = utcnow()
        return stage

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _addresses_and_locations(findings) -> tuple[list[Address], list[Location]]:  # type: ignore[no-untyped-def]
        addresses: list[Address] = []
        seen_addr: set[str] = set()
        for f in findings:
            if f.field != FieldType.ADDRESS:
                continue
            key = f.normalized_value or f.value.lower()
            if key in seen_addr:
                continue
            seen_addr.add(key)
            cls = str(f.metadata.get("address_class") or "unknown")
            try:
                classification = AddressClass(cls)
            except ValueError:
                classification = AddressClass.UNKNOWN
            addresses.append(Address(
                raw=f.value, city=str(f.metadata.get("city") or ""), state=str(f.metadata.get("state") or ""),
                pincode=str(f.metadata.get("pincode") or ""), classification=classification,
                classification_reason=str(f.metadata.get("reason") or ""), source_id=f.source_id,
                finding_ids=[f.finding_id], published_at=f.published_at, date_precision=f.date_precision,
            ))
        locs: dict[str, Location] = {}
        srcs: dict[str, set[str]] = defaultdict(set)
        for f in findings:
            if f.field not in (FieldType.LOCATION, FieldType.ADDRESS):
                continue
            city = str(f.metadata.get("city") or (f.value if f.field == FieldType.LOCATION else "")).strip()
            state = str(f.metadata.get("state") or "").strip()
            if not city and not state:
                continue
            key = f"{city.lower()}|{state.lower()}"
            loc = locs.get(key)
            if loc is None:
                loc = Location(city=city, state=state, label=", ".join(p for p in (city, state) if p))
                locs[key] = loc
            loc.finding_ids.append(f.finding_id)
            srcs[key].add(f.source_id)
        for key, loc in locs.items():
            loc.source_count = len(srcs[key])
        locations = sorted(locs.values(), key=lambda l: (-l.source_count, l.label))
        return addresses, locations

    @staticmethod
    def _aggregate_lists(findings) -> tuple[list[str], list[str], list[str]]:  # type: ignore[no-untyped-def]
        def agg(field: FieldType) -> list[str]:
            c: Counter[str] = Counter()
            label: dict[str, str] = {}
            for f in findings:
                if f.field != field:
                    continue
                k = f.normalized_value or f.value.lower()
                c[k] += 2 if f.number_displayed else 1
                label.setdefault(k, f.value)
            return [label[k] for k, _ in c.most_common()]

        usernames = agg(FieldType.USERNAME)
        return agg(FieldType.NAME), agg(FieldType.EMAIL), usernames


def default_config(phone_raw: str, depth: Depth = Depth.STANDARD, **overrides) -> InvestigationConfig:  # type: ignore[no-untyped-def]
    return InvestigationConfig.for_depth(phone_raw, depth, **overrides)


__all__ = ["InvestigationEngine", "default_config", "Association", "ConfidenceLabel", "NormalizedPhone"]
