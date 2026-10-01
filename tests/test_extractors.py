"""Extractor tests on synthetic text (no real people; example domains only)."""

from datetime import datetime, timezone

from pypdf import PdfWriter

from core.models import AddressClass, Association, DatePrecision, FieldType, LeadType, Source
from core.normalize import normalize_indian_number
from extractors.address_extractor import classify_address, extract_addresses, extract_locations, extract_pincodes
from extractors.business_extractor import extract_business_names, is_business_name
from extractors.date_extractor import best_page_date, extract_dates, parse_iso
from extractors.document_extractor import extract_document
from extractors.email_extractor import extract_emails
from extractors.name_extractor import extract_person_names, is_generic_name
from extractors.page_extractor import extract_from_text
from extractors.phone_extractor import extract_phones, subject_number_positions
from extractors.text_utils import normalise_name, strip_html, token_set_ratio
from extractors.username_extractor import extract_profiles

PHONE = normalize_indian_number("+919876543210")

CONTACT_PAGE = """Verma Agro Traders - Contact Us
Proprietor: Rohan Verma
Registered Office: Shop No. 12, Vibhuti Khand, Gomti Nagar, Lucknow, Uttar Pradesh 226010
Mobile: +91 98765 43210, Alternate: +91 91234 56780, Landline: 0522-4098765
Email: rohan@vermaagrotraders.example.in | Support: support [at] vermaagrotraders [dot] example [dot] in
Follow: https://www.linkedin.example/in/rohan-verma-lko https://github.example/rohanv-dev
GSTIN 09ABCDE1234F1Z5. Reference ID 1234567890123. Aadhaar-like 1234 5678 9012 must not be extracted.
Posted on 12 March 2024. Invoice amount 9876543210.50 is an amount, not a phone.
"""


def test_phone_extraction_and_non_matches():
    found = {p.e164 for p in extract_phones(CONTACT_PAGE)}
    assert "+919876543210" in found and "+919123456780" in found and "+915224098765" in found
    assert not any(e.endswith("9012") or "1234567890123" in e for e in found)
    assert "+911234567890" not in found  # 13-digit reference id must not yield a number
    pos = subject_number_positions("call 98765 43210 or +91-9876543210 or 09876543210 but not 9876543299", PHONE)
    assert len(pos) == 3


def test_email_extraction_including_obfuscated():
    emails = {e.email for e in extract_emails(CONTACT_PAGE)}
    assert "rohan@vermaagrotraders.example.in" in emails
    assert "support@vermaagrotraders.example.in" in emails
    assert not any(e.endswith(".png") for e in emails)


def test_profile_urls_and_reserved_paths():
    profs = extract_profiles(CONTACT_PAGE)
    platforms = {(p.platform, p.username) for p in profs}
    assert ("linkedin", "rohan-verma-lko") in platforms
    assert ("github", "rohanv-dev") in platforms
    assert not extract_profiles("see https://www.linkedin.com/login and https://github.com/features")


def test_person_names_precision():
    names = {c.name for c in extract_person_names(CONTACT_PAGE)}
    assert "Rohan Verma" in names
    assert "Verma Agro Traders" not in names
    assert "Gomti Nagar" not in names and "Vibhuti Khand" not in names and "Registered Office" not in names
    plain = {c.name for c in extract_person_names("Drip Irrigation and Organic Fertilizer Dealers near High Court")}
    assert plain == set()
    assert is_generic_name("Kumar") and not is_generic_name("Rohan Verma")
    assert normalise_name("Dr. Rohan  Verma") == "rohan verma"
    assert token_set_ratio("Rohan Verma", "Verma Rohan") > 0.9


def test_business_names():
    names = {c.name for c in extract_business_names(CONTACT_PAGE)}
    assert "Verma Agro Traders" in names
    assert is_business_name("Sharma Enterprises Pvt Ltd") and not is_business_name("Rohan Verma")


def test_addresses_locations_pincodes():
    assert extract_pincodes("PIN 226010, amount Rs 226011") == ["226010"]
    addrs = extract_addresses(CONTACT_PAGE)
    assert any(a.pincode == "226010" and a.city in ("Lucknow", "Gomti Nagar") for a in addrs)
    cls, _ = classify_address("Registered Office: Shop No. 12, Gomti Nagar")
    assert cls == AddressClass.REGISTERED_BUSINESS
    assert classify_address("Flat 4B, Green Society, Dwarka")[0] == AddressClass.RESIDENTIAL_LOOKING
    assert classify_address("Shop 3, Aminabad Market")[0] == AddressClass.COMMERCIAL
    assert classify_address("Somewhere")[0] == AddressClass.UNKNOWN
    locs = {(l.city, l.state) for l in extract_locations("We serve Bangalore and Lucknow, Uttar Pradesh")}
    assert ("Bengaluru", "Karnataka") in locs and ("Lucknow", "Uttar Pradesh") in locs


def test_dates_indian_formats():
    ds = extract_dates("Posted 12/06/2019. Updated on 3 Feb 2024, also February 5, 2024 and 2023-04-01 and Jun 2021.")
    got = {(d.date.date().isoformat(), d.precision) for d in ds}
    assert ("2019-06-12", DatePrecision.DAY) in got  # DD/MM/YYYY
    assert ("2024-02-03", DatePrecision.DAY) in got
    assert ("2024-02-05", DatePrecision.DAY) in got
    assert ("2023-04-01", DatePrecision.DAY) in got
    assert ("2021-06-01", DatePrecision.MONTH) in got
    assert parse_iso("2024-02-10T00:00:00Z").year == 2024
    dt, prec = best_page_date("Published: 12 Jun 2019", {})
    assert dt == datetime(2019, 6, 12, tzinfo=timezone.utc) and prec == DatePrecision.DAY
    dt, _ = best_page_date("", {"article:published_time": "2022-01-05T10:00:00+05:30"})
    assert dt and dt.year == 2022


def test_document_extraction_pdf_and_text():
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_metadata({"/Title": "Bid Document 2024", "/Author": "Procurement Cell", "/CreationDate": "D:20240210120000"})
    import io

    buf = io.BytesIO()
    w.write(buf)
    doc = extract_document(buf.getvalue(), "application/pdf", "https://tenders.gov.example/bid.pdf")
    assert doc.doc_type == "pdf" and doc.title == "Bid Document 2024" and doc.author == "Procurement Cell"
    assert doc.created and doc.created.year == 2024 and doc.pages == 1 and not doc.error
    txt = extract_document(b"Contact 9876543210", "text/plain", "https://x.example/a.txt")
    assert "9876543210" in txt.text
    assert extract_document(b"", "application/pdf", "u").error


def test_strip_html():
    page = strip_html("<html><head><title>T</title><meta name='author' content='A'><script>x()</script></head>"
                      "<body><p>Hello <b>world</b></p></body></html>")
    assert page.title == "T" and "Hello world" in page.text and "x()" not in page.text
    assert page.meta.get("author") == "A"


def test_extract_from_text_end_to_end_direct():
    src = Source(url="https://www.vermaagrotraders.example.in/contact.html", title="Contact Us", provider="fixture")
    ext = extract_from_text(CONTACT_PAGE, phone=PHONE, source=src, title=src.title, url=src.url, is_full_page=True)
    assert ext.number_displayed
    fields = {(f.field, f.value) for f in ext.findings}
    assert (FieldType.NAME, "Rohan Verma") in fields
    assert (FieldType.EMAIL, "rohan@vermaagrotraders.example.in") in fields
    assert (FieldType.BUSINESS, "Verma Agro Traders") in fields
    assert (FieldType.PHONE, "+919123456780") in fields
    assert (FieldType.WEBSITE, "vermaagrotraders.example.in") in fields
    assert all(f.association == Association.DIRECT for f in ext.findings)
    assert all(f.evidence_text for f in ext.findings)
    co = next(f for f in ext.findings if f.field == FieldType.PHONE and f.value == "+919123456780")
    assert co.metadata["co_listed"] is True
    lead_types = {(l.lead_type, l.value) for l in ext.leads}
    assert (LeadType.NAME, "Rohan Verma") in lead_types and (LeadType.EMAIL, "rohan@vermaagrotraders.example.in") in lead_types
    assert (LeadType.PHONE, "+919123456780") in lead_types
    job = next(f for f in ext.findings if f.field == FieldType.JOB_TITLE)
    assert job.metadata["for_name"] == "Rohan Verma"


def test_extract_from_text_inferred_when_number_absent():
    src = Source(url="https://www.linkedin.example/in/rohan-verma-lko", title="Rohan Verma - Proprietor", provider="fixture")
    ext = extract_from_text("Rohan Verma - Proprietor at Verma Agro Traders, Lucknow", phone=PHONE, source=src,
                            title=src.title, url=src.url)
    assert not ext.number_displayed
    name = next(f for f in ext.findings if f.field == FieldType.NAME)
    assert name.association == Association.INFERRED and name.confidence < 0.9
    assert all(not f.number_displayed for f in ext.findings)
    assert not any(l.lead_type == LeadType.PHONE for l in ext.leads)


def test_mention_fallback():
    src = Source(url="https://random.example/page", title="Page", provider="fixture")
    ext = extract_from_text("Call 9876543210 today!!!", phone=PHONE, source=src, title="", url=src.url)
    assert ext.number_displayed
    assert [f.field for f in ext.findings] == [FieldType.MENTION]
