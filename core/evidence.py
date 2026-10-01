"""
EvidenceSink: the engine's in-memory, deduplicating store of everything an
investigation discovers.  Collectors write into it; correlation/scoring read
from it; the engine turns it into an ``Investigation``.

Dedup rules
-----------
* Sources are unique by canonical URL (``extractors.url_utils.canonical_url``).
  A URL surfaced again by another provider/query is recorded in
  ``Source.referenced_by`` instead of creating a duplicate ("Referenced by 4
  sources" in the report).
* Findings are unique by ``Finding.dedup_key()`` = (field, normalised value,
  source URL).  Re-adding a duplicate merges confidence (max) and keeps the
  strongest association.
* Leads are unique by (lead_type, normalised value).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from core.logging import get_logger
from core.models import (
    Association,
    Business,
    DatePrecision,
    Document,
    Finding,
    Lead,
    Listing,
    NormalizedPhone,
    QueryRecord,
    SearchResult,
    SocialProfile,
    Source,
    SourceQuality,
    SourceType,
    TelecomResult,
)
from extractors.url_utils import canonical_url, registrable_domain
from scoring.source_quality import best_quality, classify_source

log = get_logger("evidence")

_ASSOC_RANK = {Association.DIRECT: 3, Association.INDIRECT: 2, Association.INFERRED: 1}


class EvidenceSink:
    def __init__(self, phone: NormalizedPhone) -> None:
        self.phone = phone
        self.sources: dict[str, Source] = {}
        self._source_by_canonical: dict[str, str] = {}
        self.findings: dict[str, Finding] = {}
        self._finding_by_key: dict[str, str] = {}
        self.queries: list[QueryRecord] = []
        self.leads: dict[str, Lead] = {}
        self._lead_by_key: dict[str, str] = {}
        self.telecom: list[TelecomResult] = []
        self.social_profiles: list[SocialProfile] = []
        self.businesses: list[Business] = []
        self.listings: list[Listing] = []
        self.documents: list[Document] = []
        self.raw_results: list[SearchResult] = []
        self.errors: list[str] = []
        self.limitations: list[str] = []

    # ------------------------------------------------------------------ #
    # Sources
    # ------------------------------------------------------------------ #
    def seen_url(self, url: str) -> bool:
        return canonical_url(url) in self._source_by_canonical

    def source_for_url(self, url: str) -> Optional[Source]:
        sid = self._source_by_canonical.get(canonical_url(url))
        return self.sources.get(sid) if sid else None

    def add_source(
        self,
        url: str,
        *,
        title: str = "",
        provider: str = "",
        snippet: str = "",
        published_at: Optional[datetime] = None,
        date_precision: DatePrecision = DatePrecision.UNKNOWN,
        source_type: Optional[SourceType] = None,
        quality: Optional[SourceQuality] = None,
        query_id: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> tuple[Source, bool]:
        canon = canonical_url(url)
        if not canon:
            raise ValueError("empty url")
        ref = provider if not query_id else f"{provider}:{query_id}"
        existing_id = self._source_by_canonical.get(canon)
        if existing_id:
            src = self.sources[existing_id]
            if ref and ref not in src.referenced_by:
                src.referenced_by.append(ref)
            if title and not src.title:
                src.title = title
            if snippet and len(snippet) > len(src.excerpt):
                src.excerpt = snippet[:1200]
            if published_at and not src.published_at:
                src.published_at, src.date_precision = published_at, date_precision
            if extra:
                src.extra.update({k: v for k, v in extra.items() if k not in src.extra})
            return src, False
        auto_type, auto_quality = classify_source(url, title, snippet)
        src = Source(
            url=url,
            canonical_url=canon,
            domain=registrable_domain(url),
            title=title[:300],
            source_type=source_type or auto_type,
            quality=quality or auto_quality,
            provider=provider,
            published_at=published_at,
            date_precision=date_precision if published_at else DatePrecision.UNKNOWN,
            excerpt=snippet[:1200],
            referenced_by=[ref] if ref else [],
            extra=dict(extra or {}),
        )
        self.sources[src.source_id] = src
        self._source_by_canonical[canon] = src.source_id
        return src, True

    def upgrade_source_quality(self, source_id: str, quality: SourceQuality) -> None:
        src = self.sources.get(source_id)
        if src:
            src.quality = best_quality(src.quality, quality)

    # ------------------------------------------------------------------ #
    # Findings / leads / queries
    # ------------------------------------------------------------------ #
    def add_finding(self, finding: Finding) -> tuple[Finding, bool]:
        if not finding.normalized_value:
            finding.normalized_value = finding.value.strip().lower()
        key = finding.dedup_key()
        existing_id = self._finding_by_key.get(key)
        if existing_id:
            f = self.findings[existing_id]
            f.confidence = max(f.confidence, finding.confidence)
            if _ASSOC_RANK[finding.association] > _ASSOC_RANK[f.association]:
                f.association = finding.association
            f.number_displayed = f.number_displayed or finding.number_displayed
            if finding.published_at and not f.published_at:
                f.published_at, f.date_precision = finding.published_at, finding.date_precision
            if len(finding.evidence_text) > len(f.evidence_text):
                f.evidence_text = finding.evidence_text
            return f, False
        self.findings[finding.finding_id] = finding
        self._finding_by_key[key] = finding.finding_id
        return finding, True

    def add_findings(self, findings: list[Finding]) -> int:
        return sum(1 for f in findings if self.add_finding(f)[1])

    def add_lead(self, lead: Lead) -> tuple[Lead, bool]:
        if not lead.normalized_value:
            lead.normalized_value = lead.value.strip().lower()
        key = f"{lead.lead_type.value}:{lead.normalized_value}"
        existing_id = self._lead_by_key.get(key)
        if existing_id:
            existing = self.leads[existing_id]
            for fid in lead.origin_finding_ids:
                if fid not in existing.origin_finding_ids:
                    existing.origin_finding_ids.append(fid)
            existing.depth = min(existing.depth, lead.depth)
            return existing, False
        self.leads[lead.lead_id] = lead
        self._lead_by_key[key] = lead.lead_id
        return lead, True

    def add_query(self, record: QueryRecord) -> None:
        self.queries.append(record)

    def findings_for_source(self, source_id: str) -> list[Finding]:
        return [f for f in self.findings.values() if f.source_id == source_id]

    def findings_by_field(self, field: str) -> list[Finding]:
        return [f for f in self.findings.values() if f.field.value == field]

    # ------------------------------------------------------------------ #
    def counts(self) -> dict[str, int]:
        return {
            "sources": len(self.sources),
            "findings": len(self.findings),
            "queries": len(self.queries),
            "leads": len(self.leads),
            "telecom": len(self.telecom),
            "social_profiles": len(self.social_profiles),
            "businesses": len(self.businesses),
            "listings": len(self.listings),
            "documents": len(self.documents),
        }

    def note_limitation(self, text: str) -> None:
        if text not in self.limitations:
            self.limitations.append(text)
