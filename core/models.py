"""
Core data models for the Indian Phone OSINT Research Engine.

Every module in the project speaks in terms of these models.  They are
deliberately explicit about *provenance* (where a piece of information came
from), *association strength* (direct / indirect / inferred) and *confidence*
(a transparent, explainable score).  Nothing in the system may store a
conclusion without a Finding that carries its evidence.

Naming conventions
------------------
* ``*_id`` fields are short, stable, URL-safe identifiers (see ``new_id``).
* All timestamps are timezone-aware UTC ``datetime`` objects.
* ``phone`` values are always E.164 (``+919876543210``) unless a field name
  says otherwise (``masked``, ``raw``, ``national``...).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

ENGINE_VERSION = "0.1.0"

DISCLAIMER = (
    "This report contains information discovered from publicly accessible or "
    "authorized sources. Public-source associations are not proof of identity. "
    "Information may be outdated, inaccurate, duplicated, or associated with "
    "another person who previously used the number."
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "id") -> str:
    """Short, URL-safe, collision-resistant identifier such as ``fnd_9f3a2c1b``."""
    return f"{prefix}_{secrets.token_hex(4)}"


def stable_id(prefix: str, *parts: str) -> str:
    """Deterministic identifier derived from content (used for dedup keys)."""
    digest = hashlib.sha1("\x1f".join(p.lower().strip() for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:10]}"


def mask_phone(e164_or_digits: str) -> str:
    """``+919876543210`` -> ``+91******3210``.  Used in logs and UI previews."""
    s = e164_or_digits.strip()
    if not s:
        return s
    prefix = "+91" if s.startswith("+91") else ("+" if s.startswith("+") else "")
    digits = "".join(ch for ch in s if ch.isdigit())
    if s.startswith("+91"):
        digits = digits[2:]
    if len(digits) <= 4:
        return prefix + "*" * len(digits)
    return f"{prefix}{'*' * (len(digits) - 4)}{digits[-4:]}"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class Depth(str, Enum):
    QUICK = "quick"  # phone intel + exact-match search
    STANDARD = "standard"  # + business + social + documents (single expansion round)
    DEEP = "deep"  # everything configured + recursive lead expansion


class SourceQuality(str, Enum):
    A = "A"  # official / public primary source (government registry, company's own site)
    B = "B"  # reputable secondary source (news, established professional network)
    C = "C"  # established directory (Justdial, IndiaMART, Google Business listing)
    D = "D"  # user-generated public source (forums, classifieds, social posts)
    E = "E"  # unknown / unreliable


class ConfidenceLabel(str, Enum):
    FACT = "FACT"  # confirmed public fact: number literally displayed by an A/B source
    STRONG_MATCH = "STRONG_MATCH"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    WEAK_ASSOCIATION = "WEAK_ASSOCIATION"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTORY = "CONTRADICTORY"


class Association(str, Enum):
    DIRECT = "direct"  # number is literally displayed on the page/profile/document
    INDIRECT = "indirect"  # number appears on a page/post/document connected to the entity
    INFERRED = "inferred"  # name + location + business + number correlate; never auto-upgraded


class SourceType(str, Enum):
    SEARCH_ENGINE = "search_engine"
    SOCIAL_PROFILE = "social_profile"
    BUSINESS_DIRECTORY = "business_directory"
    COMPANY_WEBSITE = "company_website"
    GOVERNMENT_REGISTRY = "government_registry"
    COURT_RECORD = "court_record"
    TENDER = "tender"
    DOCUMENT = "document"
    CLASSIFIED_LISTING = "classified_listing"
    MARKETPLACE = "marketplace"
    NEWS = "news"
    FORUM = "forum"
    BLOG = "blog"
    VIDEO = "video"
    CODE_REPOSITORY = "code_repository"
    MAPS = "maps"
    TELECOM_API = "telecom_api"
    NUMBERING_PLAN = "numbering_plan"
    IMAGE_SEARCH = "image_search"
    OTHER = "other"


class FieldType(str, Enum):
    NAME = "name"
    EMAIL = "email"
    USERNAME = "username"
    BUSINESS = "business"
    ORGANIZATION = "organization"
    WEBSITE = "website"
    LOCATION = "location"  # city / state level
    ADDRESS = "address"  # street-level string
    PHONE = "phone"  # an associated public number (never the subject number itself)
    DOCUMENT = "document"
    SOCIAL_PROFILE = "social_profile"
    JOB_TITLE = "job_title"
    IMAGE = "image"
    ALIAS = "alias"
    CATEGORY = "category"
    LISTING = "listing"
    MENTION = "mention"  # the subject phone appears on a page with no other extractable entity
    TELECOM = "telecom"


class EntityKind(str, Enum):
    PERSON = "person"
    BUSINESS = "business"
    ORGANIZATION = "organization"
    UNKNOWN = "unknown"


class PhoneKind(str, Enum):
    MOBILE = "mobile"
    FIXED_LINE = "fixed_line"
    FIXED_LINE_OR_MOBILE = "fixed_line_or_mobile"
    TOLL_FREE = "toll_free"
    PREMIUM_RATE = "premium_rate"
    SHARED_COST = "shared_cost"
    VOIP = "voip"
    UAN = "uan"
    SERVICE = "service"  # short codes / special service numbers
    TELEMARKETING = "telemarketing"  # 140 / 160 series (TRAI)
    M2M = "m2m"  # 13-digit machine-to-machine
    UNKNOWN = "unknown"
    INVALID = "invalid"


class AddressClass(str, Enum):
    RESIDENTIAL_LOOKING = "residential_looking"
    COMMERCIAL = "commercial"
    OFFICE = "office"
    REGISTERED_BUSINESS = "registered_business"
    PUBLIC_INSTITUTION = "public_institution"
    UNKNOWN = "unknown"


class ContradictionKind(str, Enum):
    NAME_CONFLICT = "name_conflict"
    LOCATION_CONFLICT = "location_conflict"
    BUSINESS_CONFLICT = "business_conflict"
    ENTITY_KIND_CONFLICT = "entity_kind_conflict"
    TEMPORAL_CHANGE = "temporal_change"  # public association changed over time
    OWNERSHIP_CONFLICT = "ownership_conflict"  # evidence that the number belongs to someone else


class DatePrecision(str, Enum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    UNKNOWN = "unknown"


class LeadType(str, Enum):
    NAME = "name"
    EMAIL = "email"
    USERNAME = "username"
    BUSINESS = "business"
    DOMAIN = "domain"
    PHONE = "phone"
    ADDRESS = "address"


class Stage(str, Enum):
    NORMALIZE = "normalize"
    TELECOM = "telecom"
    SEARCH = "search"
    DOCUMENTS = "documents"
    SOCIAL = "social"
    BUSINESS = "business"
    REGISTRIES = "registries"
    CLASSIFIEDS = "classifieds"
    PAGE_FETCH = "page_fetch"
    EXTRACTION = "extraction"
    LEAD_EXPANSION = "lead_expansion"
    CORRELATION = "correlation"
    SCORING = "scoring"
    REPORT = "report"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class ProviderState(str, Enum):
    AVAILABLE = "available"
    MISSING_KEY = "missing_key"
    DISABLED = "disabled"
    NOT_INSTALLED = "not_installed"
    ERROR = "error"


# --------------------------------------------------------------------------- #
# Phone normalisation
# --------------------------------------------------------------------------- #


class NormalizedPhone(BaseModel):
    """Result of ``core.normalize.normalize_indian_number``."""

    raw: str
    e164: str = ""  # +919876543210
    national: str = ""  # 098765 43210 (libphonenumber national format)
    international: str = ""  # +91 98765 43210
    subscriber: str = ""  # 9876543210 (national significant number)
    country_code: int = 91
    region: str = "IN"
    is_valid: bool = False
    is_possible: bool = False
    kind: PhoneKind = PhoneKind.UNKNOWN
    is_indian: bool = False
    masked: str = ""
    variants: list[str] = Field(default_factory=list)  # search variants, most specific first
    quoted_variants: list[str] = Field(default_factory=list)  # '"9876543210"' etc.
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.is_valid and self.is_indian


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


class Source(BaseModel):
    """A distinct public location (URL) that was consulted or surfaced."""

    source_id: str = Field(default_factory=lambda: new_id("src"))
    url: str
    canonical_url: str = ""
    domain: str = ""
    title: str = ""
    source_type: SourceType = SourceType.OTHER
    quality: SourceQuality = SourceQuality.E
    provider: str = ""  # search/collector provider that surfaced it
    retrieved_at: datetime = Field(default_factory=utcnow)
    published_at: Optional[datetime] = None
    date_precision: DatePrecision = DatePrecision.UNKNOWN
    http_status: Optional[int] = None
    content_hash: str = ""  # sha256 of relevant text, when fetched
    excerpt: str = ""  # snippet / relevant excerpt (bounded, never the whole page)
    fetched: bool = False  # True if we fetched the page body (robots permitting)
    robots_allowed: Optional[bool] = None
    referenced_by: list[str] = Field(default_factory=list)  # provider/query ids that also returned it
    extra: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Raw result from a SearchProvider, before dedup / extraction."""

    url: str
    title: str = ""
    snippet: str = ""
    provider: str = ""
    query: str = ""
    query_id: str = ""
    rank: int = 0
    published_at: Optional[datetime] = None
    file_type: str = ""  # pdf / xls / doc ... when known
    extra: dict[str, Any] = Field(default_factory=dict)


class QueryRecord(BaseModel):
    """One executed search query (kept for the report's 'queries used' section)."""

    query_id: str = Field(default_factory=lambda: new_id("qry"))
    provider: str
    query: str
    stage: Stage = Stage.SEARCH
    purpose: str = ""  # e.g. "exact phone match", "lead: name=Rahul Sharma"
    lead_id: Optional[str] = None
    executed_at: datetime = Field(default_factory=utcnow)
    results_count: int = 0
    new_results_count: int = 0
    information_gain: float = 0.0  # new_unique / max(results,1)
    cached: bool = False
    error: Optional[str] = None


# --------------------------------------------------------------------------- #
# Findings (the atomic evidence record - section 24 of the specification)
# --------------------------------------------------------------------------- #


class Finding(BaseModel):
    finding_id: str = Field(default_factory=lambda: new_id("fnd"))
    phone: str  # subject phone, E.164
    entity_id: Optional[str] = None  # assigned by entity resolution
    field: FieldType
    value: str
    normalized_value: str = ""  # lowercased / canonical form used for matching
    source_id: str
    source_url: str
    source_type: SourceType = SourceType.OTHER
    source_quality: SourceQuality = SourceQuality.E
    evidence_text: str = ""  # exact matching text, bounded to ~500 chars
    discovered_at: datetime = Field(default_factory=utcnow)
    published_at: Optional[datetime] = None
    date_precision: DatePrecision = DatePrecision.UNKNOWN
    confidence: float = 0.5  # 0..1 extraction confidence (NOT identity confidence)
    association: Association = Association.DIRECT
    number_displayed: bool = True  # is the subject number literally present in the source text?
    provider: str = ""
    query_id: Optional[str] = None
    extractor: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_text")
    @classmethod
    def _bound_evidence(cls, v: str) -> str:
        return v[:600]

    def dedup_key(self) -> str:
        return stable_id("fk", self.field.value, self.normalized_value or self.value, self.source_url)


class TelecomResult(BaseModel):
    """Section 4: every telecom provider result is a (provider, field, value, confidence) record."""

    provider: str
    timestamp: datetime = Field(default_factory=utcnow)
    field: str
    value: str
    confidence: float = 0.5
    note: str = ""  # e.g. "numbering-plan allocation only; MNP means current carrier may differ"
    raw: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Derived objects
# --------------------------------------------------------------------------- #


class SocialProfile(BaseModel):
    profile_id: str = Field(default_factory=lambda: new_id("prf"))
    platform: str
    username: str = ""
    display_name: str = ""
    profile_url: str = ""
    source_url: str = ""
    matching_text: str = ""
    discovered_at: datetime = Field(default_factory=utcnow)
    confidence: float = 0.5
    number_displayed: bool = False
    association: Association = Association.INDIRECT
    finding_ids: list[str] = Field(default_factory=list)
    entity_id: Optional[str] = None


class Address(BaseModel):
    address_id: str = Field(default_factory=lambda: new_id("adr"))
    raw: str
    city: str = ""
    state: str = ""
    pincode: str = ""
    classification: AddressClass = AddressClass.UNKNOWN
    classification_reason: str = ""
    source_id: str = ""
    finding_ids: list[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    date_precision: DatePrecision = DatePrecision.UNKNOWN
    entity_id: Optional[str] = None


class Location(BaseModel):
    """City / state level location (coarser than Address)."""

    location_id: str = Field(default_factory=lambda: new_id("loc"))
    city: str = ""
    state: str = ""
    country: str = "India"
    label: str = ""
    finding_ids: list[str] = Field(default_factory=list)
    source_count: int = 0
    entity_id: Optional[str] = None


class Business(BaseModel):
    business_id: str = Field(default_factory=lambda: new_id("biz"))
    name: str
    owner: str = ""  # proprietor / owner only if publicly stated
    category: str = ""
    address: str = ""
    city: str = ""
    website: str = ""
    email: str = ""
    social_urls: list[str] = Field(default_factory=list)
    other_numbers: list[str] = Field(default_factory=list)  # E.164, publicly co-listed only
    source_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    entity_id: Optional[str] = None


class Listing(BaseModel):
    """Classified / marketplace listing."""

    listing_id: str = Field(default_factory=lambda: new_id("lst"))
    title: str
    seller_name: str = ""
    category: str = ""
    location: str = ""
    url: str
    published_at: Optional[datetime] = None
    other_contacts: list[str] = Field(default_factory=list)
    source_id: str = ""
    finding_ids: list[str] = Field(default_factory=list)
    entity_id: Optional[str] = None


class Document(BaseModel):
    document_id: str = Field(default_factory=lambda: new_id("doc"))
    title: str = ""
    url: str
    doc_type: str = ""  # pdf / xls / xlsx / doc / docx / ppt / pptx / html
    author: str = ""
    organization: str = ""
    published_at: Optional[datetime] = None
    date_precision: DatePrecision = DatePrecision.UNKNOWN
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    fetched: bool = False
    content_hash: str = ""
    source_id: str = ""
    finding_ids: list[str] = Field(default_factory=list)
    entity_id: Optional[str] = None


class AssociatedNumber(BaseModel):
    """Section 20: a number publicly co-listed with the same entity.  NEVER inferred."""

    e164: str
    masked: str = ""
    relation: str = "publicly_co_listed"
    reason: str = ""
    source_id: str
    source_url: str = ""
    finding_id: str = ""
    entity_id: Optional[str] = None
    confidence: float = 0.8
    discovered_at: datetime = Field(default_factory=utcnow)
    published_at: Optional[datetime] = None


class Lead(BaseModel):
    """A candidate entity that may deserve its own searches (section 8/32)."""

    lead_id: str = Field(default_factory=lambda: new_id("lead"))
    lead_type: LeadType
    value: str
    normalized_value: str = ""
    relevance: float = 0.0  # scoring.relevance.score_lead
    depth: int = 0
    origin_finding_ids: list[str] = Field(default_factory=list)
    investigated: bool = False
    queries_run: int = 0
    information_gain: float = 0.0
    reasons: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Scoring / entities / graph
# --------------------------------------------------------------------------- #


class ScoreComponent(BaseModel):
    rule: str  # e.g. "exact_phone_match"
    points: int  # +40 / -30 ...
    reason: str
    finding_ids: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    components: list[ScoreComponent] = Field(default_factory=list)
    total_points: int = 0
    percent: int = 0  # 0..100 normalised analytical estimate
    label: ConfidenceLabel = ConfidenceLabel.UNVERIFIED
    note: str = "Analytical estimate derived from public-source evidence; not factual certainty."


class Entity(BaseModel):
    """A candidate identity (person / business / organisation) resolved from findings."""

    entity_id: str = Field(default_factory=lambda: new_id("ent"))
    kind: EntityKind = EntityKind.UNKNOWN
    label: str = ""  # primary display name
    names: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    usernames: list[str] = Field(default_factory=list)
    businesses: list[str] = Field(default_factory=list)
    websites: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)
    associated_numbers: list[str] = Field(default_factory=list)
    social_profile_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    independent_source_count: int = 0  # distinct registrable domains
    association: Association = Association.INFERRED  # best (strongest) association across findings
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    contradiction_ids: list[str] = Field(default_factory=list)
    why_linked: list[str] = Field(default_factory=list)  # human-readable reasons


class Relationship(BaseModel):
    """Graph edge with provenance."""

    relationship_id: str = Field(default_factory=lambda: new_id("rel"))
    from_id: str  # node id (phone:+91..., ent_xxx, email:..., ...)
    to_id: str
    relation: str  # HAS_NAME / HAS_EMAIL / HAS_USERNAME / RUNS_BUSINESS / LOCATED_IN / CO_LISTED_WITH / MENTIONED_IN ...
    finding_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    association: Association = Association.INFERRED
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None


class Contradiction(BaseModel):
    contradiction_id: str = Field(default_factory=lambda: new_id("ctr"))
    kind: ContradictionKind
    description: str
    entity_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    severity: str = "medium"  # low / medium / high
    resolution_hint: str = ""  # what an investigator should check


class TimelineEvent(BaseModel):
    date: Optional[datetime] = None
    precision: DatePrecision = DatePrecision.UNKNOWN
    description: str
    finding_id: str = ""
    source_id: str = ""
    source_url: str = ""
    entity_id: Optional[str] = None
    kind: str = "public_mention"


# --------------------------------------------------------------------------- #
# Investigation configuration & progress
# --------------------------------------------------------------------------- #


class InvestigationConfig(BaseModel):
    phone_raw: str
    depth: Depth = Depth.STANDARD
    max_depth: int = 2  # lead-expansion recursion depth
    providers: Optional[list[str]] = None  # restrict to these provider names (None = all available)
    enable_telecom: bool = True
    enable_social: bool = True
    enable_documents: bool = True
    enable_business: bool = True
    enable_registries: bool = True
    enable_classifieds: bool = True
    enable_page_fetch: bool = True  # fetch top pages (robots.txt permitting) for full-text extraction
    enable_username_enum: bool = False  # Maigret-style public profile checks (opt-in)
    enable_image_search: bool = False
    max_queries: int = 60
    max_leads: int = 12
    max_pages_to_fetch: int = 15
    info_gain_threshold: float = 0.15
    results_per_query: int = 10
    cities: list[str] = Field(default_factory=list)  # optional city hints for India-oriented queries
    offline: bool = False  # use only the fixture provider (demo / tests)
    fixture_path: Optional[str] = None
    output_dir: str = "output"
    formats: list[str] = Field(default_factory=lambda: ["json", "markdown", "html", "csv"])
    authorization_note: str = ""  # who authorised this investigation and why (stored in report metadata)
    case_reference: str = ""

    @classmethod
    def for_depth(cls, phone_raw: str, depth: Depth, **overrides: Any) -> "InvestigationConfig":
        presets: dict[Depth, dict[str, Any]] = {
            Depth.QUICK: dict(max_depth=0, max_queries=12, max_leads=0, max_pages_to_fetch=0,
                              enable_documents=False, enable_social=False, enable_business=False,
                              enable_registries=False, enable_classifieds=False, enable_page_fetch=False),
            Depth.STANDARD: dict(max_depth=1, max_queries=60, max_leads=8, max_pages_to_fetch=15),
            Depth.DEEP: dict(max_depth=3, max_queries=150, max_leads=25, max_pages_to_fetch=40,
                             enable_username_enum=True),
        }
        params = {**presets[depth], **overrides}
        return cls(phone_raw=phone_raw, depth=depth, **params)


class ProgressEvent(BaseModel):
    stage: Stage
    status: StageStatus
    message: str = ""
    counts: dict[str, int] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)


class StageResult(BaseModel):
    stage: Stage
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    message: str = ""
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class ProviderInfo(BaseModel):
    name: str
    category: str
    state: ProviderState
    paid: bool = False
    reason: str = ""
    docs_url: str = ""


# --------------------------------------------------------------------------- #
# Top-level investigation result (section 31 JSON schema)
# --------------------------------------------------------------------------- #


class InvestigationMeta(BaseModel):
    investigation_id: str = Field(default_factory=lambda: new_id("inv"))
    engine_version: str = ENGINE_VERSION
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    depth: Depth = Depth.STANDARD
    disclaimer: str = DISCLAIMER
    authorization_note: str = ""
    case_reference: str = ""
    providers: list[ProviderInfo] = Field(default_factory=list)
    stages: list[StageResult] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class ExecutiveSummary(BaseModel):
    candidate_identity: str = ""
    candidate_kind: EntityKind = EntityKind.UNKNOWN
    confidence_percent: int = 0
    confidence_label: ConfidenceLabel = ConfidenceLabel.UNVERIFIED
    possible_location: str = ""
    public_businesses: int = 0
    public_emails: int = 0
    public_usernames: int = 0
    public_profiles: int = 0
    public_documents: int = 0
    associated_public_numbers: int = 0
    candidate_count: int = 0
    contradiction_count: int = 0
    sources_consulted: int = 0
    queries_executed: int = 0
    headline: str = ""  # one-paragraph honest summary


class ConfidenceSummary(BaseModel):
    top_entity_id: Optional[str] = None
    top_percent: int = 0
    top_label: ConfidenceLabel = ConfidenceLabel.UNVERIFIED
    rules: dict[str, int] = Field(default_factory=dict)  # rule -> points table used
    per_entity: dict[str, int] = Field(default_factory=dict)
    note: str = "Scores are analytical estimates, not factual certainty."


class Investigation(BaseModel):
    """The complete, machine-readable investigation result."""

    investigation: InvestigationMeta = Field(default_factory=InvestigationMeta)
    phone: NormalizedPhone
    telecom: list[TelecomResult] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    usernames: list[str] = Field(default_factory=list)
    social_profiles: list[SocialProfile] = Field(default_factory=list)
    businesses: list[Business] = Field(default_factory=list)
    listings: list[Listing] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    addresses: list[Address] = Field(default_factory=list)
    documents: list[Document] = Field(default_factory=list)
    associated_numbers: list[AssociatedNumber] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    queries: list[QueryRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    leads: list[Lead] = Field(default_factory=list)
    confidence: ConfidenceSummary = Field(default_factory=ConfidenceSummary)
    summary: ExecutiveSummary = Field(default_factory=ExecutiveSummary)
    graph: dict[str, Any] = Field(default_factory=dict)  # networkx node-link JSON
    limitations: list[str] = Field(default_factory=list)

    # convenience -------------------------------------------------------- #
    def source_by_id(self, source_id: str) -> Optional[Source]:
        return next((s for s in self.sources if s.source_id == source_id), None)

    def finding_by_id(self, finding_id: str) -> Optional[Finding]:
        return next((f for f in self.findings if f.finding_id == finding_id), None)

    def entity_by_id(self, entity_id: str) -> Optional[Entity]:
        return next((e for e in self.entities if e.entity_id == entity_id), None)

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)
