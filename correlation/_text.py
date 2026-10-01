"""
Small, dependency-free text helpers shared by the correlation and scoring layers.

These deliberately do *not* import from ``extractors`` (which is written
concurrently) except for the stable ``extractors.url_utils`` module.  Every
helper here is pure and deterministic so that entity resolution and scoring
produce the same output for the same input.
"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from extractors.url_utils import host_of, normalize_website, registrable_domain

# Honorifics stripped before comparing person names (Indian + generic English usage).
HONORIFICS: frozenset[str] = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "shri", "sri", "shree", "smt", "adv", "ca", "er", "prof", "mx"}
)

# Suffix / keyword table used to recognise business names.  Order matters only for display.
BUSINESS_SUFFIXES: tuple[str, ...] = (
    "pvt ltd", "private limited", "limited", "ltd", "llp", "enterprises", "traders", "industries",
    "solutions", "technologies", "services", "consultancy", "associates", "& sons", "and sons", "agency",
    "agencies", "stores", "hospital", "clinic", "school", "academy", "institute", "restaurant", "hotel",
    "motors", "builders", "developers", "realty", "textiles", "jewellers", "electricals", "electronics",
    "agro", "foods", "exports", "logistics", "travels", "studio", "foundation", "trust", "society",
)

# Business names consisting of *only* one of these words carry no identifying information.
GENERIC_BUSINESS_WORDS: frozenset[str] = frozenset(
    w for w in BUSINESS_SUFFIXES if " " not in w
) | frozenset({"company", "co", "corporation", "group", "pvt", "private"})

_PUNCT_RE = re.compile(r"[^\w\s&]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _basic_clean(text: str) -> str:
    text = (text or "").strip().lower().replace(".", " ")
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def normalise_name(name: str) -> str:
    """
    Lower-case a person name, drop punctuation and leading/trailing honorifics.

    ``"Shri Rohan Verma"`` -> ``"rohan verma"``; ``"Dr. A. K. Singh"`` -> ``"a k singh"``.
    """
    tokens = _basic_clean(name).split()
    while tokens and tokens[0] in HONORIFICS:
        tokens.pop(0)
    while tokens and tokens[-1] in HONORIFICS:
        tokens.pop()
    return " ".join(tokens)


def name_tokens(name: str) -> list[str]:
    return normalise_name(name).split()


def is_full_name(name: str) -> bool:
    """A name with at least two non-honorific tokens (used for conflict detection)."""
    return len(name_tokens(name)) >= 2


def normalise_business(name: str) -> str:
    """Lower-case, punctuation-free business name with ``&`` -> ``and``."""
    text = _basic_clean(name).replace("&", " and ")
    return _WS_RE.sub(" ", text).strip()


def is_business_name(name: str) -> bool:
    """True if the name ends with / contains a known business suffix (``Verma Agro Traders``)."""
    norm = f" {normalise_business(name)} "
    return any(f" {suffix.replace('&', 'and')} " in norm for suffix in BUSINESS_SUFFIXES)


def is_generic_business(name: str) -> bool:
    """``"Services"`` / ``"Enterprises"`` alone carry no identity."""
    tokens = normalise_business(name).split()
    return bool(tokens) and all(t in GENERIC_BUSINESS_WORDS for t in tokens)


def token_set_ratio(a: str, b: str) -> float:
    """
    Token-set similarity in ``0..1`` (same construction as fuzzywuzzy's ``token_set_ratio``,
    implemented on :mod:`difflib` so no third-party dependency is needed).

    Word order is ignored; a name that is a strict subset of the other scores 1.0.
    """
    ta, tb = set(_basic_clean(a).split()), set(_basic_clean(b).split())
    if not ta or not tb:
        return 0.0
    inter = " ".join(sorted(ta & tb))
    diff_a = " ".join(sorted(ta - tb))
    diff_b = " ".join(sorted(tb - ta))
    t0 = inter
    t1 = (inter + " " + diff_a).strip()
    t2 = (inter + " " + diff_b).strip()

    def _r(x: str, y: str) -> float:
        if not x and not y:
            return 1.0
        if not x or not y:
            return 0.0
        return SequenceMatcher(None, x, y).ratio()

    return max(_r(t0, t1), _r(t0, t2), _r(t1, t2))


def names_fuzzy_equal(a: str, b: str, threshold: float = 0.85) -> bool:
    """Names are fuzzy-equal when they share a token and their token-set ratio meets the threshold."""
    ta, tb = set(name_tokens(a)), set(name_tokens(b))
    if not ta or not tb or not (ta & tb):
        return False
    return token_set_ratio(normalise_name(a), normalise_name(b)) >= threshold


def normalise_email(email: str) -> str:
    return (email or "").strip().lower().strip("<>()[].,;:")


def normalise_city(city: str) -> str:
    return _basic_clean(city)


def normalise_username(username: str) -> str:
    return (username or "").strip().lower().lstrip("@")


def normalise_domain(url_or_domain: str) -> str:
    return normalize_website(url_or_domain or "")


def address_hash(address: str) -> str:
    return hashlib.sha1(_basic_clean(address).encode("utf-8")).hexdigest()[:12]


_DEMO_ROOTS = {"example.in", "example.com", "example.org", "example.net"}


def independent_domain(url: str) -> str:
    """
    Domain used to count *independent* sources.

    Real hosts collapse to their registrable domain (``sub.example.co.in`` -> ``example.co.in``).
    Synthetic fixture hosts (``justdial.example``, ``vermaagrotraders.example.in``) would all collapse
    to ``example``, so they are mapped through the fixture alias table / kept as full hosts instead.
    """
    host = host_of(url)
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(".example"):
        # local import: scoring.source_quality is a stable, existing module
        from scoring.source_quality import demo_host_alias

        alias_host, _ = demo_host_alias(host)
        return alias_host[4:] if alias_host.startswith("www.") else alias_host
    reg = registrable_domain(url)
    if reg in _DEMO_ROOTS:
        return host
    return reg or host


def display_domain(url: str) -> str:
    """Host without ``www.`` for human-readable sentences."""
    host = host_of(url)
    return host[4:] if host.startswith("www.") else host


def most_common_variant(variants: list[str]) -> str:
    """Pick the most frequent spelling; ties broken by longest, then alphabetical (deterministic)."""
    if not variants:
        return ""
    counts: dict[str, int] = {}
    for v in variants:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]


def join_human(items: list[str], limit: int = 5) -> str:
    items = list(items)
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:limit]) + f" and {len(items) - limit} more"
