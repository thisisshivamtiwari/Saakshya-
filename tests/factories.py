"""
Test factories: a rich, fully synthetic ``Investigation`` for the fictional
number ``+919876543210``.

Everything here is invented.  Hosts use ``.example`` / ``*.example.in``
(reserved, non-resolving), and no real person, business or document is
described.  Identifiers are explicit so tests are deterministic.

Used by ``tests/test_reports.py``, ``tests/test_storage.py`` and other test
modules that need a populated investigation without network access.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.models import (
    Address,
    AddressClass,
    AssociatedNumber,
    Association,
    Business,
    ConfidenceLabel,
    ConfidenceSummary,
    Contradiction,
    ContradictionKind,
    DatePrecision,
    Depth,
    Document,
    Entity,
    EntityKind,
    ExecutiveSummary,
    FieldType,
    Finding,
    Investigation,
    InvestigationMeta,
    Lead,
    LeadType,
    Listing,
    Location,
    NormalizedPhone,
    PhoneKind,
    ProviderInfo,
    ProviderState,
    QueryRecord,
    Relationship,
    ScoreBreakdown,
    ScoreComponent,
    SocialProfile,
    Source,
    SourceQuality,
    SourceType,
    Stage,
    StageResult,
    StageStatus,
    TelecomResult,
    TimelineEvent,
    mask_phone,
)

PHONE = "+919876543210"
ALT_PHONE = "+919123456780"


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


RUN_AT = _dt(2025, 1, 15, 10, 0)
DONE_AT = _dt(2025, 1, 15, 10, 4)


def make_sample_phone() -> NormalizedPhone:
    """Normalised form of the synthetic subject number (mirrors ``core.normalize`` output)."""
    variants = [
        PHONE, "919876543210", "09876543210", "9876543210", "98765 43210",
        "+91 98765 43210", "+91 9876543210", "+91-9876543210", "98-7654-3210",
        "98 7654 3210", "987 654 3210", "987-654-3210", "098765 43210",
    ]
    return NormalizedPhone(
        raw="+91 98765 43210",
        e164=PHONE,
        national="098765 43210",
        international="+91 98765 43210",
        subscriber="9876543210",
        country_code=91,
        region="IN",
        is_valid=True,
        is_possible=True,
        kind=PhoneKind.MOBILE,
        is_indian=True,
        masked=mask_phone(PHONE),
        variants=variants,
        quoted_variants=[f'"{v}"' for v in variants],
        warnings=["Input contained spaces; normalised before validation."],
        notes=[
            "Mobile Number Portability: the prefix indicates original allocation only; "
            "the current operator and service area may differ."
        ],
    )


def _sources() -> list[Source]:
    return [
        Source(
            source_id="src_tender",
            url="https://eprocure.gov.example/tenders/2024/verma-agro-supply.pdf",
            canonical_url="https://eprocure.gov.example/tenders/2024/verma-agro-supply.pdf",
            domain="eprocure.gov.example",
            title="Tender Notice 2024/117 - Supply of Agricultural Inputs (Lucknow Division)",
            source_type=SourceType.TENDER,
            quality=SourceQuality.A,
            provider="fixture",
            retrieved_at=RUN_AT,
            published_at=_dt(2024, 3, 15),
            date_precision=DatePrecision.DAY,
            http_status=200,
            content_hash="a1" * 32,
            excerpt="Bidder: Verma Agro Traders. Contact person: Rohan Verma, Mob: +91 98765 43210. "
                    "Registered office: Plot 12, Transport Nagar, Lucknow, Uttar Pradesh 226012.",
            fetched=True,
            robots_allowed=True,
            referenced_by=["qry_03", "qry_06"],
        ),
        Source(
            source_id="src_company",
            url="https://www.vermaagrotraders.example.in/contact",
            canonical_url="https://www.vermaagrotraders.example.in/contact",
            domain="vermaagrotraders.example.in",
            title="Contact Us - Verma Agro Traders",
            source_type=SourceType.COMPANY_WEBSITE,
            quality=SourceQuality.A,
            provider="fixture",
            retrieved_at=RUN_AT,
            published_at=None,
            http_status=200,
            content_hash="b2" * 32,
            excerpt="Proprietor: Rohan Verma | Phone: 98765 43210 | Email: rohan@vermaagrotraders.example.in",
            fetched=True,
            robots_allowed=True,
            referenced_by=["qry_01", "qry_05"],
        ),
        Source(
            source_id="src_justdial",
            url="https://www.justdial.example/lucknow/verma-agro-traders-transport-nagar",
            canonical_url="https://www.justdial.example/lucknow/verma-agro-traders-transport-nagar",
            domain="justdial.example",
            title="Verma Agro Traders, Transport Nagar - Fertilizer Dealers in Lucknow",
            source_type=SourceType.BUSINESS_DIRECTORY,
            quality=SourceQuality.C,
            provider="fixture",
            retrieved_at=RUN_AT,
            published_at=_dt(2023, 6, 10),
            date_precision=DatePrecision.MONTH,
            http_status=200,
            content_hash="c3" * 32,
            excerpt="Verma Agro Traders - Fertilizer Dealers. Call 9876543210, 9123456780. "
                    "Plot 12, Transport Nagar, Lucknow. Listed since 2023.",
            fetched=True,
            robots_allowed=True,
            referenced_by=["qry_01", "qry_02", "qry_06"],
        ),
        Source(
            source_id="src_linkedin",
            url="https://www.linkedin.example/in/rohan-verma-agro",
            canonical_url="https://www.linkedin.example/in/rohan-verma-agro",
            domain="linkedin.example",
            title="Rohan Verma - Proprietor - Verma Agro Traders",
            source_type=SourceType.SOCIAL_PROFILE,
            quality=SourceQuality.B,
            provider="fixture",
            retrieved_at=RUN_AT,
            excerpt="Rohan Verma. Proprietor at Verma Agro Traders. Lucknow, Uttar Pradesh, India.",
            fetched=False,  # provider snippet only
            robots_allowed=False,
            referenced_by=["qry_04"],
        ),
        Source(
            source_id="src_github",
            url="https://github.example/rohanv-dev",
            canonical_url="https://github.example/rohanv-dev",
            domain="github.example",
            title="rohanv-dev (Rohan Verma) - GitHub",
            source_type=SourceType.CODE_REPOSITORY,
            quality=SourceQuality.C,
            provider="fixture",
            retrieved_at=RUN_AT,
            http_status=200,
            content_hash="d4" * 32,
            excerpt="rohanv-dev - Rohan Verma - Lucknow - rohan@vermaagrotraders.example.in",
            fetched=True,
            robots_allowed=True,
            referenced_by=["qry_05"],
        ),
        Source(
            source_id="src_olx",
            url="https://www.olx.example.in/item/used-tractor-spare-parts-rohini-delhi-2019",
            canonical_url="https://www.olx.example.in/item/used-tractor-spare-parts-rohini-delhi-2019",
            domain="olx.example.in",
            title="Used tractor spare parts - Rohini, Delhi",
            source_type=SourceType.CLASSIFIED_LISTING,
            quality=SourceQuality.D,
            provider="fixture",
            retrieved_at=RUN_AT,
            published_at=_dt(2019, 8, 2),
            date_precision=DatePrecision.DAY,
            excerpt="Seller: Amit Kumar. Contact 98765 43210. Flat 4B, Rohini Sector 7, Delhi.",
            fetched=False,  # provider snippet only
            robots_allowed=None,
            referenced_by=["qry_02"],
        ),
        Source(
            source_id="src_news",
            url="https://news.example.in/lucknow/agri-traders-fair-2023",
            canonical_url="https://news.example.in/lucknow/agri-traders-fair-2023",
            domain="news.example.in",
            title="Lucknow Agri Fair 2023 draws 200 traders",
            source_type=SourceType.NEWS,
            quality=SourceQuality.B,
            provider="fixture",
            retrieved_at=RUN_AT,
            published_at=_dt(2023, 11, 20),
            date_precision=DatePrecision.DAY,
            excerpt="Stall holders included Verma Agro Traders (contact 98765 43210) of Transport Nagar.",
            fetched=False,
            referenced_by=["qry_06"],
        ),
        Source(
            source_id="src_forum",
            url="https://forum.example.in/threads/agro-supplier-recommendations-lucknow",
            canonical_url="https://forum.example.in/threads/agro-supplier-recommendations-lucknow",
            domain="forum.example.in",
            title="Agro supplier recommendations (Lucknow)?",
            source_type=SourceType.FORUM,
            quality=SourceQuality.D,
            provider="fixture",
            retrieved_at=RUN_AT,
            published_at=_dt(2022, 1, 1),
            date_precision=DatePrecision.YEAR,
            excerpt="Try Verma Agro in Transport Nagar, ask for Rohan.",
            fetched=False,
            referenced_by=["qry_06"],
        ),
    ]


def _finding(
    fid: str,
    field: FieldType,
    value: str,
    source: Source,
    *,
    entity_id: str | None,
    evidence: str,
    association: Association = Association.DIRECT,
    number_displayed: bool = True,
    confidence: float = 0.9,
    query_id: str = "qry_01",
    extractor: str = "regex",
) -> Finding:
    return Finding(
        finding_id=fid,
        phone=PHONE,
        entity_id=entity_id,
        field=field,
        value=value,
        normalized_value=value.lower(),
        source_id=source.source_id,
        source_url=source.url,
        source_type=source.source_type,
        source_quality=source.quality,
        evidence_text=evidence,
        discovered_at=RUN_AT,
        published_at=source.published_at,
        date_precision=source.date_precision,
        confidence=confidence,
        association=association,
        number_displayed=number_displayed,
        provider=source.provider,
        query_id=query_id,
        extractor=extractor,
    )


def _findings(sources: dict[str, Source]) -> list[Finding]:
    tender, company, jd = sources["src_tender"], sources["src_company"], sources["src_justdial"]
    li, gh, olx, news = sources["src_linkedin"], sources["src_github"], sources["src_olx"], sources["src_news"]
    forum = sources["src_forum"]
    return [
        _finding("fnd_01", FieldType.NAME, "Rohan Verma", tender, entity_id="ent_rohan",
                 evidence="Contact person: Rohan Verma, Mob: +91 98765 43210", query_id="qry_03",
                 extractor="pdf_text"),
        _finding("fnd_02", FieldType.BUSINESS, "Verma Agro Traders", tender, entity_id="ent_rohan",
                 evidence="Bidder: Verma Agro Traders ... Mob: +91 98765 43210", query_id="qry_03",
                 extractor="pdf_text"),
        _finding("fnd_03", FieldType.ADDRESS, "Plot 12, Transport Nagar, Lucknow, Uttar Pradesh 226012",
                 tender, entity_id="ent_rohan",
                 evidence="Registered office: Plot 12, Transport Nagar, Lucknow, Uttar Pradesh 226012.",
                 query_id="qry_03", extractor="pdf_text", confidence=0.85),
        _finding("fnd_04", FieldType.NAME, "Rohan Verma", company, entity_id="ent_rohan",
                 evidence="Proprietor: Rohan Verma | Phone: 98765 43210", extractor="html_text"),
        _finding("fnd_05", FieldType.EMAIL, "rohan@vermaagrotraders.example.in", company, entity_id="ent_rohan",
                 evidence="Phone: 98765 43210 | Email: rohan@vermaagrotraders.example.in", extractor="html_text"),
        _finding("fnd_06", FieldType.WEBSITE, "vermaagrotraders.example.in", company, entity_id="ent_rohan",
                 evidence="https://www.vermaagrotraders.example.in/contact", extractor="url", confidence=0.95),
        _finding("fnd_07", FieldType.BUSINESS, "Verma Agro Traders", jd, entity_id="ent_rohan",
                 evidence="Verma Agro Traders - Fertilizer Dealers. Call 9876543210", extractor="html_text",
                 confidence=0.8),
        _finding("fnd_08", FieldType.PHONE, ALT_PHONE, jd, entity_id="ent_rohan",
                 evidence="Call 9876543210, 9123456780.", extractor="regex", confidence=0.8),
        _finding("fnd_09", FieldType.LOCATION, "Lucknow, Uttar Pradesh", jd, entity_id="ent_rohan",
                 evidence="Plot 12, Transport Nagar, Lucknow.", extractor="location", confidence=0.8),
        _finding("fnd_10", FieldType.SOCIAL_PROFILE, "https://www.linkedin.example/in/rohan-verma-agro", li,
                 entity_id="ent_rohan", evidence="Rohan Verma. Proprietor at Verma Agro Traders. Lucknow",
                 association=Association.INDIRECT, number_displayed=False, confidence=0.6, query_id="qry_04",
                 extractor="snippet"),
        _finding("fnd_11", FieldType.JOB_TITLE, "Proprietor", li, entity_id="ent_rohan",
                 evidence="Proprietor at Verma Agro Traders", association=Association.INFERRED,
                 number_displayed=False, confidence=0.5, query_id="qry_04", extractor="snippet"),
        _finding("fnd_12", FieldType.USERNAME, "rohanv-dev", gh, entity_id="ent_rohan",
                 evidence="rohanv-dev - Rohan Verma - rohan@vermaagrotraders.example.in",
                 association=Association.INDIRECT, number_displayed=False, confidence=0.65, query_id="qry_05",
                 extractor="html_text"),
        _finding("fnd_13", FieldType.NAME, "Amit Kumar", olx, entity_id="ent_amit",
                 evidence="Seller: Amit Kumar. Contact 98765 43210.", query_id="qry_02", extractor="snippet",
                 confidence=0.7),
        _finding("fnd_14", FieldType.LOCATION, "Delhi", olx, entity_id="ent_amit",
                 evidence="Rohini Sector 7, Delhi", query_id="qry_02", extractor="location", confidence=0.7),
        _finding("fnd_15", FieldType.ADDRESS, "Flat 4B, Rohini Sector 7, Delhi 110085", olx, entity_id="ent_amit",
                 evidence="Flat 4B, Rohini Sector 7, Delhi.", query_id="qry_02", extractor="snippet",
                 confidence=0.6),
        _finding("fnd_16", FieldType.LISTING, "Used tractor spare parts - Rohini, Delhi", olx,
                 entity_id="ent_amit", evidence="Used tractor spare parts ... Contact 98765 43210",
                 query_id="qry_02", extractor="snippet", confidence=0.7),
        _finding("fnd_17", FieldType.MENTION, "Verma Agro Traders stall at Lucknow Agri Fair 2023", news,
                 entity_id="ent_rohan", evidence="Verma Agro Traders (contact 98765 43210) of Transport Nagar.",
                 query_id="qry_06", extractor="snippet", confidence=0.75),
        _finding("fnd_18", FieldType.ALIAS, "Rohan", forum, entity_id="ent_rohan",
                 evidence="Try Verma Agro in Transport Nagar, ask for Rohan.",
                 association=Association.INFERRED, number_displayed=False, confidence=0.3, query_id="qry_06",
                 extractor="snippet"),
    ]


def make_sample_investigation() -> Investigation:
    """Return a complete, deterministic, synthetic investigation for ``+919876543210``."""
    sources = _sources()
    by_id = {s.source_id: s for s in sources}
    findings = _findings(by_id)

    rohan_score = ScoreBreakdown(
        components=[
            ScoreComponent(rule="exact_phone_match", points=40,
                           reason="Number literally displayed on tender PDF, company website and directory listing",
                           finding_ids=["fnd_01", "fnd_04", "fnd_07"]),
            ScoreComponent(rule="same_name_multiple_sources", points=25,
                           reason="'Rohan Verma' appears with the number on 2 independent domains",
                           finding_ids=["fnd_01", "fnd_04"]),
            ScoreComponent(rule="same_business", points=15,
                           reason="'Verma Agro Traders' on tender, website, directory and news",
                           finding_ids=["fnd_02", "fnd_07", "fnd_17"]),
            ScoreComponent(rule="same_location", points=10, reason="Lucknow on 4 sources",
                           finding_ids=["fnd_03", "fnd_09"]),
            ScoreComponent(rule="same_email", points=10,
                           reason="rohan@vermaagrotraders.example.in on company site and GitHub profile",
                           finding_ids=["fnd_05", "fnd_12"]),
            ScoreComponent(rule="multiple_independent_sources", points=10,
                           reason="5 independent registrable domains", finding_ids=[]),
            ScoreComponent(rule="official_or_primary_source", points=10,
                           reason="Government tender portal (quality A)", finding_ids=["fnd_01"]),
            ScoreComponent(rule="direct_association", points=5, reason="Best association is DIRECT",
                           finding_ids=["fnd_01"]),
            ScoreComponent(rule="contradictory_name", points=-30,
                           reason="A 2019 classified listing names a different seller (Amit Kumar)",
                           finding_ids=["fnd_13"]),
        ],
        total_points=95,
        percent=88,
        label=ConfidenceLabel.STRONG_MATCH,
        note="Analytical estimate (95 raw points normalised against a 108-point practical ceiling); "
             "not factual certainty.",
    )
    amit_score = ScoreBreakdown(
        components=[
            ScoreComponent(rule="exact_phone_match", points=40,
                           reason="Number displayed on a 2019 classified listing", finding_ids=["fnd_13"]),
            ScoreComponent(rule="direct_association", points=5, reason="Number shown on the listing itself",
                           finding_ids=["fnd_13"]),
            ScoreComponent(rule="stale_evidence_only", points=-10, reason="Only evidence is from 2019",
                           finding_ids=["fnd_13"]),
        ],
        total_points=35,
        percent=35,
        label=ConfidenceLabel.CONTRADICTORY,
        note="Single low-quality, stale source that conflicts with the stronger 2023-2024 evidence.",
    )

    entities = [
        Entity(
            entity_id="ent_rohan",
            kind=EntityKind.PERSON,
            label="Rohan Verma",
            names=["Rohan Verma", "Rohan"],
            emails=["rohan@vermaagrotraders.example.in"],
            usernames=["rohanv-dev"],
            businesses=["Verma Agro Traders"],
            websites=["vermaagrotraders.example.in"],
            locations=["Lucknow, Uttar Pradesh"],
            addresses=["Plot 12, Transport Nagar, Lucknow, Uttar Pradesh 226012"],
            job_titles=["Proprietor"],
            associated_numbers=[ALT_PHONE],
            social_profile_ids=["prf_linkedin", "prf_github"],
            document_ids=["doc_tender"],
            finding_ids=[f"fnd_{i:02d}" for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 17, 18)],
            source_ids=["src_tender", "src_company", "src_justdial", "src_linkedin", "src_github",
                        "src_news", "src_forum"],
            independent_source_count=5,
            association=Association.DIRECT,
            score=rohan_score,
            first_seen=_dt(2022, 1, 1),
            last_seen=_dt(2024, 3, 15),
            contradiction_ids=["ctr_name", "ctr_temporal"],
            why_linked=[
                "Number displayed next to 'Rohan Verma' on a 2024 government tender PDF (quality A)",
                "Company website lists the number with the same name and e-mail",
                "Directory listing (2023) shows the same business and a co-listed number",
                "GitHub profile shares the company e-mail (indirect link, number not displayed)",
            ],
        ),
        Entity(
            entity_id="ent_amit",
            kind=EntityKind.PERSON,
            label="Amit Kumar",
            names=["Amit Kumar"],
            locations=["Delhi"],
            addresses=["Flat 4B, Rohini Sector 7, Delhi 110085"],
            finding_ids=["fnd_13", "fnd_14", "fnd_15", "fnd_16"],
            source_ids=["src_olx"],
            independent_source_count=1,
            association=Association.DIRECT,
            score=amit_score,
            first_seen=_dt(2019, 8, 2),
            last_seen=_dt(2019, 8, 2),
            contradiction_ids=["ctr_name", "ctr_temporal"],
            why_linked=[
                "Number displayed as seller contact on a 2019 classified listing (quality D)",
                "No corroboration from any other source; may be a previous user of the number",
            ],
        ),
    ]

    social_profiles = [
        SocialProfile(
            profile_id="prf_linkedin", platform="LinkedIn", username="rohan-verma-agro",
            display_name="Rohan Verma", profile_url="https://www.linkedin.example/in/rohan-verma-agro",
            source_url="https://www.linkedin.example/in/rohan-verma-agro",
            matching_text="Proprietor at Verma Agro Traders. Lucknow", discovered_at=RUN_AT,
            confidence=0.6, number_displayed=False, association=Association.INDIRECT,
            finding_ids=["fnd_10"], entity_id="ent_rohan",
        ),
        SocialProfile(
            profile_id="prf_github", platform="GitHub", username="rohanv-dev", display_name="Rohan Verma",
            profile_url="https://github.example/rohanv-dev", source_url="https://github.example/rohanv-dev",
            matching_text="rohan@vermaagrotraders.example.in", discovered_at=RUN_AT, confidence=0.65,
            number_displayed=False, association=Association.INDIRECT, finding_ids=["fnd_12"],
            entity_id="ent_rohan",
        ),
    ]

    businesses = [
        Business(
            business_id="biz_verma", name="Verma Agro Traders", owner="Rohan Verma",
            category="Fertilizer Dealers", address="Plot 12, Transport Nagar, Lucknow, Uttar Pradesh 226012",
            city="Lucknow", website="https://www.vermaagrotraders.example.in",
            email="rohan@vermaagrotraders.example.in", social_urls=["https://www.linkedin.example/in/rohan-verma-agro"],
            other_numbers=[ALT_PHONE], source_ids=["src_tender", "src_company", "src_justdial", "src_news"],
            finding_ids=["fnd_02", "fnd_07", "fnd_17"], entity_id="ent_rohan",
        )
    ]

    listings = [
        Listing(
            listing_id="lst_olx", title="Used tractor spare parts - Rohini, Delhi", seller_name="Amit Kumar",
            category="Spare parts", location="Rohini, Delhi",
            url="https://www.olx.example.in/item/used-tractor-spare-parts-rohini-delhi-2019",
            published_at=_dt(2019, 8, 2), other_contacts=[], source_id="src_olx",
            finding_ids=["fnd_13", "fnd_14", "fnd_15", "fnd_16"], entity_id="ent_amit",
        )
    ]

    addresses = [
        Address(
            address_id="adr_lucknow", raw="Plot 12, Transport Nagar, Lucknow, Uttar Pradesh 226012",
            city="Lucknow", state="Uttar Pradesh", pincode="226012",
            classification=AddressClass.REGISTERED_BUSINESS,
            classification_reason="Stated as 'registered office' in a government tender document",
            source_id="src_tender", finding_ids=["fnd_03"], published_at=_dt(2024, 3, 15),
            date_precision=DatePrecision.DAY, entity_id="ent_rohan",
        ),
        Address(
            address_id="adr_delhi", raw="Flat 4B, Rohini Sector 7, Delhi 110085", city="Delhi", state="Delhi",
            pincode="110085", classification=AddressClass.RESIDENTIAL_LOOKING,
            classification_reason="'Flat' prefix and residential sector on a classified listing",
            source_id="src_olx", finding_ids=["fnd_15"], published_at=_dt(2019, 8, 2),
            date_precision=DatePrecision.DAY, entity_id="ent_amit",
        ),
    ]

    locations = [
        Location(location_id="loc_lucknow", city="Lucknow", state="Uttar Pradesh", label="Lucknow, Uttar Pradesh",
                 finding_ids=["fnd_03", "fnd_09"], source_count=4, entity_id="ent_rohan"),
        Location(location_id="loc_delhi", city="Delhi", state="Delhi", label="Delhi",
                 finding_ids=["fnd_14"], source_count=1, entity_id="ent_amit"),
    ]

    documents = [
        Document(
            document_id="doc_tender",
            title="Tender Notice 2024/117 - Supply of Agricultural Inputs (Lucknow Division)",
            url="https://eprocure.gov.example/tenders/2024/verma-agro-supply.pdf", doc_type="pdf",
            author="Procurement Cell", organization="Lucknow Division (example)", published_at=_dt(2024, 3, 15),
            date_precision=DatePrecision.DAY, phones=[PHONE], emails=["rohan@vermaagrotraders.example.in"],
            names=["Rohan Verma"], addresses=["Plot 12, Transport Nagar, Lucknow, Uttar Pradesh 226012"],
            urls=["https://www.vermaagrotraders.example.in"], fetched=True, content_hash="a1" * 32,
            source_id="src_tender", finding_ids=["fnd_01", "fnd_02", "fnd_03"], entity_id="ent_rohan",
        )
    ]

    associated_numbers = [
        AssociatedNumber(
            e164=ALT_PHONE, masked=mask_phone(ALT_PHONE), relation="publicly_co_listed",
            reason="Listed alongside the subject number on the same directory entry for Verma Agro Traders",
            source_id="src_justdial",
            source_url="https://www.justdial.example/lucknow/verma-agro-traders-transport-nagar",
            finding_id="fnd_08", entity_id="ent_rohan", confidence=0.8, discovered_at=RUN_AT,
            published_at=_dt(2023, 6, 10),
        )
    ]

    timeline = [
        TimelineEvent(date=_dt(2019, 8, 2), precision=DatePrecision.DAY,
                      description="Number shown as seller contact 'Amit Kumar' on a Delhi classified listing",
                      finding_id="fnd_13", source_id="src_olx", source_url=by_id["src_olx"].url,
                      entity_id="ent_amit", kind="classified_listing"),
        TimelineEvent(date=_dt(2022, 1, 1), precision=DatePrecision.YEAR,
                      description="Forum post recommends 'Verma Agro' (number not displayed)",
                      finding_id="fnd_18", source_id="src_forum", source_url=by_id["src_forum"].url,
                      entity_id="ent_rohan", kind="public_mention"),
        TimelineEvent(date=_dt(2023, 6, 10), precision=DatePrecision.MONTH,
                      description="Directory listing for Verma Agro Traders shows the number (co-listed with +919123456780)",
                      finding_id="fnd_07", source_id="src_justdial", source_url=by_id["src_justdial"].url,
                      entity_id="ent_rohan", kind="business_listing"),
        TimelineEvent(date=_dt(2023, 11, 20), precision=DatePrecision.DAY,
                      description="News article mentions Verma Agro Traders stall with the number",
                      finding_id="fnd_17", source_id="src_news", source_url=by_id["src_news"].url,
                      entity_id="ent_rohan", kind="news"),
        TimelineEvent(date=_dt(2024, 3, 15), precision=DatePrecision.DAY,
                      description="Government tender PDF lists Rohan Verma as contact person with the number",
                      finding_id="fnd_01", source_id="src_tender", source_url=by_id["src_tender"].url,
                      entity_id="ent_rohan", kind="document"),
    ]

    phone_node = f"phone:{PHONE}"
    relationships = [
        Relationship(relationship_id="rel_01", from_id=phone_node, to_id="ent_rohan", relation="CANDIDATE_IDENTITY",
                     finding_ids=["fnd_01", "fnd_04"], source_ids=["src_tender", "src_company"], confidence=0.88,
                     association=Association.DIRECT, first_seen=_dt(2022, 1, 1), last_seen=_dt(2024, 3, 15)),
        Relationship(relationship_id="rel_02", from_id="ent_rohan", to_id="name:Rohan Verma", relation="HAS_NAME",
                     finding_ids=["fnd_01", "fnd_04"], source_ids=["src_tender", "src_company"], confidence=0.9,
                     association=Association.DIRECT),
        Relationship(relationship_id="rel_03", from_id="ent_rohan", to_id="email:rohan@vermaagrotraders.example.in",
                     relation="HAS_EMAIL", finding_ids=["fnd_05"], source_ids=["src_company"], confidence=0.9,
                     association=Association.DIRECT),
        Relationship(relationship_id="rel_04", from_id="ent_rohan", to_id="username:rohanv-dev",
                     relation="HAS_USERNAME", finding_ids=["fnd_12"], source_ids=["src_github"], confidence=0.65,
                     association=Association.INDIRECT),
        Relationship(relationship_id="rel_05", from_id="ent_rohan", to_id="business:Verma Agro Traders",
                     relation="RUNS_BUSINESS", finding_ids=["fnd_02", "fnd_07"],
                     source_ids=["src_tender", "src_justdial"], confidence=0.85, association=Association.DIRECT),
        Relationship(relationship_id="rel_06", from_id="ent_rohan", to_id="location:Lucknow, Uttar Pradesh",
                     relation="LOCATED_IN", finding_ids=["fnd_09"], source_ids=["src_justdial"], confidence=0.8,
                     association=Association.DIRECT),
        Relationship(relationship_id="rel_07", from_id="business:Verma Agro Traders", to_id=f"phone:{ALT_PHONE}",
                     relation="CO_LISTED_WITH", finding_ids=["fnd_08"], source_ids=["src_justdial"],
                     confidence=0.8, association=Association.DIRECT),
        Relationship(relationship_id="rel_08", from_id="ent_rohan", to_id="profile:linkedin/rohan-verma-agro",
                     relation="HAS_PROFILE", finding_ids=["fnd_10"], source_ids=["src_linkedin"], confidence=0.6,
                     association=Association.INDIRECT),
        Relationship(relationship_id="rel_09", from_id=phone_node, to_id="ent_amit", relation="CANDIDATE_IDENTITY",
                     finding_ids=["fnd_13"], source_ids=["src_olx"], confidence=0.35,
                     association=Association.DIRECT, first_seen=_dt(2019, 8, 2), last_seen=_dt(2019, 8, 2)),
        Relationship(relationship_id="rel_10", from_id="ent_amit", to_id="name:Amit Kumar", relation="HAS_NAME",
                     finding_ids=["fnd_13"], source_ids=["src_olx"], confidence=0.7,
                     association=Association.DIRECT),
        Relationship(relationship_id="rel_11", from_id="ent_amit", to_id="location:Delhi", relation="LOCATED_IN",
                     finding_ids=["fnd_14"], source_ids=["src_olx"], confidence=0.7,
                     association=Association.DIRECT),
    ]

    contradictions = [
        Contradiction(
            contradiction_id="ctr_name", kind=ContradictionKind.NAME_CONFLICT,
            description="The number is displayed with 'Rohan Verma' (2023-2024, Lucknow) and with 'Amit Kumar' "
                        "(2019, Delhi).",
            entity_ids=["ent_rohan", "ent_amit"], finding_ids=["fnd_01", "fnd_13"], severity="high",
            resolution_hint="Check whether the 2019 listing is still live and whether the number was reassigned "
                            "or transferred between 2019 and 2023.",
        ),
        Contradiction(
            contradiction_id="ctr_temporal", kind=ContradictionKind.TEMPORAL_CHANGE,
            description="Public association of the number changed from a Delhi classified seller (2019) to a "
                        "Lucknow business (2023 onwards).",
            entity_ids=["ent_rohan", "ent_amit"], finding_ids=["fnd_13", "fnd_07"], severity="medium",
            resolution_hint="Treat pre-2023 evidence as historical; verify current association via the "
                            "company's own contact page.",
        ),
    ]

    graph_nodes = [
        {"id": phone_node, "label": PHONE, "kind": "phone"},
        {"id": "ent_rohan", "label": "Rohan Verma", "kind": "entity", "percent": 88},
        {"id": "ent_amit", "label": "Amit Kumar", "kind": "entity", "percent": 35},
        {"id": "name:Rohan Verma", "label": "Rohan Verma", "kind": "name"},
        {"id": "email:rohan@vermaagrotraders.example.in", "label": "rohan@vermaagrotraders.example.in",
         "kind": "email"},
        {"id": "username:rohanv-dev", "label": "rohanv-dev", "kind": "username"},
        {"id": "business:Verma Agro Traders", "label": "Verma Agro Traders", "kind": "business"},
        {"id": "location:Lucknow, Uttar Pradesh", "label": "Lucknow, Uttar Pradesh", "kind": "location"},
        {"id": f"phone:{ALT_PHONE}", "label": ALT_PHONE, "kind": "phone"},
        {"id": "profile:linkedin/rohan-verma-agro", "label": "LinkedIn: rohan-verma-agro", "kind": "profile"},
        {"id": "name:Amit Kumar", "label": "Amit Kumar", "kind": "name"},
        {"id": "location:Delhi", "label": "Delhi", "kind": "location"},
    ]
    graph_edges = [
        {"source": r.from_id, "target": r.to_id, "relation": r.relation, "association": r.association.value,
         "confidence": r.confidence}
        for r in relationships
    ]
    graph = {"directed": True, "multigraph": True, "graph": {"phone": PHONE}, "nodes": graph_nodes,
             "edges": graph_edges}

    queries = [
        QueryRecord(query_id="qry_01", provider="fixture", query=f'"{PHONE}"', stage=Stage.SEARCH,
                    purpose="exact phone match", executed_at=RUN_AT, results_count=4, new_results_count=4,
                    information_gain=1.0),
        QueryRecord(query_id="qry_02", provider="fixture", query='"9876543210"', stage=Stage.SEARCH,
                    purpose="exact phone match (national)", executed_at=RUN_AT, results_count=5,
                    new_results_count=2, information_gain=0.4),
        QueryRecord(query_id="qry_03", provider="fixture", query='"98765 43210" filetype:pdf',
                    stage=Stage.DOCUMENTS, purpose="documents", executed_at=RUN_AT, results_count=1,
                    new_results_count=1, information_gain=1.0),
        QueryRecord(query_id="qry_04", provider="fixture", query='"Rohan Verma" Lucknow', stage=Stage.LEAD_EXPANSION,
                    purpose="lead: name=Rohan Verma", lead_id="lead_name", executed_at=RUN_AT, results_count=6,
                    new_results_count=1, information_gain=0.17),
        QueryRecord(query_id="qry_05", provider="fixture", query='"rohan@vermaagrotraders.example.in"',
                    stage=Stage.LEAD_EXPANSION, purpose="lead: email", lead_id="lead_email", executed_at=RUN_AT,
                    results_count=2, new_results_count=1, information_gain=0.5),
        QueryRecord(query_id="qry_06", provider="fixture", query='"Verma Agro Traders"', stage=Stage.BUSINESS,
                    purpose="lead: business", lead_id="lead_business", executed_at=RUN_AT, results_count=8,
                    new_results_count=3, information_gain=0.38, cached=True),
    ]

    leads = [
        Lead(lead_id="lead_name", lead_type=LeadType.NAME, value="Rohan Verma", normalized_value="rohan verma",
             relevance=0.82, depth=1, origin_finding_ids=["fnd_01", "fnd_04"], investigated=True, queries_run=1,
             information_gain=0.17, reasons=["2 sources", "quality A", "direct association"]),
        Lead(lead_id="lead_email", lead_type=LeadType.EMAIL, value="rohan@vermaagrotraders.example.in",
             normalized_value="rohan@vermaagrotraders.example.in", relevance=0.9, depth=1,
             origin_finding_ids=["fnd_05"], investigated=True, queries_run=1, information_gain=0.5,
             reasons=["email lead", "quality A"]),
        Lead(lead_id="lead_business", lead_type=LeadType.BUSINESS, value="Verma Agro Traders",
             normalized_value="verma agro traders", relevance=0.78, depth=1, origin_finding_ids=["fnd_02", "fnd_07"],
             investigated=True, queries_run=1, information_gain=0.38, reasons=["2 sources", "business lead"]),
    ]

    telecom = [
        TelecomResult(provider="libphonenumber", timestamp=RUN_AT, field="country", value="India (+91)",
                      confidence=1.0),
        TelecomResult(provider="libphonenumber", timestamp=RUN_AT, field="number_type", value="mobile",
                      confidence=0.95),
        TelecomResult(provider="libphonenumber", timestamp=RUN_AT, field="original_carrier",
                      value="Example Telecom", confidence=0.5,
                      note="Numbering-plan allocation only; MNP means the current carrier may differ."),
        TelecomResult(provider="libphonenumber", timestamp=RUN_AT, field="original_circle",
                      value="Uttar Pradesh (East)", confidence=0.5,
                      note="Original allocation circle; not the current location of the subscriber."),
        TelecomResult(provider="libphonenumber", timestamp=RUN_AT, field="timezone", value="Asia/Kolkata",
                      confidence=0.9),
    ]

    meta = InvestigationMeta(
        investigation_id="inv_sample01",
        started_at=RUN_AT,
        finished_at=DONE_AT,
        depth=Depth.STANDARD,
        authorization_note="Synthetic test investigation; no real subject.",
        case_reference="CASE-TEST-001",
        providers=[
            ProviderInfo(name="fixture", category="search", state=ProviderState.AVAILABLE),
            ProviderInfo(name="libphonenumber", category="phone", state=ProviderState.AVAILABLE),
            ProviderInfo(name="brave", category="search", state=ProviderState.MISSING_KEY, paid=True,
                         reason="BRAVE_API_KEY not set"),
            ProviderInfo(name="github", category="social", state=ProviderState.DISABLED,
                         reason="offline mode"),
            ProviderInfo(name="maigret", category="username", state=ProviderState.NOT_INSTALLED,
                         reason="optional dependency missing"),
        ],
        stages=[
            StageResult(stage=Stage.NORMALIZE, status=StageStatus.DONE, started_at=RUN_AT, finished_at=RUN_AT,
                        counts={"variants": 13}),
            StageResult(stage=Stage.TELECOM, status=StageStatus.DONE, started_at=RUN_AT, finished_at=RUN_AT,
                        counts={"results": 5}),
            StageResult(stage=Stage.SEARCH, status=StageStatus.DONE, started_at=RUN_AT, finished_at=RUN_AT,
                        counts={"queries": 2, "results": 9}),
            StageResult(stage=Stage.DOCUMENTS, status=StageStatus.DONE, started_at=RUN_AT, finished_at=RUN_AT,
                        counts={"documents": 1}),
            StageResult(stage=Stage.LEAD_EXPANSION, status=StageStatus.DONE, started_at=RUN_AT,
                        finished_at=RUN_AT, counts={"leads": 3, "queries": 3}),
            StageResult(stage=Stage.SOCIAL, status=StageStatus.SKIPPED, message="offline mode"),
            StageResult(stage=Stage.CORRELATION, status=StageStatus.DONE, started_at=RUN_AT,
                        finished_at=RUN_AT, counts={"entities": 2, "contradictions": 2}),
            StageResult(stage=Stage.SCORING, status=StageStatus.DONE, started_at=RUN_AT, finished_at=DONE_AT,
                        counts={"entities": 2}),
        ],
        config={"depth": "standard", "offline": True, "max_queries": 60},
    )

    summary = ExecutiveSummary(
        candidate_identity="Rohan Verma",
        candidate_kind=EntityKind.PERSON,
        confidence_percent=88,
        confidence_label=ConfidenceLabel.STRONG_MATCH,
        possible_location="Lucknow, Uttar Pradesh",
        public_businesses=1,
        public_emails=1,
        public_usernames=1,
        public_profiles=2,
        public_documents=1,
        associated_public_numbers=1,
        candidate_count=2,
        contradiction_count=2,
        sources_consulted=len(sources),
        queries_executed=len(queries),
        headline="The number is publicly displayed with 'Rohan Verma' / Verma Agro Traders (Lucknow) on a 2024 "
                 "government tender, the company's own website and a 2023 directory listing. A 2019 classified "
                 "listing associates it with a different seller in Delhi; this may reflect an earlier user of "
                 "the number. Public-source associations are not proof of identity.",
    )

    confidence = ConfidenceSummary(
        top_entity_id="ent_rohan",
        top_percent=88,
        top_label=ConfidenceLabel.STRONG_MATCH,
        rules={
            "exact_phone_match": 40, "same_name_multiple_sources": 25, "same_business": 15, "same_location": 10,
            "same_email": 10, "same_username": 10, "multiple_independent_sources": 10,
            "official_or_primary_source": 10, "direct_association": 5, "contradictory_location": -30,
            "contradictory_name": -30, "evidence_belongs_to_other_person": -50, "low_quality_sources_only": -15,
            "inferred_only": -20, "stale_evidence_only": -10,
        },
        per_entity={"ent_rohan": 88, "ent_amit": 35},
    )

    limitations = [
        "Only publicly accessible sources were consulted; no login-protected, breach or telecom-subscriber data "
        "was used.",
        "Carrier and circle come from the numbering plan; Mobile Number Portability means they may be outdated.",
        "Public-source associations are not proof of identity; the number may have been reassigned or reused.",
        "Provider snippets for un-fetched pages (LinkedIn, OLX, news, forum) were not verified against the live "
        "page.",
        "Search coverage was limited to the offline fixture provider; live search engines were not queried.",
    ]

    return Investigation(
        investigation=meta,
        phone=make_sample_phone(),
        telecom=telecom,
        entities=entities,
        names=["Rohan Verma", "Amit Kumar"],
        emails=["rohan@vermaagrotraders.example.in"],
        usernames=["rohanv-dev"],
        social_profiles=social_profiles,
        businesses=businesses,
        listings=listings,
        locations=locations,
        addresses=addresses,
        documents=documents,
        associated_numbers=associated_numbers,
        timeline=timeline,
        relationships=relationships,
        contradictions=contradictions,
        sources=sources,
        queries=queries,
        findings=findings,
        leads=leads,
        confidence=confidence,
        summary=summary,
        graph=graph,
        limitations=limitations,
    )


__all__ = ["make_sample_investigation", "make_sample_phone", "PHONE", "ALT_PHONE"]
