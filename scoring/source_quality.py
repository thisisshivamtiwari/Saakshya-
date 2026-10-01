"""
Source classification and quality rating (spec section 23).

A - official / public primary source (government registry, court database, the entity's own site)
B - reputable secondary source (news, LinkedIn, established aggregators of official data)
C - established directory (Justdial, IndiaMART, Google Business, GitHub)
D - user-generated public source (classifieds, forums, social posts)
E - unknown / unreliable
"""

from __future__ import annotations

from core.models import SourceQuality, SourceType
from extractors.url_utils import file_type_from_url, host_of, registrable_domain

# (registrable domain or suffix, source type, quality)
DOMAIN_TABLE: list[tuple[str, SourceType, SourceQuality]] = [
    # Government / courts / official
    ("indiankanoon.org", SourceType.COURT_RECORD, SourceQuality.A),
    ("ecourts.gov.in", SourceType.COURT_RECORD, SourceQuality.A),
    ("mca.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("eprocure.gov.in", SourceType.TENDER, SourceQuality.A),
    ("gem.gov.in", SourceType.TENDER, SourceQuality.A),
    ("udyamregistration.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("foscos.fssai.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("maharera.maharashtra.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("rera.karnataka.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("up-rera.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("sebi.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("irdai.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("icai.org", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("icsi.edu", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("nmc.org.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("startupindia.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    ("gst.gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    # Aggregators of official company data (secondary)
    ("zaubacorp.com", SourceType.GOVERNMENT_REGISTRY, SourceQuality.B),
    ("tofler.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.B),
    ("indiafilings.com", SourceType.GOVERNMENT_REGISTRY, SourceQuality.B),
    ("thecompanycheck.com", SourceType.GOVERNMENT_REGISTRY, SourceQuality.B),
    ("companycheck.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.B),
    ("falconebiz.com", SourceType.GOVERNMENT_REGISTRY, SourceQuality.B),
    ("casemine.com", SourceType.COURT_RECORD, SourceQuality.B),
    # Professional networks / news
    ("linkedin.com", SourceType.SOCIAL_PROFILE, SourceQuality.B),
    ("crunchbase.com", SourceType.BUSINESS_DIRECTORY, SourceQuality.B),
    ("timesofindia.indiatimes.com", SourceType.NEWS, SourceQuality.B),
    ("indiatimes.com", SourceType.NEWS, SourceQuality.B),
    ("thehindu.com", SourceType.NEWS, SourceQuality.B),
    ("hindustantimes.com", SourceType.NEWS, SourceQuality.B),
    ("indianexpress.com", SourceType.NEWS, SourceQuality.B),
    ("ndtv.com", SourceType.NEWS, SourceQuality.B),
    ("livemint.com", SourceType.NEWS, SourceQuality.B),
    ("economictimes.indiatimes.com", SourceType.NEWS, SourceQuality.B),
    ("business-standard.com", SourceType.NEWS, SourceQuality.B),
    ("thewire.in", SourceType.NEWS, SourceQuality.B),
    ("scroll.in", SourceType.NEWS, SourceQuality.B),
    ("news18.com", SourceType.NEWS, SourceQuality.B),
    ("deccanherald.com", SourceType.NEWS, SourceQuality.B),
    # Established directories
    ("justdial.com", SourceType.BUSINESS_DIRECTORY, SourceQuality.C),
    ("indiamart.com", SourceType.BUSINESS_DIRECTORY, SourceQuality.C),
    ("tradeindia.com", SourceType.BUSINESS_DIRECTORY, SourceQuality.C),
    ("exportersindia.com", SourceType.BUSINESS_DIRECTORY, SourceQuality.C),
    ("sulekha.com", SourceType.BUSINESS_DIRECTORY, SourceQuality.C),
    ("yellowpages.in", SourceType.BUSINESS_DIRECTORY, SourceQuality.C),
    ("google.com", SourceType.MAPS, SourceQuality.C),
    ("goo.gl", SourceType.MAPS, SourceQuality.C),
    ("practo.com", SourceType.BUSINESS_DIRECTORY, SourceQuality.C),
    ("zomato.com", SourceType.BUSINESS_DIRECTORY, SourceQuality.C),
    ("github.com", SourceType.CODE_REPOSITORY, SourceQuality.C),
    ("gitlab.com", SourceType.CODE_REPOSITORY, SourceQuality.C),
    ("openstreetmap.org", SourceType.MAPS, SourceQuality.C),
    # Classifieds / marketplaces / user generated
    ("olx.in", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("quikr.com", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("99acres.com", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("magicbricks.com", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("housing.com", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("nobroker.in", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("makaan.com", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("cardekho.com", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("carwale.com", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("droom.in", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("clickindia.com", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("locanto.net", SourceType.CLASSIFIED_LISTING, SourceQuality.D),
    ("facebook.com", SourceType.SOCIAL_PROFILE, SourceQuality.D),
    ("instagram.com", SourceType.SOCIAL_PROFILE, SourceQuality.D),
    ("x.com", SourceType.SOCIAL_PROFILE, SourceQuality.D),
    ("twitter.com", SourceType.SOCIAL_PROFILE, SourceQuality.D),
    ("youtube.com", SourceType.VIDEO, SourceQuality.D),
    ("reddit.com", SourceType.FORUM, SourceQuality.D),
    ("t.me", SourceType.SOCIAL_PROFILE, SourceQuality.D),
    ("telegram.me", SourceType.SOCIAL_PROFILE, SourceQuality.D),
    ("quora.com", SourceType.FORUM, SourceQuality.D),
    ("medium.com", SourceType.BLOG, SourceQuality.D),
    ("blogspot.com", SourceType.BLOG, SourceQuality.D),
    ("wordpress.com", SourceType.BLOG, SourceQuality.D),
    ("pinterest.com", SourceType.SOCIAL_PROFILE, SourceQuality.D),
    ("scribd.com", SourceType.DOCUMENT, SourceQuality.D),
    ("slideshare.net", SourceType.DOCUMENT, SourceQuality.D),
    ("issuu.com", SourceType.DOCUMENT, SourceQuality.D),
    ("truecaller.com", SourceType.OTHER, SourceQuality.E),
    ("whocalledme", SourceType.FORUM, SourceQuality.E),
    ("callercenter", SourceType.FORUM, SourceQuality.E),
    ("spamcalls.net", SourceType.FORUM, SourceQuality.E),
]

_SUFFIX_TABLE: list[tuple[str, SourceType, SourceQuality]] = [
    (".gov.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    (".nic.in", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    (".gov", SourceType.GOVERNMENT_REGISTRY, SourceQuality.A),
    (".ac.in", SourceType.OTHER, SourceQuality.B),
    (".edu.in", SourceType.OTHER, SourceQuality.B),
    (".edu", SourceType.OTHER, SourceQuality.B),
    (".org.in", SourceType.OTHER, SourceQuality.C),
]

SOCIAL_HOSTS = {
    "linkedin.com": "linkedin", "facebook.com": "facebook", "instagram.com": "instagram",
    "x.com": "x", "twitter.com": "x", "youtube.com": "youtube", "github.com": "github",
    "reddit.com": "reddit", "t.me": "telegram", "telegram.me": "telegram", "pinterest.com": "pinterest",
    "medium.com": "medium", "quora.com": "quora", "threads.net": "threads", "tiktok.com": "tiktok",
    "koo.app": "koo", "behance.net": "behance", "dribbble.com": "dribbble", "gitlab.com": "gitlab",
    "stackoverflow.com": "stackoverflow", "about.me": "aboutme",
}


_DEMO_SPECIAL = {"olx": "olx.in", "t": "t.me", "yellowpages": "yellowpages.in", "tofler": "tofler.in",
                 "nobroker": "nobroker.in", "up-rera": "up-rera.in", "droom": "droom.in", "gov": "gov.in",
                 "nic": "nic.in", "indiankanoon": "indiankanoon.org", "locanto": "locanto.net",
                 "slideshare": "slideshare.net", "threads": "threads.net"}


def demo_host_alias(host: str) -> tuple[str, str]:
    """
    Synthetic fixtures use ``<label>.example`` hosts (e.g. ``www.linkedin.example``) so that no real
    site is referenced.  Map them onto the real registrable domain for classification purposes only.
    Returns (host, registrable_domain) - unchanged for real hosts.
    """
    if not host.endswith(".example"):
        return host, registrable_domain("https://" + host)
    base = host[: -len(".example")]
    if base.startswith("www."):
        base = base[4:]
    labels = base.split(".")
    last = labels[-1]
    if last in _DEMO_SPECIAL:
        mapped = _DEMO_SPECIAL[last]
        alias_host = ".".join(labels[:-1] + [mapped]) if len(labels) > 1 else mapped
        return alias_host, mapped
    mapped = f"{last}.com"
    alias_host = ".".join(labels[:-1] + [mapped]) if len(labels) > 1 else mapped
    return alias_host, mapped


def classify_source(url: str, title: str = "", snippet: str = "") -> tuple[SourceType, SourceQuality]:
    """Return (SourceType, SourceQuality) for a URL using the domain tables + heuristics."""
    host, domain = demo_host_alias(host_of(url))
    for dom, stype, q in DOMAIN_TABLE:
        if domain == dom or host == dom or host.endswith("." + dom):
            if file_type_from_url(url) and stype not in (SourceType.COURT_RECORD, SourceType.TENDER):
                return SourceType.DOCUMENT, q
            return stype, q
    for suffix, stype, q in _SUFFIX_TABLE:
        if host.endswith(suffix):
            if file_type_from_url(url):
                return SourceType.DOCUMENT, q
            return stype, q
    ftype = file_type_from_url(url)
    if ftype:
        return SourceType.DOCUMENT, SourceQuality.E
    low = f"{title} {snippet}".lower()
    if any(w in low for w in ("tender", "notice inviting", "bid document", "rfp", "e-procurement")):
        return SourceType.TENDER, SourceQuality.C
    if any(w in low for w in ("contact us", "about us", "our team", "reach us")):
        return SourceType.COMPANY_WEBSITE, SourceQuality.C
    if any(w in low for w in ("pvt ltd", "private limited", "llp", "enterprises", "industries", "traders")):
        return SourceType.COMPANY_WEBSITE, SourceQuality.C
    if any(w in low for w in ("forum", "thread", "replies", "posted by")):
        return SourceType.FORUM, SourceQuality.D
    return SourceType.OTHER, SourceQuality.E


def platform_for_url(url: str) -> str:
    """'linkedin' / 'github' / '' for a URL."""
    host, domain = demo_host_alias(host_of(url))
    for dom, platform in SOCIAL_HOSTS.items():
        if domain == dom or host.endswith("." + dom) or host == dom:
            return platform
    return ""


QUALITY_RANK = {SourceQuality.A: 5, SourceQuality.B: 4, SourceQuality.C: 3, SourceQuality.D: 2, SourceQuality.E: 1}


def best_quality(a: SourceQuality, b: SourceQuality) -> SourceQuality:
    return a if QUALITY_RANK[a] >= QUALITY_RANK[b] else b
