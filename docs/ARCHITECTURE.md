# Architecture

Indian Phone Number OSINT Research Engine — lawful, public-source only.

```
+91XXXXXXXXXX
    │
    ▼
core.normalize ──► NormalizedPhone (E.164, variants, kind, warnings)
    │
    ▼
core.engine.InvestigationEngine
    │  builds ProviderRegistry (only configured providers), HttpClient (rate-limited, cached,
    │  robots-aware), EvidenceSink, QueryPlanner, SearchBudget
    │
    ├─ Stage TELECOM        collectors.telecom      → TelecomResult[]           (providers.phone.*)
    ├─ Stage SEARCH         collectors.search       → Source[] + Finding[]      (providers.search.*)
    ├─ Stage DOCUMENTS      collectors.documents    → Document[]                (filetype: dorks + safe fetch)
    ├─ Stage SOCIAL         collectors.social       → SocialProfile[]           (site: dorks + username providers)
    ├─ Stage BUSINESS       collectors.business     → Business[]                (dorks + providers.business.*)
    ├─ Stage REGISTRIES     collectors.registries   → Source/Finding            (dorks + providers.registry.*)
    ├─ Stage CLASSIFIEDS    collectors.classifieds  → Listing[]
    ├─ Stage PAGE_FETCH     collectors.page_fetch   → full-text extraction of top sources (robots permitting)
    ├─ Stage LEAD_EXPANSION collectors.leads        → recursive lead queries until information gain < threshold
    ├─ Stage CORRELATION    correlation.*           → Entity[], Relationship[], Contradiction[], Timeline, AssociatedNumber[]
    ├─ Stage SCORING        scoring.*               → ScoreBreakdown per entity, ConfidenceSummary, ExecutiveSummary
    └─ Stage REPORT         reports.*, storage.*    → JSON / Markdown / HTML / CSV / (PDF), SQLite evidence store
```

Everything flows through **`core.models`** — read it first. The rules below are the contract
between modules so they can be built independently and integrate without surprises.

---

## 1. Layering and dependency rules

| Layer         | May import                                  | Must NOT import                  |
|---------------|---------------------------------------------|----------------------------------|
| `config`      | stdlib, pydantic                            | anything else                    |
| `core`        | config, storage.cache, providers.base (registry only) | collectors, reports, ui |
| `providers`   | config, core.models, core.http, core.logging, providers.base | collectors, correlation, reports |
| `extractors`  | core.models, core.normalize, core.logging   | providers, collectors            |
| `collectors`  | core.*, providers.base, extractors, scoring.relevance/information_gain, storage | reports, ui |
| `correlation` | core.models, extractors (for normalisation helpers) | providers, collectors      |
| `scoring`     | core.models                                 | providers, collectors            |
| `reports`     | core.models                                 | providers, collectors            |
| `storage`     | core.models (evidence_store), stdlib        | providers, collectors            |
| `ui`, `main`  | everything                                  | —                                |

All network access goes through `core.http.HttpClient`. No module may create its own
`httpx`/`requests` client. No module may read environment variables directly — use `Settings`.

## 2. Key shared objects

### `core.evidence.EvidenceSink` (engine-owned in-memory store, built by the engine builder)

```python
class EvidenceSink:
    phone: NormalizedPhone
    sources: dict[str, Source]           # by source_id
    findings: dict[str, Finding]         # by finding_id
    queries: list[QueryRecord]
    leads: dict[str, Lead]               # by lead_id
    telecom: list[TelecomResult]
    social_profiles: list[SocialProfile]
    businesses: list[Business]
    listings: list[Listing]
    documents: list[Document]
    raw_results: list[SearchResult]

    def add_source(self, url: str, *, title="", provider="", snippet="", published_at=None,
                   source_type=None, quality=None, extra=None) -> tuple[Source, bool]
        # canonicalises URL (extractors.url_utils.canonical_url), dedups by canonical_url,
        # auto-classifies type/quality via scoring.source_quality.classify_source when not given,
        # appends provider to referenced_by, returns (source, is_new)
    def add_finding(self, finding: Finding) -> tuple[Finding, bool]      # dedup by finding.dedup_key()
    def add_lead(self, lead: Lead) -> tuple[Lead, bool]                  # dedup by (lead_type, normalized_value)
    def add_query(self, record: QueryRecord) -> None
    def seen_url(self, url: str) -> bool
    def findings_for_source(self, source_id: str) -> list[Finding]
    def counts(self) -> dict[str, int]
```

### `core.strategy` — query planning (spec sections 5, 8, 32)

```python
class PlannedQuery(BaseModel):
    query: str
    stage: Stage
    purpose: str                    # "exact phone match" | "social:linkedin" | "documents:pdf" | "lead:name" ...
    branch: str                     # information-gain branch key, e.g. "exact", "social", "docs", "lead:<lead_id>"
    lead_id: Optional[str] = None
    priority: float = 1.0           # higher first
    requires_site_operator: bool = False
    requires_filetype_operator: bool = False

class QueryPlanner:
    def __init__(self, config: InvestigationConfig, phone: NormalizedPhone): ...
    def exact_match_queries(self) -> list[PlannedQuery]         # quoted variants; QUICK=4, STANDARD=7, DEEP=all
    def social_queries(self) -> list[PlannedQuery]              # site:linkedin.com "<n>" etc. (platform table)
    def business_queries(self) -> list[PlannedQuery]            # "<n>" business/owner/proprietor/contact + site:justdial.com, indiamart.com, tradeindia.com, sulekha.com
    def document_queries(self) -> list[PlannedQuery]            # "<n>" filetype:pdf|xls|xlsx|doc|docx|ppt|pptx
    def registry_queries(self) -> list[PlannedQuery]            # site:indiankanoon.org, site:*.gov.in, site:eprocure.gov.in, site:*.nic.in, RERA, MCA aggregator sites
    def classified_queries(self) -> list[PlannedQuery]          # site:olx.in, quikr.com, 99acres.com, magicbricks.com, housing.com, cardekho.com, sulekha.com, indiamart...
    def india_queries(self) -> list[PlannedQuery]               # "<n>" India, "+91 <n>", "<n>" <city> for config.cities
    def lead_queries(self, lead: Lead, context: "LeadContext") -> list[PlannedQuery]
        # NAME: "<name>" "<phone>", "<name>" <city>, "<name>" <business>, "<name>" email, site:linkedin.com "<name>" <city>, ...
        # EMAIL: "<email>", site:linkedin.com "<email>", site:github.com "<email>"
        # USERNAME: "<username>", "<username>" India, site:github.com "<username>", site:instagram.com "<username>", ...
        # BUSINESS: "<business>" "<phone>", "<business>" <city>, "<business>" owner, "<business>" contact
        # DOMAIN: site:<domain> contact, "<domain>" "<phone>"
        # Bounded: at most N queries per lead (N depends on depth and lead.relevance)

class LeadContext(BaseModel):
    cities: list[str]; businesses: list[str]; names: list[str]; emails: list[str]; domains: list[str]

class SearchBudget:
    def __init__(self, max_queries: int, info_gain_threshold: float, min_queries_per_branch: int = 2)
    def can_run(self) -> bool
    def record(self, branch: str, results: int, new_results: int) -> float   # returns gain, updates branch stats
    def branch_exhausted(self, branch: str) -> bool     # avg gain of last 2 queries in branch < threshold
    def stats(self) -> dict
```

The engine runs a query only if `budget.can_run()` and not `budget.branch_exhausted(pq.branch)`.
Information gain for a query = `new_unique_sources / max(results, 1)` (spec 32).

### Extraction entry point (`extractors.page_extractor`)

```python
class Extraction(BaseModel):
    findings: list[Finding]
    number_displayed: bool          # subject number literally found (any variant) in the text
    other_numbers: list[str]        # other Indian numbers (E.164) found in same text (for co-listing)
    leads: list[Lead]               # candidate leads derived from findings (relevance unscored = 0)

def extract_from_text(text: str, *, phone: NormalizedPhone, source: Source, query_id: str | None = None,
                      title: str = "", url: str = "", is_full_page: bool = False,
                      extractor_tag: str = "snippet") -> Extraction
```

It composes the individual extractors (phones, emails, usernames/profile URLs, names, business names,
addresses/locations, job titles, dates) and emits one `Finding` per (field, value). Every Finding
must carry `evidence_text` (the ±120 chars around the match), `association` (DIRECT if the subject
number is in the same text window / page, INDIRECT if only on the same page but far away, INFERRED
otherwise) and `number_displayed`.

## 3. Provider contract (`providers/base.py`)

* Subclass the right category class; set `name`, `requires`, `paid`, `docs_url`, `rate_per_second`.
* Use `self.http.get_json(...)` for APIs (cached automatically). Never build your own client.
* Convert provider payloads to `SearchResult` / `TelecomResult` / `SocialProfile` / `Business`.
* Never raise on empty results; catch provider errors, append to `self.errors`, log at WARNING
  with the provider name and status **but never the key**, and return `[]`.
* `search()` must apply `max_results`. If the provider does not support `site:`/`filetype:` operators,
  set the class flags to False — the collector will skip such queries for that provider.
* `state`/`available` come from the base class using `requires`. Override `extra_state_check()`
  only for binaries/packages/URLs (PhoneInfoga, Maigret, SearXNG).
* Provider names are stable identifiers used in `--providers`: see `providers/catalog.py`.

## 4. Collector contract (`collectors/base.py`)

```python
class CollectorContext:
    config: InvestigationConfig
    phone: NormalizedPhone
    registry: ProviderRegistry
    http: HttpClient
    sink: EvidenceSink
    planner: QueryPlanner
    budget: SearchBudget
    progress: Callable[[ProgressEvent], None]
    settings: Settings

class BaseCollector(ABC):
    name: str
    stage: Stage
    async def run(self, ctx: CollectorContext) -> StageResult

async def run_planned_queries(ctx, queries: list[PlannedQuery], *, stage: Stage,
                              extract: bool = True) -> list[SearchResult]
    # shared helper (collectors/base.py): for each query and each enabled search provider:
    #   respects budget/branch exhaustion, provider operator support, records QueryRecord with
    #   information_gain, adds Sources, runs extract_from_text on title+snippet, adds Findings/Leads.
```

Collectors never call `http` for pages except `PageFetchCollector` and `DocumentCollector`, which
must use `http.fetch_page` (robots.txt enforced) and must only fetch `Source`s that were surfaced
by a search provider (never crawl).

## 5. Correlation contract

```python
# correlation/dedup.py
def dedup_sources(sources: list[Source]) -> list[Source]           # merge by canonical_url; merge referenced_by; keep best quality
def dedup_findings(findings: list[Finding]) -> list[Finding]       # by (field, normalized_value, canonical source)
def title_similarity(a: str, b: str) -> float                       # 0..1 (difflib ratio on normalised titles)

# correlation/entity_resolver.py
def resolve_entities(phone: NormalizedPhone, findings: list[Finding], sources: list[Source]) -> tuple[list[Entity], list[Relationship]]
#   1. group findings by source → one "mention cluster" per source
#   2. merge clusters when they share a strong key (normalised email, username+platform, website domain)
#      or a fuzzy-equal person/business name (token-set ratio ≥ 0.85) AND no conflicting name in either cluster
#   3. never merge clusters with different person names unless a strong key is shared
#   4. clusters with no name/email/username/business become the "unresolved mentions" pseudo-entity (kind UNKNOWN, label "Unattributed public mentions")
#   5. set Entity.kind (BUSINESS if label matches business suffix table or only BUSINESS findings; PERSON if person-name; else UNKNOWN)
#   6. fill Entity lists, finding_ids, source_ids, independent_source_count (distinct registrable domains), association = strongest association among findings, first_seen/last_seen from findings.published_at
#   7. emit Relationship edges phone→entity (HAS_CANDIDATE), entity→name/email/username/business/website/location/address (HAS_*), entity→co-listed number (CO_LISTED_WITH)

# correlation/contradictions.py
def detect_contradictions(phone, entities, findings, sources) -> list[Contradiction]
#   NAME_CONFLICT: ≥2 PERSON entities each with a DIRECT finding (number_displayed) from A–D quality sources
#   LOCATION_CONFLICT: same entity with ≥2 different cities from DIRECT findings
#   ENTITY_KIND_CONFLICT: number directly displayed for both a person and an unrelated business
#   TEMPORAL_CHANGE: DIRECT findings for different entities whose published_at differ by ≥ 1 year
#   OWNERSHIP_CONFLICT: evidence_text contains phrases like "not my number", "wrong number", "previous owner", "old number"
#   Never merge; only describe and attach entity/finding ids; add resolution_hint.

# correlation/timeline.py
def build_timeline(findings, sources, entities) -> list[TimelineEvent]   # from published_at (source or finding), sorted, unknown dates last

# correlation/alternate_numbers.py
def find_co_listed_numbers(phone, findings, sources) -> list[AssociatedNumber]
#   Only FieldType.PHONE findings whose source also displays the subject number (number_displayed=True). Never generate numbers.

# correlation/graph.py
class EvidenceGraph:            # networkx.MultiDiGraph wrapper
    def __init__(self, phone: NormalizedPhone)
    def add_entity(self, e: Entity) / add_finding(self, f: Finding, source: Source) / add_relationship(self, r: Relationship)
    def to_node_link(self) -> dict          # nx.node_link_data(G, edges="edges")
    def to_pyvis_html(self) -> str | None   # optional; None if pyvis missing
    def to_ascii_tree(self) -> str          # PHONE ├── NAME └── ... for markdown reports
```

## 6. Scoring contract

```python
# scoring/confidence.py
RULES = {  # spec section 17 - transparent
  "exact_phone_match": 40, "same_name_multiple_sources": 25, "same_business": 15, "same_location": 10,
  "same_email": 10, "same_username": 10, "multiple_independent_sources": 10,
  "official_or_primary_source": 10, "direct_association": 5,
  "contradictory_location": -30, "contradictory_name": -30, "evidence_belongs_to_other_person": -50,
  "low_quality_sources_only": -15, "inferred_only": -20, "stale_evidence_only": -10,
}
def score_entity(entity: Entity, findings: list[Finding], sources: list[Source], contradictions: list[Contradiction]) -> ScoreBreakdown
#   percent = clamp(total_points, 0, 100) (max realistic total ~ 125 → clamp)
#   label: FACT only if number_displayed by an A/B source AND ≥2 independent sources AND no contradictions (else STRONG_MATCH ≥75, POSSIBLE_MATCH ≥50, WEAK_ASSOCIATION ≥25, UNVERIFIED <25; CONTRADICTORY if a NAME/OWNERSHIP contradiction involves the entity and percent<75)
def summarize_confidence(entities) -> ConfidenceSummary
def build_executive_summary(inv: Investigation) -> ExecutiveSummary

# scoring/source_quality.py
def classify_source(url: str, title: str = "", snippet: str = "") -> tuple[SourceType, SourceQuality]
#   domain table for Indian sources: *.gov.in/*.nic.in → GOVERNMENT_REGISTRY/A, indiankanoon.org → COURT_RECORD/A,
#   mca.gov.in → A, zaubacorp.com/tofler.in → GOVERNMENT_REGISTRY/B, linkedin.com → SOCIAL_PROFILE/B,
#   justdial.com/indiamart.com/tradeindia.com/sulekha.com → BUSINESS_DIRECTORY/C, olx.in/quikr.com/99acres/magicbricks → CLASSIFIED_LISTING/D,
#   facebook/instagram/x.com/youtube/reddit/telegram → SOCIAL_PROFILE/D, github.com → CODE_REPOSITORY/C, news domains → NEWS/B,
#   .pdf/.doc/.xls URLs → DOCUMENT (quality by host), unknown → OTHER/E

# scoring/relevance.py
def score_lead(lead: Lead, findings: list[Finding], sources: list[Source]) -> float   # 0..1
#   + number of distinct sources; + quality; + DIRECT association; + lead type weight (email .9, username .7, name .6, business .7, domain .5)
#   - generic names (very common / single token), - stop-word business names, - depth penalty
def rank_leads(leads, findings, sources, *, limit: int) -> list[Lead]

# scoring/information_gain.py
def information_gain(results: int, new_results: int) -> float
```

## 7. Reports contract

```python
reports.builder.write_reports(inv: Investigation, output_dir: Path, formats: list[str]) -> dict[str, Path]
reports.json_report.write_json(inv, path) ; reports.markdown_report.render_markdown(inv) -> str
reports.html_report.render_html(inv) -> str (Jinja2 template in reports/templates/report.html.j2, self-contained, no external CDN needed for core content)
reports.csv_report.write_csv(inv, dir) -> {findings.csv, sources.csv, entities.csv, queries.csv, timeline.csv}
reports.pdf_report.write_pdf(html: str, path) -> Path | None   (weasyprint optional)
```

Report sections (spec 30) in order: disclaimer banner → investigation metadata → input number →
normalisation → telecom → executive summary → candidate identities (with WHY linked + score ledger) →
names → emails → usernames → social profiles → businesses → addresses/locations → public alternate
numbers → documents → timeline → evidence graph → contradictions → confidence scores → source quality →
full source list → queries used → limitations → timestamp. Every claim must show
**CONFIRMED PUBLIC FACT** vs **ANALYTICAL INFERENCE** labelling (from `ConfidenceLabel` / `Association`).

## 8. Storage contract

```python
storage.evidence_store.EvidenceStore(path).save(inv) -> str ; .load(investigation_id) -> Investigation ; .list() -> list[dict]
storage.snapshots.SnapshotStore(dir).save(source: Source, excerpt: str) -> Path   # url, title, retrieved_at, excerpt, content_hash (never whole sites)
```

## 9. Offline fixture (demo + tests)

`fixtures/synthetic_investigation.json` describes a completely fictional scenario for the synthetic
number `+919876543210` (all names, businesses, e-mails and domains are invented; domains use
`example.in`/`example.com`; no real person is described):

```json
{
  "phone": "+919876543210",
  "documents": [ {"url": "...", "title": "...", "snippet": "...", "text": "...", "content_type": "text/html", "published_at": "2023-04-01", "file_type": ""} ],
  "telecom": [ {"provider": "fixture", "field": "carrier", "value": "Example Telecom", "confidence": 0.5} ]
}
```

`providers.search.fixture.FixtureSearchProvider.search(query)` performs a tiny local search engine over
`documents`: it honours quoted phrases, `site:` and `filetype:` operators and plain terms, returning
`SearchResult`s ranked by term overlap. `providers.search.fixture.build_offline_transport(fixture)` returns an
`httpx.MockTransport` serving each document's `text` at its URL so `PageFetchCollector` works offline.
The scenario must include: Candidate A (person, Lucknow, runs a trading business, LinkedIn, e-mail, GitHub
username, company website with a co-listed second number, a tender PDF from 2024), Candidate B (a different
person in Delhi, from a 2019 classified listing — an older association / potential recycled number),
an unrelated noise result that contains a *different* number sharing 8 digits, and one "wrong number" forum post.

## 10. Depth presets

| Depth    | Queries | Leads | Page fetch | Stages |
|----------|---------|-------|------------|--------|
| QUICK    | 12      | 0     | 0          | telecom + exact-match search |
| STANDARD | 60      | 8     | 15         | + documents, social, business, registries, classifieds, one lead round |
| DEEP     | 150     | 25    | 40         | + recursive leads (max_depth 3), username enumeration, image search if configured |

`--deep` never means anything other than *more public queries*.

## 11. Security & privacy invariants (enforced in code and tests)

1. No provider or collector may implement login, OTP, password-reset, account-recovery, contact-sync
   or breach-lookup flows. Tests grep the codebase for such endpoints/keywords.
2. Subject and discovered numbers are masked in logs; secrets are `SecretStr`.
3. Page fetches honour robots.txt and size/content-type limits; documents are parsed in-process with
   pure-Python parsers only (no macros, no external viewers).
4. Reports carry the disclaimer and label every association as DIRECT / INDIRECT / INFERRED.
5. Alternate numbers are only ever *co-listed* public numbers; nothing generates or tests numbers.
