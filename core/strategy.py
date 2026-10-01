"""
Search strategy engine (spec sections 5, 8, 32).

* ``QueryPlanner`` turns a normalised phone number (and later, leads) into
  staged, prioritised, *bounded* query lists.
* ``SearchBudget`` tracks the global query budget and per-branch information
  gain so the engine stops expanding a branch when it keeps returning the
  same URLs.

Nothing here talks to the network.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from pydantic import BaseModel, Field

from core.models import Depth, InvestigationConfig, Lead, LeadType, NormalizedPhone, Stage


class PlannedQuery(BaseModel):
    query: str
    stage: Stage
    purpose: str
    branch: str
    lead_id: Optional[str] = None
    priority: float = 1.0
    requires_site_operator: bool = False
    requires_filetype_operator: bool = False

    def key(self) -> str:
        return self.query.strip().lower()


class LeadContext(BaseModel):
    cities: list[str] = Field(default_factory=list)
    businesses: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Static tables
# --------------------------------------------------------------------------- #

SOCIAL_SITES: list[tuple[str, str]] = [  # (site, platform)
    ("linkedin.com", "linkedin"),
    ("facebook.com", "facebook"),
    ("instagram.com", "instagram"),
    ("x.com", "x"),
    ("twitter.com", "x"),
    ("youtube.com", "youtube"),
    ("github.com", "github"),
    ("reddit.com", "reddit"),
    ("t.me", "telegram"),
    ("quora.com", "quora"),
    ("medium.com", "medium"),
    ("pinterest.com", "pinterest"),
    ("threads.net", "threads"),
]

BUSINESS_SITES: list[str] = [
    "justdial.com", "indiamart.com", "tradeindia.com", "sulekha.com", "exportersindia.com",
    "yellowpages.in", "practo.com", "zomato.com", "crunchbase.com", "google.com/maps",
]

BUSINESS_TERMS: list[str] = [
    "business", "company", "owner", "contact", "proprietor", "manager", "services", "shop",
    "office", "dealer", "agency", "consultant", "clinic", "school", "restaurant",
]

REGISTRY_QUERIES: list[tuple[str, str]] = [  # (site operator or extra terms, purpose)
    ("site:indiankanoon.org", "registry:court"),
    ("site:gov.in", "registry:government"),
    ("site:nic.in", "registry:government"),
    ("site:eprocure.gov.in", "registry:tender"),
    ("site:gem.gov.in", "registry:tender"),
    ("site:zaubacorp.com", "registry:company"),
    ("site:tofler.in", "registry:company"),
    ("site:thecompanycheck.com", "registry:company"),
    ("site:maharera.maharashtra.gov.in", "registry:rera"),
    ("site:up-rera.in", "registry:rera"),
    ("site:rera.karnataka.gov.in", "registry:rera"),
    ("site:sebi.gov.in", "registry:sebi"),
    ("site:udyamregistration.gov.in", "registry:msme"),
    ("site:foscos.fssai.gov.in", "registry:fssai"),
    ("tender", "registry:tender-terms"),
    ("notice OR circular OR gazette", "registry:notice-terms"),
    ("director OR proprietor OR partner registered", "registry:company-terms"),
]

CLASSIFIED_SITES: list[str] = [
    "olx.in", "quikr.com", "99acres.com", "magicbricks.com", "housing.com", "nobroker.in",
    "makaan.com", "cardekho.com", "carwale.com", "droom.in", "clickindia.com", "locanto.net",
    "sulekha.com", "indiamart.com",
]

DOCUMENT_TYPES: list[str] = ["pdf", "xls", "xlsx", "doc", "docx", "ppt", "pptx"]

DEFAULT_INDIA_CITIES: list[str] = [
    "Delhi", "Mumbai", "Bangalore", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune",
    "Ahmedabad", "Jaipur", "Lucknow", "Surat", "Noida", "Gurgaon", "Gurugram", "Chandigarh",
    "Indore", "Bhopal", "Nagpur", "Patna", "Kochi", "Coimbatore", "Visakhapatnam", "Thane",
]


def _depth_n(depth: Depth, quick: int, standard: int, deep: int) -> int:
    return {Depth.QUICK: quick, Depth.STANDARD: standard, Depth.DEEP: deep}[depth]


# --------------------------------------------------------------------------- #
# Planner
# --------------------------------------------------------------------------- #


class QueryPlanner:
    def __init__(self, config: InvestigationConfig, phone: NormalizedPhone) -> None:
        self.config = config
        self.phone = phone
        self.depth = config.depth
        self._emitted: set[str] = set()
        quoted = phone.quoted_variants or [f'"{phone.subscriber}"']
        self.q_primary = f'"{phone.subscriber}"' if phone.subscriber else quoted[0]
        # second-best variant: the Indian 5-5 split, then E.164
        spaced = f'"{phone.subscriber[:5]} {phone.subscriber[5:]}"' if len(phone.subscriber) == 10 else ""
        self.q_secondary = spaced if spaced in quoted else (quoted[0] if quoted else self.q_primary)
        self.q_e164 = f'"{phone.e164}"' if phone.e164 else self.q_primary
        self.quoted = quoted

    # -- helpers ----------------------------------------------------------- #
    def _pq(self, query: str, stage: Stage, purpose: str, branch: str, *, priority: float = 1.0,
            lead_id: Optional[str] = None, site: bool = False, filetype: bool = False) -> Optional[PlannedQuery]:
        q = " ".join(query.split())
        if q.lower() in self._emitted:
            return None
        self._emitted.add(q.lower())
        return PlannedQuery(query=q, stage=stage, purpose=purpose, branch=branch, priority=priority,
                            lead_id=lead_id, requires_site_operator=site, requires_filetype_operator=filetype)

    def _collect(self, items: list[Optional[PlannedQuery]]) -> list[PlannedQuery]:
        return sorted([i for i in items if i is not None], key=lambda p: -p.priority)

    def reset_seen(self) -> None:
        self._emitted.clear()

    # -- stage 1: exact match --------------------------------------------- #
    def exact_match_queries(self) -> list[PlannedQuery]:
        n = _depth_n(self.depth, 4, 7, len(self.quoted))
        out = []
        for i, q in enumerate(self.quoted[:n]):
            out.append(self._pq(q, Stage.SEARCH, "exact phone match", "exact", priority=1.0 - i * 0.02))
        return self._collect(out)

    def india_queries(self) -> list[PlannedQuery]:
        out = [
            self._pq(f"{self.q_primary} India", Stage.SEARCH, "india: generic", "india", priority=0.7),
            self._pq(f'"+91 {self.phone.subscriber}"', Stage.SEARCH, "india: +91 spaced", "india", priority=0.65),
        ]
        cities = self.config.cities or ([] if self.depth == Depth.QUICK else [])
        for city in cities[: _depth_n(self.depth, 0, 4, 10)]:
            out.append(self._pq(f"{self.q_primary} {city}", Stage.SEARCH, f"india: city {city}", "india", priority=0.6))
        return self._collect(out)

    # -- stage 1b: source-specific dorks ---------------------------------- #
    def social_queries(self) -> list[PlannedQuery]:
        n = _depth_n(self.depth, 0, 8, len(SOCIAL_SITES))
        out = []
        for i, (site, platform) in enumerate(SOCIAL_SITES[:n]):
            out.append(self._pq(f"site:{site} {self.q_primary}", Stage.SOCIAL, f"social:{platform}", "social",
                                priority=0.9 - i * 0.02, site=True))
            if self.depth == Depth.DEEP and i < 4:
                out.append(self._pq(f"site:{site} {self.q_secondary}", Stage.SOCIAL, f"social:{platform} (spaced)",
                                    "social", priority=0.6, site=True))
        return self._collect(out)

    def business_queries(self) -> list[PlannedQuery]:
        n_terms = _depth_n(self.depth, 0, 6, len(BUSINESS_TERMS))
        n_sites = _depth_n(self.depth, 0, 6, len(BUSINESS_SITES))
        out = []
        for i, term in enumerate(BUSINESS_TERMS[:n_terms]):
            out.append(self._pq(f"{self.q_primary} {term}", Stage.BUSINESS, f"business:{term}", "business",
                                priority=0.8 - i * 0.02))
        for i, site in enumerate(BUSINESS_SITES[:n_sites]):
            out.append(self._pq(f"site:{site} {self.q_primary}", Stage.BUSINESS, f"business:site {site}",
                                "business", priority=0.85 - i * 0.02, site=True))
        return self._collect(out)

    def document_queries(self) -> list[PlannedQuery]:
        n = _depth_n(self.depth, 0, 4, len(DOCUMENT_TYPES))
        out = []
        for i, ft in enumerate(DOCUMENT_TYPES[:n]):
            out.append(self._pq(f"{self.q_primary} filetype:{ft}", Stage.DOCUMENTS, f"documents:{ft}", "docs",
                                priority=0.85 - i * 0.03, filetype=True))
        if self.depth != Depth.QUICK:
            out.append(self._pq(f"{self.q_secondary} filetype:pdf", Stage.DOCUMENTS, "documents:pdf (spaced)",
                                "docs", priority=0.7, filetype=True))
        if self.depth == Depth.DEEP:
            out.append(self._pq(f"{self.q_e164} filetype:pdf", Stage.DOCUMENTS, "documents:pdf (e164)", "docs",
                                priority=0.6, filetype=True))
            out.append(self._pq(f"{self.q_primary} resume OR CV OR biodata", Stage.DOCUMENTS,
                                "documents:resume-terms", "docs", priority=0.55))
            out.append(self._pq(f"{self.q_primary} brochure OR catalogue OR newsletter", Stage.DOCUMENTS,
                                "documents:brochure-terms", "docs", priority=0.5))
        return self._collect(out)

    def registry_queries(self) -> list[PlannedQuery]:
        n = _depth_n(self.depth, 0, 8, len(REGISTRY_QUERIES))
        out = []
        for i, (op, purpose) in enumerate(REGISTRY_QUERIES[:n]):
            is_site = op.startswith("site:")
            out.append(self._pq(f"{op} {self.q_primary}" if is_site else f"{self.q_primary} {op}",
                                Stage.REGISTRIES, purpose, "registry", priority=0.8 - i * 0.02, site=is_site))
        return self._collect(out)

    def classified_queries(self) -> list[PlannedQuery]:
        n = _depth_n(self.depth, 0, 7, len(CLASSIFIED_SITES))
        out = []
        for i, site in enumerate(CLASSIFIED_SITES[:n]):
            out.append(self._pq(f"site:{site} {self.q_primary}", Stage.CLASSIFIEDS, f"classifieds:{site}",
                                "classifieds", priority=0.75 - i * 0.02, site=True))
        if self.depth == Depth.DEEP:
            out.append(self._pq(f"{self.q_primary} for sale OR for rent OR wanted", Stage.CLASSIFIEDS,
                                "classifieds:terms", "classifieds", priority=0.5))
        return self._collect(out)

    # -- stage 3: leads ---------------------------------------------------- #
    def lead_queries(self, lead: Lead, context: Optional[LeadContext] = None) -> list[PlannedQuery]:
        ctx = context or LeadContext()
        cap = _depth_n(self.depth, 0, 4, 7)
        cap = max(1, min(cap, 2 + round(max(0.0, min(lead.relevance, 1.0)) * (cap - 2))))
        value = lead.value.strip()
        q = f'"{value}"'
        branch = f"lead:{lead.lead_id}"
        lid = lead.lead_id
        stage = Stage.LEAD_EXPANSION
        cands: list[Optional[PlannedQuery]] = []
        p = self.q_primary

        if lead.lead_type == LeadType.NAME:
            cands.append(self._pq(f"{q} {p}", stage, "lead:name+phone", branch, priority=1.0, lead_id=lid))
            for city in ctx.cities[:2]:
                cands.append(self._pq(f"{q} {city}", stage, "lead:name+city", branch, priority=0.8, lead_id=lid))
            for biz in ctx.businesses[:2]:
                cands.append(self._pq(f'{q} "{biz}"', stage, "lead:name+business", branch, priority=0.8, lead_id=lid))
            cands.append(self._pq(f"site:linkedin.com {q}" + (f" {ctx.cities[0]}" if ctx.cities else ""),
                                  stage, "lead:name linkedin", branch, priority=0.7, lead_id=lid, site=True))
            cands.append(self._pq(f"{q} email OR contact OR phone", stage, "lead:name contact", branch,
                                  priority=0.6, lead_id=lid))
            cands.append(self._pq(f"site:instagram.com {q}", stage, "lead:name instagram", branch,
                                  priority=0.5, lead_id=lid, site=True))
            cands.append(self._pq(f"{q} business OR company OR proprietor", stage, "lead:name business", branch,
                                  priority=0.5, lead_id=lid))
        elif lead.lead_type == LeadType.EMAIL:
            cands.append(self._pq(q, stage, "lead:email exact", branch, priority=1.0, lead_id=lid))
            cands.append(self._pq(f"site:linkedin.com {q}", stage, "lead:email linkedin", branch, priority=0.7,
                                  lead_id=lid, site=True))
            cands.append(self._pq(f"site:github.com {q}", stage, "lead:email github", branch, priority=0.7,
                                  lead_id=lid, site=True))
            cands.append(self._pq(f"{q} {p}", stage, "lead:email+phone", branch, priority=0.6, lead_id=lid))
            cands.append(self._pq(f"site:in {q}", stage, "lead:email .in sites", branch, priority=0.4,
                                  lead_id=lid, site=True))
        elif lead.lead_type == LeadType.USERNAME:
            cands.append(self._pq(q, stage, "lead:username exact", branch, priority=1.0, lead_id=lid))
            cands.append(self._pq(f"{q} India", stage, "lead:username india", branch, priority=0.6, lead_id=lid))
            for site in ("github.com", "linkedin.com", "instagram.com", "reddit.com", "youtube.com", "x.com"):
                cands.append(self._pq(f"site:{site} {q}", stage, f"lead:username {site}", branch, priority=0.55,
                                      lead_id=lid, site=True))
        elif lead.lead_type == LeadType.BUSINESS:
            cands.append(self._pq(f"{q} {p}", stage, "lead:business+phone", branch, priority=1.0, lead_id=lid))
            for city in ctx.cities[:1]:
                cands.append(self._pq(f"{q} {city}", stage, "lead:business+city", branch, priority=0.8, lead_id=lid))
            cands.append(self._pq(f"{q} owner OR proprietor OR director", stage, "lead:business owner", branch,
                                  priority=0.7, lead_id=lid))
            cands.append(self._pq(f"{q} contact", stage, "lead:business contact", branch, priority=0.6, lead_id=lid))
            cands.append(self._pq(f"site:zaubacorp.com {q}", stage, "lead:business registry", branch,
                                  priority=0.5, lead_id=lid, site=True))
        elif lead.lead_type == LeadType.DOMAIN:
            cands.append(self._pq(f"site:{value} contact", stage, "lead:domain contact page", branch, priority=1.0,
                                  lead_id=lid, site=True))
            cands.append(self._pq(f"site:{value} {p}", stage, "lead:domain+phone", branch, priority=0.9,
                                  lead_id=lid, site=True))
            cands.append(self._pq(f'"{value}" {p}', stage, "lead:domain mention+phone", branch, priority=0.6,
                                  lead_id=lid))
        elif lead.lead_type == LeadType.ADDRESS:
            cands.append(self._pq(f"{q} {p}", stage, "lead:address+phone", branch, priority=0.9, lead_id=lid))
            cands.append(self._pq(q, stage, "lead:address exact", branch, priority=0.5, lead_id=lid))
        elif lead.lead_type == LeadType.PHONE:
            # A publicly co-listed number: only ever searched to find the *same* public entity.
            cands.append(self._pq(f'"{value}" {p}', stage, "lead:co-listed number + subject", branch,
                                  priority=0.8, lead_id=lid))
        return self._collect(cands)[:cap]

    # -- convenience for --dry-run ----------------------------------------- #
    def preview(self) -> list[PlannedQuery]:
        self.reset_seen()
        plan = self.exact_match_queries() + self.india_queries()
        c = self.config
        if c.enable_documents:
            plan += self.document_queries()
        if c.enable_social:
            plan += self.social_queries()
        if c.enable_business:
            plan += self.business_queries()
        if c.enable_registries:
            plan += self.registry_queries()
        if c.enable_classifieds:
            plan += self.classified_queries()
        return plan


# --------------------------------------------------------------------------- #
# Budget / information gain
# --------------------------------------------------------------------------- #


class SearchBudget:
    def __init__(self, max_queries: int, info_gain_threshold: float = 0.15, min_queries_per_branch: int = 2) -> None:
        self.max_queries = max_queries
        self.threshold = info_gain_threshold
        self.min_per_branch = min_queries_per_branch
        self.executed = 0
        self.gains: dict[str, list[float]] = defaultdict(list)
        self.results_total = 0
        self.new_total = 0

    def can_run(self) -> bool:
        return self.executed < self.max_queries

    def remaining(self) -> int:
        return max(0, self.max_queries - self.executed)

    def record(self, branch: str, results: int, new_results: int) -> float:
        gain = information_gain(results, new_results)
        self.executed += 1
        self.results_total += results
        self.new_total += new_results
        self.gains[branch].append(gain)
        return gain

    def branch_exhausted(self, branch: str) -> bool:
        g = self.gains.get(branch, [])
        if len(g) < self.min_per_branch:
            return False
        recent = g[-2:]
        return sum(recent) / len(recent) < self.threshold

    def branch_gain(self, branch: str) -> float:
        g = self.gains.get(branch, [])
        return sum(g) / len(g) if g else 0.0

    def stats(self) -> dict[str, float | int | dict[str, float]]:
        return {
            "executed": self.executed,
            "max_queries": self.max_queries,
            "results_total": self.results_total,
            "new_total": self.new_total,
            "branches": {b: round(self.branch_gain(b), 3) for b in self.gains},
            "exhausted": [b for b in self.gains if self.branch_exhausted(b)],  # type: ignore[dict-item]
        }


def information_gain(results: int, new_results: int) -> float:
    """Share of results that were previously unseen sources (0..1)."""
    if results <= 0:
        return 0.0
    return max(0.0, min(1.0, new_results / results))
