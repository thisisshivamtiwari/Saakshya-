"""
Extraction entry point (ARCHITECTURE §2): text → Findings + Leads with
evidence windows, association strength and number-displayed flags.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from core.models import Association, FieldType, Finding, Lead, LeadType, NormalizedPhone, Source, SourceType
from extractors.address_extractor import classify_address, extract_addresses, extract_locations
from extractors.business_extractor import extract_business_names
from extractors.date_extractor import extract_dates
from extractors.email_extractor import extract_emails
from extractors.name_extractor import extract_person_names, is_generic_name
from extractors.phone_extractor import extract_phones, subject_number_positions
from extractors.text_utils import normalise_name, window
from extractors.url_utils import normalize_website, registrable_domain
from extractors.username_extractor import extract_profiles
from scoring.source_quality import classify_source

DIRECT_RADIUS = 300
SNIPPET_LEN = 400

_JOB_TITLES = ["Managing Director", "Chartered Accountant", "Co-Founder", "Proprietor", "Owner", "Director", "CEO",
               "Founder", "Partner", "Manager", "Engineer", "Consultant", "Advocate", "Doctor", "Architect", "Teacher",
               "Tutor", "Agent", "Broker", "Dealer", "Distributor", "Dr"]
_JOB_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in _JOB_TITLES) + r")\b")


class Extraction(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    number_displayed: bool = False
    other_numbers: list[str] = Field(default_factory=list)
    leads: list[Lead] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    usernames: list[str] = Field(default_factory=list)
    businesses: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)
    profiles: list[dict] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)


def _near(positions: list[tuple[int, int]], start: int, end: int, radius: int) -> bool:
    return any(abs(ps - end) <= radius or abs(start - pe) <= radius or (ps <= start and pe >= end)
               for ps, pe in positions)


def extract_from_text(
    text: str,
    *,
    phone: NormalizedPhone,
    source: Source,
    query_id: Optional[str] = None,
    title: str = "",
    url: str = "",
    is_full_page: bool = False,
    extractor_tag: str = "snippet",
) -> Extraction:
    ext = Extraction()
    text = (text or "")[:200_000]
    if title and title not in text:
        text = f"{title}\n{text}"
    url = url or source.url
    positions = subject_number_positions(text, phone)
    ext.number_displayed = bool(positions)
    is_snippet = not is_full_page and len(text) <= SNIPPET_LEN
    seen: set[tuple[str, str]] = set()

    def association_for(start: int, end: int) -> Association:
        if not positions:
            return Association.INFERRED
        if is_snippet or _near(positions, start, end, DIRECT_RADIUS):
            return Association.DIRECT
        return Association.INDIRECT

    def add(field: FieldType, value: str, normalized: str, conf: float, start: int, end: int,
            metadata: Optional[dict] = None) -> Optional[Finding]:
        value = value.strip()
        if not value:
            return None
        key = (field.value, normalized)
        if key in seen:
            return None
        seen.add(key)
        assoc = association_for(start, end)
        if not positions:
            conf *= 0.7
        f = Finding(
            phone=phone.e164, field=field, value=value[:300], normalized_value=normalized[:300],
            source_id=source.source_id, source_url=source.url, source_type=source.source_type,
            source_quality=source.quality, evidence_text=window(text, start, end),
            published_at=source.published_at, date_precision=source.date_precision,
            confidence=round(min(1.0, conf), 2), association=assoc, number_displayed=bool(positions),
            provider=source.provider, query_id=query_id, extractor=extractor_tag, metadata=dict(metadata or {}),
        )
        ext.findings.append(f)
        return f

    # phones (other than the subject) ---------------------------------- #
    for pm in extract_phones(text):
        if pm.e164 == phone.e164:
            continue
        f = add(FieldType.PHONE, pm.e164, pm.e164, 0.8, pm.start, pm.end,
                {"co_listed": bool(positions), "raw": pm.raw, "kind": pm.kind})
        if f:
            ext.other_numbers.append(pm.e164)
            if positions:
                ext.leads.append(Lead(lead_type=LeadType.PHONE, value=pm.e164, normalized_value=pm.e164,
                                      origin_finding_ids=[f.finding_id],
                                      reasons=[f"co-listed phone on {source.domain or registrable_domain(url)}"]))
    # emails ----------------------------------------------------------- #
    for em in extract_emails(text):
        f = add(FieldType.EMAIL, em.email, em.email.lower(), 0.9, em.start, em.end)
        if f:
            ext.emails.append(em.email)
            ext.leads.append(Lead(lead_type=LeadType.EMAIL, value=em.email, normalized_value=em.email.lower(),
                                  origin_finding_ids=[f.finding_id], reasons=[f"email on {source.domain}"]))
    # profiles / usernames --------------------------------------------- #
    for pr in extract_profiles(text, url=url):
        uname_key = f"{pr.platform}:{pr.username.lower()}"
        meta = {"platform": pr.platform, "username": pr.username, "profile_url": pr.profile_url, "kind": pr.kind}
        f = add(FieldType.SOCIAL_PROFILE, pr.profile_url or f"@{pr.username}", uname_key, pr.confidence,
                pr.start, pr.end, meta)
        if f:
            ext.profiles.append(pr.as_dict())
        if pr.kind in ("profile", "handle", "channel") and pr.username and pr.platform != "unknown":
            g = add(FieldType.USERNAME, pr.username, uname_key, min(0.85, pr.confidence), pr.start, pr.end, meta)
            if g:
                ext.usernames.append(pr.username)
                ext.leads.append(Lead(lead_type=LeadType.USERNAME, value=pr.username,
                                      normalized_value=pr.username.lower(), origin_finding_ids=[g.finding_id],
                                      reasons=[f"platform:{pr.platform}", f"on {source.domain}"]))
    # businesses -------------------------------------------------------- #
    business_names: list[str] = []
    for bc in extract_business_names(text):
        if bc.confidence < 0.5:  # descriptive trade phrases are not business names
            continue
        norm = normalise_name(bc.name)
        f = add(FieldType.BUSINESS, bc.name, norm, bc.confidence, bc.start, bc.end, {"reason": bc.reason})
        if f:
            business_names.append(bc.name)
            ext.businesses.append(bc.name)
            if bc.confidence >= 0.5:
                ext.leads.append(Lead(lead_type=LeadType.BUSINESS, value=bc.name, normalized_value=norm,
                                      origin_finding_ids=[f.finding_id], reasons=[f"business on {source.domain}"]))
    # person names ------------------------------------------------------ #
    for nc in extract_person_names(text):
        if any(normalise_name(nc.name) in normalise_name(b) for b in business_names):
            continue
        norm = normalise_name(nc.name)
        f = add(FieldType.NAME, nc.name, norm, nc.confidence, nc.start, nc.end, {"reason": nc.reason})
        if not f:
            continue
        ext.names.append(nc.name)
        jm = _JOB_RE.search(text[max(0, nc.start - 40):min(len(text), nc.end + 40)])
        if jm:
            add(FieldType.JOB_TITLE, jm.group(1), f"{jm.group(1).lower()}|{norm}", 0.6, nc.start, nc.end,
                {"for_name": nc.name})
        if nc.confidence >= 0.5 and not is_generic_name(nc.name):
            ext.leads.append(Lead(lead_type=LeadType.NAME, value=nc.name, normalized_value=norm,
                                  origin_finding_ids=[f.finding_id], reasons=[nc.reason, f"on {source.domain}"]))
    # addresses & locations -------------------------------------------- #
    covered: list[tuple[int, int]] = []
    for am in extract_addresses(text):
        cls, reason = classify_address(am.raw)
        f = add(FieldType.ADDRESS, am.raw, " ".join(am.raw.lower().split()), am.confidence, am.start, am.end,
                {"city": am.city, "state": am.state, "pincode": am.pincode, "address_class": cls.value,
                 "reason": reason})
        if f:
            ext.addresses.append(am.raw)
            covered.append((am.start, am.end))
            if am.city:
                ext.locations.append(am.city)
    for lm in extract_locations(text):
        if not lm.city:
            continue
        label = ", ".join(p for p in (lm.city, lm.state) if p)
        f = add(FieldType.LOCATION, label, label.lower(), lm.confidence, lm.start, lm.end,
                {"city": lm.city, "state": lm.state})
        if f and lm.city not in ext.locations:
            ext.locations.append(lm.city)
    # dates -------------------------------------------------------------- #
    ext.dates = [d.date.date().isoformat() for d in extract_dates(text)[:10]]
    # website (page's own domain) --------------------------------------- #
    stype, _ = classify_source(url, title)
    if positions and stype in (SourceType.COMPANY_WEBSITE, SourceType.OTHER, SourceType.BLOG):
        site = normalize_website(url)
        if site and not site.endswith(".example") and "example.com" not in site:
            f = add(FieldType.WEBSITE, site, site, 0.7, 0, 0, {"origin": "page_domain"})
            if f:
                ext.leads.append(Lead(lead_type=LeadType.DOMAIN, value=site, normalized_value=site,
                                      origin_finding_ids=[f.finding_id], reasons=["page displays the number"]))
    # mention fallback -------------------------------------------------- #
    if positions and not ext.findings:
        s, e = positions[0]
        add(FieldType.MENTION, title or source.domain or url, (title or url).lower(), 0.5, s, e)
    return ext
