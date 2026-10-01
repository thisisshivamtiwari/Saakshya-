"""
Source and finding de-duplication (ARCHITECTURE section 5).

Two providers frequently return the same page (``http://`` vs ``https://``, tracking
parameters, ``www.``).  ``dedup_sources`` merges such records into one ``Source`` that
remembers every provider/query that surfaced it (``referenced_by``), keeps the best quality
rating, the earliest publication date and the most complete title/excerpt.

``dedup_findings`` collapses identical facts extracted twice from the same page while
keeping the strongest association and highest extraction confidence.
"""

from __future__ import annotations

from collections import defaultdict

from core.models import Association, Finding, Source
from extractors.url_utils import canonical_url
from scoring.source_quality import QUALITY_RANK

from correlation._text import _basic_clean, independent_domain, token_set_ratio

_ASSOC_RANK = {Association.DIRECT: 3, Association.INDIRECT: 2, Association.INFERRED: 1}


def strongest_association(a: Association, b: Association) -> Association:
    return a if _ASSOC_RANK[a] >= _ASSOC_RANK[b] else b


def _canon(source: Source) -> str:
    return source.canonical_url or canonical_url(source.url)


def _merge_source(base: Source, other: Source) -> Source:
    """Merge ``other`` into a copy of ``base`` (base wins ties)."""
    merged = base.model_copy(deep=True)
    if QUALITY_RANK[other.quality] > QUALITY_RANK[merged.quality]:
        merged.quality = other.quality
        merged.source_type = other.source_type
    if other.published_at and (merged.published_at is None or other.published_at < merged.published_at):
        merged.published_at = other.published_at
        merged.date_precision = other.date_precision
    if len(other.title or "") > len(merged.title or ""):
        merged.title = other.title
    if len(other.excerpt or "") > len(merged.excerpt or ""):
        merged.excerpt = other.excerpt
    if not merged.content_hash and other.content_hash:
        merged.content_hash = other.content_hash
    if other.fetched and not merged.fetched:
        merged.fetched = True
        merged.http_status = other.http_status
        merged.robots_allowed = other.robots_allowed
    if not merged.domain and other.domain:
        merged.domain = other.domain
    refs = list(merged.referenced_by)
    for ref in list(other.referenced_by) + ([other.provider] if other.provider else []):
        if ref and ref not in refs:
            refs.append(ref)
    if merged.provider and merged.provider not in refs:
        refs.insert(0, merged.provider)
    merged.referenced_by = refs
    aliases = list(merged.extra.get("merged_source_ids", []))
    if other.source_id not in aliases:
        aliases.append(other.source_id)
    merged.extra = {**other.extra, **merged.extra, "merged_source_ids": aliases}
    return merged


def dedup_sources(sources: list[Source]) -> list[Source]:
    """
    Merge sources with the same canonical URL.  Output order = first appearance of each
    canonical URL in the input, so callers get stable ordering.
    """
    order: list[str] = []
    by_canon: dict[str, Source] = {}
    for src in sources:
        key = _canon(src)
        if key not in by_canon:
            copy = src.model_copy(deep=True)
            copy.canonical_url = copy.canonical_url or key
            if copy.provider and copy.provider not in copy.referenced_by:
                copy.referenced_by = [copy.provider] + list(copy.referenced_by)
            by_canon[key] = copy
            order.append(key)
        else:
            by_canon[key] = _merge_source(by_canon[key], src)
    return [by_canon[k] for k in order]


def source_alias_map(original: list[Source], deduped: list[Source]) -> dict[str, str]:
    """``{old_source_id: surviving_source_id}`` so findings can be re-pointed after dedup."""
    mapping: dict[str, str] = {}
    for d in deduped:
        mapping[d.source_id] = d.source_id
        for alias in d.extra.get("merged_source_ids", []):
            mapping[alias] = d.source_id
    for s in original:
        mapping.setdefault(s.source_id, s.source_id)
    return mapping


def _finding_key(f: Finding) -> tuple[str, str, str]:
    value = (f.normalized_value or f.value or "").strip().lower()
    return (f.field.value, value, canonical_url(f.source_url))


def dedup_findings(findings: list[Finding]) -> list[Finding]:
    """
    Collapse findings with the same (field, normalised value, canonical source URL).
    The survivor keeps ``max`` confidence, the strongest association and
    ``number_displayed = any``.  Input order of first appearance is preserved.
    """
    order: list[tuple[str, str, str]] = []
    kept: dict[tuple[str, str, str], Finding] = {}
    for f in findings:
        key = _finding_key(f)
        if key not in kept:
            kept[key] = f.model_copy(deep=True)
            order.append(key)
            continue
        cur = kept[key]
        cur.confidence = max(cur.confidence, f.confidence)
        cur.association = strongest_association(cur.association, f.association)
        cur.number_displayed = cur.number_displayed or f.number_displayed
        if len(f.evidence_text or "") > len(cur.evidence_text or ""):
            cur.evidence_text = f.evidence_text
        if cur.published_at is None and f.published_at is not None:
            cur.published_at = f.published_at
            cur.date_precision = f.date_precision
        merged_ids = list(cur.metadata.get("merged_finding_ids", []))
        if f.finding_id not in merged_ids:
            merged_ids.append(f.finding_id)
        cur.metadata = {**f.metadata, **cur.metadata, "merged_finding_ids": merged_ids}
    return [kept[k] for k in order]


def title_similarity(a: str, b: str) -> float:
    """0..1 similarity of two page titles after normalisation (token-set ratio)."""
    na, nb = _basic_clean(a), _basic_clean(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return token_set_ratio(na, nb)


def group_duplicate_sources_by_content(sources: list[Source], threshold: float = 0.92) -> list[list[Source]]:
    """
    Group sources that carry the *same content* on different domains (syndicated
    directory listings, mirrored PDFs): identical ``content_hash`` or title similarity
    >= ``threshold``.  Every source in a group of size > 1 gets
    ``extra["duplicate_group"] = {"id", "size", "domains"}`` so reports can say
    "referenced by N sources".  Singletons are returned as one-element groups.
    """
    n = len(sources)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    domains = [independent_domain(s.url) for s in sources]
    for i in range(n):
        for j in range(i + 1, n):
            if domains[i] and domains[i] == domains[j]:
                continue  # same domain: handled by canonical-URL dedup, not content grouping
            si, sj = sources[i], sources[j]
            same_hash = bool(si.content_hash) and si.content_hash == sj.content_hash
            if same_hash or title_similarity(si.title, sj.title) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    result: list[list[Source]] = []
    for root in sorted(groups):
        members = [sources[i] for i in groups[root]]
        if len(members) > 1:
            gid = f"dup_{root}_{len(members)}"
            group_domains = sorted({domains[i] for i in groups[root] if domains[i]})
            for m in members:
                m.extra["duplicate_group"] = {"id": gid, "size": len(members), "domains": group_domains}
        result.append(members)
    return result
