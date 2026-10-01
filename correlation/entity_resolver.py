"""
Entity resolution (ARCHITECTURE section 5, steps 1-7).

The algorithm is intentionally conservative and fully explainable:

1. Every source becomes one *mention cluster* (all findings extracted from that page).
2. Clusters merge only when they share a **strong key** (e-mail, ``platform:username``,
   website domain) or a fuzzy-equal person/business name (token-set ratio >= 0.85) with
   **no conflicting full person name** on either side.
3. Two clusters with different person names are never merged unless they share a strong
   key - in which case both names are kept and the reason is written to ``why_linked``.
4. Clusters without any identifying key are pooled into one "Unattributed public mentions"
   pseudo-entity (kind UNKNOWN).
5. ``Entity.kind``: PERSON when a person name is present (a source that lists a person *and*
   a business is the proprietor pattern: PERSON with ``businesses=[...]``), BUSINESS when only
   business names, ORGANIZATION when only organisation names, else UNKNOWN.
6. Lists, provenance, independent-source count and association strength are filled in.
7. ``Relationship`` edges are emitted with node ids ``phone:<e164>``, ``ent:<id>``,
   ``name:<normalised>`` ... so the graph module and reports share one vocabulary.

Nothing here upgrades an association: INFERRED stays INFERRED, and the resolver never
invents a value that was not literally extracted from a public source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from core.logging import get_logger
from core.models import (
    Address,
    Association,
    Business,
    Document,
    Entity,
    EntityKind,
    FieldType,
    Finding,
    NormalizedPhone,
    Relationship,
    SocialProfile,
    Source,
    mask_phone,
    stable_id,
)
from extractors.url_utils import canonical_url
from scoring.source_quality import platform_for_url

from correlation._text import (
    address_hash,
    display_domain,
    independent_domain,
    is_business_name,
    is_full_name,
    join_human,
    most_common_variant,
    name_tokens,
    names_fuzzy_equal,
    normalise_business,
    normalise_city,
    normalise_domain,
    normalise_email,
    normalise_name,
    normalise_username,
)

log = get_logger(__name__)

UNRESOLVED_LABEL = "Unattributed public mentions"
NAME_MATCH_THRESHOLD = 0.85

_ASSOC_RANK = {Association.DIRECT: 3, Association.INDIRECT: 2, Association.INFERRED: 1}
_ASSOC_CONF = {Association.DIRECT: 0.9, Association.INDIRECT: 0.6, Association.INFERRED: 0.3}

# Findings that never describe an identity (kept out of clusters).
_NON_IDENTITY_FIELDS = {FieldType.TELECOM}


# --------------------------------------------------------------------------- #
# Mention clusters
# --------------------------------------------------------------------------- #


@dataclass
class _Cluster:
    """All findings extracted from one or more sources believed to describe one entity."""

    findings: list[Finding] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    # normalised key -> display variants
    person_names: dict[str, list[str]] = field(default_factory=dict)
    businesses: dict[str, list[str]] = field(default_factory=dict)
    organizations: dict[str, list[str]] = field(default_factory=dict)
    emails: dict[str, list[str]] = field(default_factory=dict)
    usernames: dict[str, list[str]] = field(default_factory=dict)  # "platform:user"
    profiles: dict[str, list[str]] = field(default_factory=dict)  # "platform:user" -> profile urls
    websites: dict[str, list[str]] = field(default_factory=dict)
    locations: dict[str, list[str]] = field(default_factory=dict)
    addresses: dict[str, list[str]] = field(default_factory=dict)
    job_titles: dict[str, list[str]] = field(default_factory=dict)
    phones: dict[str, list[str]] = field(default_factory=dict)
    why_linked: list[str] = field(default_factory=list)

    # ---- identity keys ------------------------------------------------- #
    def strong_keys(self) -> set[str]:
        keys = {f"email:{k}" for k in self.emails}
        keys |= {f"username:{k}" for k in self.usernames}
        keys |= {f"username:{k}" for k in self.profiles}
        keys |= {f"website:{k}" for k in self.websites}
        return keys

    def has_identity(self) -> bool:
        return bool(self.person_names or self.businesses or self.organizations or self.strong_keys())

    def full_person_names(self) -> list[str]:
        return [n for n in self.person_names if len(n.split()) >= 2]

    def primary_person_name(self) -> str:
        return _primary(self.person_names, prefer_full=True)

    def primary_business(self) -> str:
        return _primary(self.businesses) or _primary(self.organizations)

    # ---- merging -------------------------------------------------------- #
    def absorb(self, other: "_Cluster") -> None:
        self.findings.extend(other.findings)
        for sid in other.source_ids:
            if sid not in self.source_ids:
                self.source_ids.append(sid)
        for attr in ("person_names", "businesses", "organizations", "emails", "usernames", "profiles",
                     "websites", "locations", "addresses", "job_titles", "phones"):
            mine: dict[str, list[str]] = getattr(self, attr)
            for k, variants in getattr(other, attr).items():
                mine.setdefault(k, []).extend(variants)
        for why in other.why_linked:
            if why not in self.why_linked:
                self.why_linked.append(why)


def _primary(table: dict[str, list[str]], prefer_full: bool = False) -> str:
    """Most frequent normalised key; ties -> longer, then alphabetical.  Optionally prefer full names."""
    if not table:
        return ""
    items = list(table.items())
    if prefer_full:
        full = [(k, v) for k, v in items if len(k.split()) >= 2]
        if full:
            items = full
    return sorted(items, key=lambda kv: (-len(kv[1]), -len(kv[0]), kv[0]))[0][0]


def _platform_and_user(f: Finding, source: Optional[Source]) -> tuple[str, str]:
    """Derive (platform, username) for USERNAME / SOCIAL_PROFILE findings."""
    meta = f.metadata or {}
    platform = str(meta.get("platform") or "").strip().lower()
    user = str(meta.get("username") or "").strip()
    value = (f.normalized_value or f.value or "").strip()
    if not user:
        if f.field == FieldType.USERNAME:
            if ":" in value and not value.startswith("http"):
                platform = platform or value.split(":", 1)[0].lower()
                user = value.split(":", 1)[1]
            else:
                user = value
        else:  # SOCIAL_PROFILE: value is usually the profile URL
            path = value.split("://", 1)[-1].split("/", 1)[1] if "/" in value.split("://", 1)[-1] else ""
            parts = [p for p in path.split("/") if p and p not in ("in", "u", "user", "users", "profile")]
            user = parts[0] if parts else ""
    if not platform:
        platform = platform_for_url(value) if value.startswith("http") else ""
    if not platform and source is not None:
        platform = platform_for_url(source.url)
    return platform or "unknown", normalise_username(user)


def _add(table: dict[str, list[str]], key: str, display: str) -> None:
    if key:
        table.setdefault(key, []).append(display.strip())


def _cluster_from_source(source_key: str, findings: list[Finding], source: Optional[Source]) -> _Cluster:
    c = _Cluster()
    c.source_ids.append(source_key)
    for f in findings:
        if f.field in _NON_IDENTITY_FIELDS:
            continue
        c.findings.append(f)
        value = (f.value or "").strip()
        if not value:
            continue
        if f.field == FieldType.NAME:
            if is_business_name(value):
                _add(c.businesses, normalise_business(value), value)
            else:
                _add(c.person_names, normalise_name(value), value)
        elif f.field == FieldType.ALIAS:
            _add(c.person_names, normalise_name(value), value)
        elif f.field == FieldType.BUSINESS:
            _add(c.businesses, normalise_business(value), value)
        elif f.field == FieldType.ORGANIZATION:
            _add(c.organizations, normalise_business(value), value)
        elif f.field == FieldType.EMAIL:
            _add(c.emails, normalise_email(f.normalized_value or value), value.lower())
        elif f.field == FieldType.USERNAME:
            platform, user = _platform_and_user(f, source)
            _add(c.usernames, f"{platform}:{user}", f"{platform}:{user}")
        elif f.field == FieldType.SOCIAL_PROFILE:
            platform, user = _platform_and_user(f, source)
            if user:
                _add(c.profiles, f"{platform}:{user}", value)
        elif f.field == FieldType.WEBSITE:
            _add(c.websites, normalise_domain(f.normalized_value or value), normalise_domain(value))
        elif f.field == FieldType.LOCATION:
            city = str((f.metadata or {}).get("city") or f.normalized_value or value)
            _add(c.locations, normalise_city(city), value)
        elif f.field == FieldType.ADDRESS:
            _add(c.addresses, address_hash(value), value)
        elif f.field == FieldType.JOB_TITLE:
            _add(c.job_titles, normalise_business(value), value)
        elif f.field == FieldType.PHONE:
            _add(c.phones, value.replace(" ", ""), value)
    return c


# --------------------------------------------------------------------------- #
# Merge rules
# --------------------------------------------------------------------------- #


def _shared_strong_keys(a: _Cluster, b: _Cluster) -> list[str]:
    return sorted(a.strong_keys() & b.strong_keys())


def _names_conflict(a: _Cluster, b: _Cluster) -> bool:
    """True when either cluster holds a full person name with no fuzzy match on the other side."""
    fa, fb = a.full_person_names(), b.full_person_names()
    if not fa or not fb:
        return False
    for x in fa:
        if not any(names_fuzzy_equal(x, y, NAME_MATCH_THRESHOLD) for y in fb):
            return True
    for y in fb:
        if not any(names_fuzzy_equal(y, x, NAME_MATCH_THRESHOLD) for x in fa):
            return True
    return False


def _fuzzy_name_link(a: _Cluster, b: _Cluster) -> Optional[str]:
    """Return a human reason if the clusters share a fuzzy-equal person or business name."""
    for x in a.person_names:
        for y in b.person_names:
            if names_fuzzy_equal(x, y, NAME_MATCH_THRESHOLD):
                return f"person name '{most_common_variant(a.person_names[x])}' ~ '{most_common_variant(b.person_names[y])}'"
    for table_a, table_b in ((a.businesses, b.businesses), (a.organizations, b.organizations)):
        for x in table_a:
            for y in table_b:
                if x == y or names_fuzzy_equal(x, y, NAME_MATCH_THRESHOLD):
                    return f"business name '{most_common_variant(table_a[x])}' ~ '{most_common_variant(table_b[y])}'"
    return None


def _merge_reason(a: _Cluster, b: _Cluster, sources: dict[str, Source]) -> Optional[str]:
    """Decide whether two clusters describe the same entity; return why, or None."""
    shared = _shared_strong_keys(a, b)
    dom_a = join_human(sorted({_domain_of(s, sources) for s in a.source_ids}))
    dom_b = join_human(sorted({_domain_of(s, sources) for s in b.source_ids}))
    if shared:
        key = shared[0]
        kind, _, val = key.partition(":")
        label = {"email": "e-mail", "username": "username", "website": "website"}[kind]
        reason = f"Shared {label} '{val}' links {dom_a} with {dom_b} (strong key)"
        if _names_conflict(a, b):
            na, nb = a.primary_person_name(), b.primary_person_name()
            reason += f"; both names '{na}' and '{nb}' retained because the strong key matched"
        return reason
    if _names_conflict(a, b):
        return None
    link = _fuzzy_name_link(a, b)
    if link:
        return f"Fuzzy-equal {link} links {dom_a} with {dom_b} (no conflicting person names)"
    return None


def _domain_of(source_id: str, sources: dict[str, Source]) -> str:
    src = sources.get(source_id)
    return display_domain(src.url) if src else source_id


def _merge_clusters(clusters: list[_Cluster], sources: dict[str, Source]) -> list[_Cluster]:
    """Greedy, order-stable merging repeated until no pair can be merged."""
    groups: list[_Cluster] = []
    for c in clusters:
        target: Optional[_Cluster] = None
        for g in groups:
            reason = _merge_reason(g, c, sources)
            if reason:
                target = g
                target.absorb(c)
                target.why_linked.append(reason)
                break
        if target is None:
            groups.append(c)
    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                reason = _merge_reason(groups[i], groups[j], sources)
                if reason:
                    groups[i].absorb(groups[j])
                    groups[i].why_linked.append(reason)
                    del groups[j]
                    changed = True
                    break
            if changed:
                break
    return groups


# --------------------------------------------------------------------------- #
# Entity construction
# --------------------------------------------------------------------------- #


def _display_list(table: dict[str, list[str]]) -> list[str]:
    """Most common display variant per normalised key, ordered by frequency then alphabetically."""
    rows = sorted(table.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    out: list[str] = []
    for _, variants in rows:
        v = most_common_variant(variants)
        if v and v not in out:
            out.append(v)
    return out


def _kind_and_label(c: _Cluster) -> tuple[EntityKind, str]:
    if c.person_names:
        key = c.primary_person_name()
        return EntityKind.PERSON, most_common_variant(c.person_names[key])
    if c.businesses:
        key = _primary(c.businesses)
        return EntityKind.BUSINESS, most_common_variant(c.businesses[key])
    if c.organizations:
        key = _primary(c.organizations)
        return EntityKind.ORGANIZATION, most_common_variant(c.organizations[key])
    if c.emails:
        return EntityKind.UNKNOWN, _primary(c.emails)
    if c.usernames or c.profiles:
        return EntityKind.UNKNOWN, _primary(c.usernames) or _primary(c.profiles)
    if c.websites:
        return EntityKind.UNKNOWN, _primary(c.websites)
    return EntityKind.UNKNOWN, UNRESOLVED_LABEL


def _strongest(findings: Iterable[Finding]) -> Association:
    best = Association.INFERRED
    for f in findings:
        if _ASSOC_RANK[f.association] > _ASSOC_RANK[best]:
            best = f.association
    return best


def _dates(findings: Iterable[Finding], sources: dict[str, Source]) -> tuple[Optional[datetime], Optional[datetime]]:
    dates: list[datetime] = []
    for f in findings:
        d = f.published_at
        if d is None:
            src = sources.get(f.source_id)
            d = src.published_at if src else None
        if d is not None:
            dates.append(d)
    if not dates:
        return None, None
    return min(dates), max(dates)


def _why_sentences(c: _Cluster, sources: dict[str, Source]) -> list[str]:
    """Explain why the evidence was grouped: per key, the independent domains it appears on."""
    sentences: list[str] = []

    def domains_for(pred) -> list[str]:  # type: ignore[no-untyped-def]
        doms: set[str] = set()
        for f in c.findings:
            if pred(f):
                src = sources.get(f.source_id)
                doms.add(display_domain(src.url) if src else f.source_url)
        return sorted(doms)

    def sentence(kind: str, value: str, doms: list[str], with_number: bool) -> str:
        n = len(doms)
        where = f"on {n} independent source{'s' if n != 1 else ''} ({join_human(doms)})"
        return f"{kind} '{value}' appears {'with the number ' if with_number else ''}{where}"

    for key, variants in sorted(c.person_names.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        doms = domains_for(lambda f, k=key: f.field in (FieldType.NAME, FieldType.ALIAS) and normalise_name(f.value) == k)
        displayed = any(f.number_displayed for f in c.findings if f.field == FieldType.NAME and normalise_name(f.value) == key)
        sentences.append(sentence("Name", most_common_variant(variants), doms, displayed))
    for key, variants in sorted(c.businesses.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        doms = domains_for(lambda f, k=key: f.field in (FieldType.BUSINESS, FieldType.NAME) and normalise_business(f.value) == k)
        displayed = any(f.number_displayed for f in c.findings if f.field in (FieldType.BUSINESS, FieldType.NAME) and normalise_business(f.value) == key)
        sentences.append(sentence("Business", most_common_variant(variants), doms, displayed))
    for key in sorted(c.emails):
        doms = domains_for(lambda f, k=key: f.field == FieldType.EMAIL and normalise_email(f.normalized_value or f.value) == k)
        sentences.append(sentence("E-mail", key, doms, False))
    for key in sorted(c.usernames):
        sentences.append(f"Username '{key}' recorded from a public profile")
    return sentences


def _build_entity(c: _Cluster, sources: dict[str, Source], phone_e164: str) -> Entity:
    kind, label = _kind_and_label(c)
    source_urls = sorted(canonical_url(sources[s].url) if s in sources else s for s in c.source_ids)
    entity_id = stable_id("ent", kind.value, label.lower(), *source_urls)
    findings = c.findings
    ent = Entity(
        entity_id=entity_id,
        kind=kind,
        label=label,
        names=_display_list(c.person_names),
        emails=sorted(c.emails),
        usernames=sorted(set(c.usernames) | set(c.profiles)),
        businesses=_display_list(c.businesses) + [b for b in _display_list(c.organizations) if b not in _display_list(c.businesses)],
        websites=sorted(c.websites),
        locations=_display_list(c.locations),
        addresses=_display_list(c.addresses),
        job_titles=_display_list(c.job_titles),
        associated_numbers=sorted(k for k in c.phones if k != phone_e164),
        finding_ids=[f.finding_id for f in findings],
        source_ids=list(c.source_ids),
        independent_source_count=len({independent_domain(sources[s].url) for s in c.source_ids if s in sources}),
        association=_strongest(findings),
    )
    ent.first_seen, ent.last_seen = _dates(findings, sources)
    ent.why_linked = _why_sentences(c, sources) + list(c.why_linked)
    if label == UNRESOLVED_LABEL:
        ent.why_linked = [
            f"{len(c.source_ids)} public page(s) display the number without an extractable name, e-mail, username or business"
        ] + list(c.why_linked)
    return ent


# --------------------------------------------------------------------------- #
# Relationships
# --------------------------------------------------------------------------- #


def node_id(kind: str, *parts: str) -> str:
    return f"{kind}:{':'.join(p for p in parts if p)}"


def _rel(from_id: str, to_id: str, relation: str, findings: list[Finding], sources: dict[str, Source]) -> Relationship:
    assoc = _strongest(findings) if findings else Association.INFERRED
    first, last = _dates(findings, sources)
    conf = max((f.confidence for f in findings), default=_ASSOC_CONF[assoc])
    return Relationship(
        relationship_id=stable_id("rel", from_id, relation, to_id),
        from_id=from_id,
        to_id=to_id,
        relation=relation,
        finding_ids=[f.finding_id for f in findings],
        source_ids=sorted({f.source_id for f in findings}),
        confidence=round(conf, 3),
        association=assoc,
        first_seen=first,
        last_seen=last,
    )


def _relationships_for(ent: Entity, c: _Cluster, phone_e164: str, sources: dict[str, Source]) -> list[Relationship]:
    ent_node = node_id("ent", ent.entity_id)
    rels: list[Relationship] = []
    direct = [f for f in c.findings if f.number_displayed]
    rels.append(_rel(node_id("phone", phone_e164), ent_node, "HAS_CANDIDATE", direct or c.findings, sources))

    def by(pred) -> list[Finding]:  # type: ignore[no-untyped-def]
        return [f for f in c.findings if pred(f)]

    for key in sorted(c.person_names):
        fs = by(lambda f, k=key: f.field in (FieldType.NAME, FieldType.ALIAS) and normalise_name(f.value) == k)
        rels.append(_rel(ent_node, node_id("name", key), "HAS_NAME", fs, sources))
    for key in sorted(c.emails):
        fs = by(lambda f, k=key: f.field == FieldType.EMAIL and normalise_email(f.normalized_value or f.value) == k)
        rels.append(_rel(ent_node, node_id("email", key), "HAS_EMAIL", fs, sources))
    for key in sorted(c.usernames):
        platform, _, user = key.partition(":")
        fs = by(lambda f, p=platform, u=user: f.field == FieldType.USERNAME and _platform_and_user(f, sources.get(f.source_id)) == (p, u))
        rels.append(_rel(ent_node, node_id("username", platform, user), "HAS_USERNAME", fs, sources))
    for key in sorted(c.profiles):
        platform, _, user = key.partition(":")
        fs = by(lambda f, p=platform, u=user: f.field == FieldType.SOCIAL_PROFILE and _platform_and_user(f, sources.get(f.source_id)) == (p, u))
        rels.append(_rel(ent_node, node_id("profile", platform, user), "HAS_PROFILE", fs, sources))
    for key in sorted(set(c.businesses) | set(c.organizations)):
        fs = by(lambda f, k=key: f.field in (FieldType.BUSINESS, FieldType.ORGANIZATION, FieldType.NAME) and normalise_business(f.value) == k)
        rels.append(_rel(ent_node, node_id("business", key), "RUNS_BUSINESS", fs, sources))
    for key in sorted(c.websites):
        fs = by(lambda f, k=key: f.field == FieldType.WEBSITE and normalise_domain(f.normalized_value or f.value) == k)
        rels.append(_rel(ent_node, node_id("website", key), "HAS_WEBSITE", fs, sources))
    for key in sorted(c.locations):
        fs = by(lambda f, k=key: f.field == FieldType.LOCATION and normalise_city(str((f.metadata or {}).get("city") or f.normalized_value or f.value)) == k)
        rels.append(_rel(ent_node, node_id("location", key), "LOCATED_IN", fs, sources))
    for key in sorted(c.addresses):
        fs = by(lambda f, k=key: f.field == FieldType.ADDRESS and address_hash(f.value) == k)
        rels.append(_rel(ent_node, node_id("address", key), "HAS_ADDRESS", fs, sources))
    for key in sorted(c.job_titles):
        fs = by(lambda f, k=key: f.field == FieldType.JOB_TITLE and normalise_business(f.value) == k)
        rels.append(_rel(ent_node, node_id("jobtitle", key), "HAS_JOB_TITLE", fs, sources))
    for key in sorted(c.phones):
        if key == phone_e164:
            continue
        fs = by(lambda f, k=key: f.field == FieldType.PHONE and f.value.replace(" ", "") == k)
        if any(f.number_displayed for f in fs):  # co-listing requires the subject number on the page
            rels.append(_rel(ent_node, node_id("phone", key), "CO_LISTED_WITH", fs, sources))
    for sid in c.source_ids:
        fs = by(lambda f, s=sid: f.source_id == s)
        rels.append(_rel(ent_node, node_id("doc", sid), "MENTIONED_IN", fs, sources))
    return rels


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def resolve_entities(
    phone: NormalizedPhone, findings: list[Finding], sources: list[Source]
) -> tuple[list[Entity], list[Relationship]]:
    """
    Resolve findings into candidate entities and relationship edges.

    Side effect: ``Finding.entity_id`` is set on the passed findings so downstream modules
    (timeline, co-listed numbers, scoring) can attribute evidence.  Output ordering is
    deterministic: entities by number of DIRECT findings desc, independent sources desc,
    label; the unresolved pseudo-entity always last.
    """
    src_by_id: dict[str, Source] = {s.source_id: s for s in sources}
    phone_e164 = phone.e164

    # 1. one cluster per source (fall back to canonical URL when the source object is unknown)
    grouped: dict[str, list[Finding]] = {}
    for f in findings:
        key = f.source_id if f.source_id in src_by_id else (canonical_url(f.source_url) or f.source_id)
        grouped.setdefault(key, []).append(f)

    def sort_key(k: str) -> tuple[str, str]:
        src = src_by_id.get(k)
        return (canonical_url(src.url) if src else k, k)

    clusters = [
        _cluster_from_source(k, grouped[k], src_by_id.get(k)) for k in sorted(grouped, key=sort_key)
    ]
    clusters = [c for c in clusters if c.findings]

    # 2-3. merge identity-bearing clusters; 4. pool the rest
    identified = [c for c in clusters if c.has_identity()]
    unresolved = [c for c in clusters if not c.has_identity()]
    merged = _merge_clusters(identified, src_by_id)
    if unresolved:
        pool = _Cluster()
        for c in unresolved:
            pool.absorb(c)
        merged.append(pool)

    # 5-6. entities
    entities: list[Entity] = []
    cluster_of: dict[str, _Cluster] = {}
    for c in merged:
        ent = _build_entity(c, src_by_id, phone_e164)
        entities.append(ent)
        cluster_of[ent.entity_id] = c
        for f in c.findings:
            f.entity_id = ent.entity_id

    def order(e: Entity) -> tuple[int, int, int, str]:
        direct = sum(1 for f in cluster_of[e.entity_id].findings if f.association == Association.DIRECT)
        return (1 if e.label == UNRESOLVED_LABEL else 0, -direct, -e.independent_source_count, e.label.lower())

    entities.sort(key=order)

    # 7. relationships
    relationships: list[Relationship] = []
    for ent in entities:
        relationships.extend(_relationships_for(ent, cluster_of[ent.entity_id], phone_e164, src_by_id))

    log.info(
        "entity resolution complete",
        phone=mask_phone(phone_e164),
        clusters=len(clusters),
        entities=len(entities),
        relationships=len(relationships),
    )
    return entities, relationships


def attach_derived_objects(
    entities: list[Entity],
    social_profiles: list[SocialProfile],
    businesses: list[Business],
    documents: list[Document],
    addresses: list[Address],
) -> None:
    """Set ``entity_id`` on derived objects whose ``finding_ids`` intersect an entity's; fill entity id lists."""
    owner: dict[str, Entity] = {}
    for e in entities:
        for fid in e.finding_ids:
            owner.setdefault(fid, e)

    def entity_for(finding_ids: list[str]) -> Optional[Entity]:
        for fid in finding_ids:
            if fid in owner:
                return owner[fid]
        return None

    for p in social_profiles:
        e = entity_for(p.finding_ids)
        if e is not None:
            p.entity_id = e.entity_id
            if p.profile_id not in e.social_profile_ids:
                e.social_profile_ids.append(p.profile_id)
    for b in businesses:
        e = entity_for(b.finding_ids)
        if e is not None:
            b.entity_id = e.entity_id
    for d in documents:
        e = entity_for(d.finding_ids)
        if e is not None:
            d.entity_id = e.entity_id
            if d.document_id not in e.document_ids:
                e.document_ids.append(d.document_id)
    for a in addresses:
        e = entity_for(a.finding_ids)
        if e is not None:
            a.entity_id = e.entity_id


__all__ = ["resolve_entities", "attach_derived_objects", "node_id", "UNRESOLVED_LABEL", "NAME_MATCH_THRESHOLD"]
