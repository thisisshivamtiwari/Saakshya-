"""
Business / organisation name extraction.

Two strategies, both table-driven and deterministic:

* **suffix / keyword** - up to four Title-Case tokens followed by a business
  suffix (``Pvt Ltd``, ``LLP``, ``Enterprises``, ``Traders`` ...) or a trade
  keyword (``Hospital``, ``Cafe``, ``Jewellers`` ...);
* **labelled** - ``Company:``, ``Firm:``, ``Business Name:``, ``Seller:`` (only
  when the value looks like a business) and the Indian ``M/s`` prefix.

:func:`is_business_name` is shared with the person-name extractor so that
``Verma Agro Traders`` is never reported as a person.
"""

from __future__ import annotations

import re

from extractors.text_utils import NameCandidate, truncate

# strong legal suffixes (high confidence)
LEGAL_SUFFIXES: tuple[str, ...] = (
    "Pvt Ltd", "Pvt. Ltd.", "Pvt. Ltd", "Pvt Ltd.", "Private Limited", "Limited", "Ltd", "Ltd.", "LLP",
    "OPC", "Inc", "Inc.", "Corp", "Corporation", "Co.", "Company", "& Co", "& Co.", "and Co", "& Sons",
    "and Sons", "& Bros", "Brothers", "& Brothers", "Public Limited", "Plc",
)
# trade / activity keywords (medium confidence)
TRADE_KEYWORDS: tuple[str, ...] = (
    "Enterprises", "Enterprise", "Traders", "Trading", "Industries", "Industry", "Solutions", "Technologies",
    "Technology", "Tech", "Systems", "Services", "Consultancy", "Consultants", "Consulting", "Associates",
    "Agencies", "Agency", "Stores", "Store", "Mart", "Emporium", "Bazaar", "Bazar", "Hospital", "Hospitals",
    "Clinic", "Clinics", "Diagnostics", "Pharmacy", "Pharma", "Medicals", "Medical Store", "School", "Academy",
    "Institute", "Institution", "College", "University", "Classes", "Coaching", "Restaurant", "Cafe", "Café",
    "Hotel", "Hotels", "Resorts", "Resort", "Motors", "Automobiles", "Automotive", "Builders", "Developers",
    "Constructions", "Construction", "Infra", "Infrastructure", "Realty", "Realtors", "Properties", "Estates",
    "Textiles", "Garments", "Fashions", "Fashion", "Jewellers", "Jewelers", "Jewellery", "Electricals",
    "Electronics", "Hardware", "Steels", "Steel", "Metals", "Agro", "Agrotech", "Foods", "Dairy", "Exports",
    "Imports", "Exim", "Logistics", "Transport", "Transports", "Travels", "Tours", "Packers", "Movers",
    "Studio", "Studios", "Photography", "Events", "Decorators", "Caterers", "Foundation", "Trust", "Society",
    "Samiti", "Sangh", "Sangathan", "Nidhi", "Finance", "Fincorp", "Capital", "Cooperative", "Co-operative",
    "Co-op", "Ventures", "Holdings", "Group", "Labs", "Laboratories", "Mills", "Works", "Marketing", "Media",
    "Networks", "Digital", "Infotech", "Softwares", "Software", "Innovations", "Global", "International",
    "Overseas", "Chemicals", "Plastics", "Polymers", "Packaging", "Printers", "Publications", "Publishers",
    "Furnishers", "Furniture", "Interiors", "Designs", "Architects", "Engineers", "Engineering", "Contractors",
    "Suppliers", "Distributors", "Wholesalers", "Retail", "Supermarket", "Bakery", "Sweets", "Dhaba",
    "Nursing Home", "Dental", "Optical", "Opticals", "Salon", "Saloon", "Spa", "Gym", "Fitness", "Institute of",
    "Petrol Pump", "Filling Station", "Marbles", "Granites", "Tiles", "Ceramics", "Sanitary", "Paints",
    "Seeds", "Fertilizers", "Fertilisers", "Pesticides", "Nursery", "Farms", "Poultry", "Fisheries",
    "Apparels", "Sarees", "Boutique", "Handloom", "Handicrafts", "Crafts", "Toys", "Books", "Stationery",
    "Computers", "Mobiles", "Telecom", "Communications", "Cables", "Wires", "Pumps", "Machines", "Machinery",
    "Tools", "Equipments", "Equipment", "Instruments", "Devices", "Appliances", "Security", "Guards",
    "Manpower", "Placements", "HR", "Recruiters", "Academy of", "Institute for", "Insurance", "Securities",
    "Investments", "Credit", "Microfinance", "Chit Fund", "Chits", "Housing", "Bank",
)
_ALL_SUFFIXES = tuple(sorted(set(LEGAL_SUFFIXES + TRADE_KEYWORDS), key=len, reverse=True))


def _alt(words: tuple[str, ...]) -> str:
    return "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words)


_TOKEN = r"(?:[A-Z][A-Za-z0-9'’.&-]*|[A-Z][A-Z0-9&.]{1,6}|&|and|of|the|de)"
_SUFFIX_RE_SRC = r"(?P<suffix>" + _alt(_ALL_SUFFIXES) + r")\.?"
_TAIL_RE_SRC = (r"(?:\s+(?:" + _alt(LEGAL_SUFFIXES) + r"|India|\(India\)|International|Group|Overseas|Global"
                r"|Pvt|Private|Limited|Ltd|LLP)\.?){0,3}")
_BUSINESS_RE = re.compile(
    r"(?<![\w'’-])(?P<lead>(?:" + _TOKEN + r"[ \t]+){1,4})" + _SUFFIX_RE_SRC + _TAIL_RE_SRC + r"(?![\w'’-])"
)
_LABEL_RE = re.compile(
    r"(?:\b(?:Company|Firm|Business Name|Business|Organisation|Organization|Org|Trade Name|Legal Name|"
    r"Seller|Vendor|Dealer|Supplier|Shop Name|Store Name|Brand|Employer|Works at|Works for)\s*(?:name)?\s*[:\-–]\s*)"
    r"(?P<value>[A-Z][^\n,;|•]{2,80}?)(?=[\n,;|•]|\s{2,}|\s+(?:Phone|Mobile|Contact|Email|E-mail|Address|Tel|Ph)\b|$)",
    re.IGNORECASE,
)
_MS_RE = re.compile(r"\bM/s\.?\s+(?P<value>[A-Z][^\n,;|•(]{2,80}?)(?=[\n,;|•(]|\s{2,}|\s+(?:Phone|Mobile|Contact|Email|Address|Tel|Ph)\b|$)")
_BUSINESS_WORD_RE = re.compile(r"(?<![\w-])(?:" + _alt(_ALL_SUFFIXES) + r")\.?(?![\w-])", re.IGNORECASE)
_LEGAL_WORD_RE = re.compile(r"(?<![\w-])(?:" + _alt(LEGAL_SUFFIXES) + r")\.?(?![\w-])", re.IGNORECASE)

_LEADING_STOP = {
    "contact", "welcome", "about", "visit", "call", "our", "this", "best", "top", "leading", "dear", "from",
    "to", "with", "at", "in", "on", "for", "by", "and", "of", "near", "opposite", "behind", "opp", "the",
    "hi", "hello", "thanks", "regards", "sincerely", "yours", "please", "new", "old", "your", "my", "its",
    "is", "are", "was", "were", "as", "an", "a", "or", "but", "also", "we", "i", "you", "they", "he", "she",
    "director", "owner", "proprietor", "partner", "founder", "manager", "mr", "mrs", "ms", "dr", "shri", "smt",
    "posted", "listed", "seller", "buyer", "phone", "mobile", "email", "address", "name", "company", "firm",
    "website", "tel", "ph", "whatsapp", "team", "join", "join", "check", "see", "view", "click", "read", "more",
    "all", "any", "some", "other", "such", "each", "every", "both", "few", "many", "most", "several",
}
_MAX_RESULTS = 200


def _clean_lead_tokens(lead: str) -> str:
    toks = lead.split()
    # drop leading generic / label words
    while toks and toks[0].strip(".:,'’").lower() in _LEADING_STOP:
        toks.pop(0)
    while toks and toks[0] in ("&", "and", "of"):
        toks.pop(0)
    return " ".join(toks)


def is_business_name(name: str) -> bool:
    """True if ``name`` contains a legal suffix, trade keyword or the ``M/s`` prefix."""
    if not name:
        return False
    n = name.strip()
    if re.match(r"^M/s\.?\s", n, re.IGNORECASE):
        return True
    if _LEGAL_WORD_RE.search(n):
        return True
    m = _BUSINESS_WORD_RE.search(n)
    if not m:
        return False
    word = m.group(0).rstrip(".")
    if word.lower() == "bank":
        # "Bank" only counts when preceded by 2+ Title-Case words ("State Bank" is not enough)
        before = n[: m.start()].split()
        return len([t for t in before if t[:1].isupper()]) >= 2
    if word.lower() in ("group", "tech", "digital", "global", "international", "media", "works", "housing", "credit", "security", "guards", "hr", "retail"):
        # weak keywords need at least one other token before them
        return len(n[: m.start()].split()) >= 1 and n[: m.start()].strip() != ""
    return True


def _confidence(text: str) -> float:
    """Legal suffix (Pvt Ltd, LLP …) → 0.8; short trade-keyword names (≤3 tokens) → 0.65;
    long descriptive phrases ("Wholesaler of Certified Paddy Seeds") → 0.45 (below the lead threshold)."""
    if _LEGAL_WORD_RE.search(text):
        return 0.8
    toks = text.split()
    if len(toks) <= 3 and not any(t.lower() in ("of", "and", "&", "for") for t in toks):
        return 0.65
    return 0.45


def extract_business_names(text: str) -> list[NameCandidate]:
    """
    Return business / organisation names found in ``text`` (de-duplicated,
    highest confidence kept, ordered by first appearance).
    """
    text = truncate(text)
    if not text:
        return []
    found: dict[str, NameCandidate] = {}

    def _add(name: str, conf: float, start: int, end: int, reason: str) -> None:
        name = re.sub(r"\s+", " ", name).strip(" ,.;:-|")
        if ". " in name:  # never span a sentence boundary ("Us. Verma Agro Traders" -> "Verma Agro Traders")
            name = name.rsplit(". ", 1)[-1].strip()
        if len(name) < 4 or len(name) > 90:
            return
        toks = name.split()
        if len(toks) < 2 and not _LEGAL_WORD_RE.search(name):
            return
        key = name.lower()
        cur = found.get(key)
        if cur is None or conf > cur.confidence:
            found[key] = NameCandidate(name=name, confidence=conf, start=start, end=end, reason=reason)

    for m in _MS_RE.finditer(text):
        val = m.group("value").strip()
        _add(val, 0.9, m.start(), m.end(), "labelled:M/s")
        if len(found) >= _MAX_RESULTS:
            break

    for m in _LABEL_RE.finditer(text):
        val = m.group("value").strip()
        label = text[m.start():m.start("value")].strip().rstrip(":-– ").lower()
        if label.startswith(("seller", "vendor", "dealer", "supplier", "employer", "works")):
            if not is_business_name(val):
                continue
        elif not is_business_name(val) and len(val.split()) < 2:
            continue
        _add(val, 0.85, m.start(), m.end(), f"labelled:{label}")
        if len(found) >= _MAX_RESULTS:
            break

    for m in _BUSINESS_RE.finditer(text):
        lead = _clean_lead_tokens(m.group("lead"))
        if not lead:
            continue
        whole = lead + " " + text[m.start("suffix"):m.end()]
        suffix = m.group("suffix")
        if suffix.lower() == "bank" and len(lead.split()) < 2:
            continue
        start = m.end() - len(whole)
        _add(whole, _confidence(whole), max(m.start(), start), m.end(), f"suffix:{suffix}")
        if len(found) >= _MAX_RESULTS:
            break

    return sorted(found.values(), key=lambda c: c.start)


__all__ = ["LEGAL_SUFFIXES", "TRADE_KEYWORDS", "extract_business_names", "is_business_name"]
