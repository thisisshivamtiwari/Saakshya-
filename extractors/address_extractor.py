"""Indian address / location / pincode extraction and address classification (spec section 14)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.models import AddressClass
from extractors.data.india_cities import all_city_names, all_state_names, state_for_city

_CITY_MAP = all_city_names()  # spelling -> canonical
_STATE_MAP = all_state_names()  # spelling / abbreviation -> canonical
_CITY_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(c) for c in _CITY_MAP), key=len, reverse=True)) + r")\b")
_STATE_LONG = [s for s in _STATE_MAP if len(s) > 3]
_STATE_ABBR = [s for s in _STATE_MAP if len(s) <= 3]
_STATE_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(s) for s in _STATE_LONG), key=len, reverse=True)) + r")\b",
                       re.I)
_STATE_ABBR_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(s) for s in _STATE_ABBR) + r")(?![A-Za-z])")
_PIN_RE = re.compile(r"(?<!\d)(?:(?:PIN|Pin|pin|Pincode|PINCODE|Pin ?Code)\s*[:\-–]?\s*)?([1-9]\d{5})(?!\d)")
_ADDR_LABEL_RE = re.compile(
    r"(?i)\b(address|regd\.? office|registered office|corporate office|head office|office|add|located at|"
    r"branch office|works|factory|godown|plot no|shop no|h\.? ?no|house no|flat no)\s*[:\-–.]\s*(?P<addr>[^\n]{10,220})")
_ADDR_KEYWORDS = re.compile(
    r"(?i)\b(house|plot|shop|flat|floor|sector|road|marg|nagar|colony|gali|lane|chowk|bazar|bazaar|tower|complex|"
    r"plaza|apartment|apartments|society|enclave|vihar|extension|phase|block|street|st\.|main road|cross|layout|"
    r"industrial area|industrial estate|village|tehsil|district|dist\.|near|opp\.|opposite|behind)\b")


@dataclass
class LocationMatch:
    city: str
    state: str
    start: int
    end: int
    confidence: float


@dataclass
class AddressMatch:
    raw: str
    city: str
    state: str
    pincode: str
    start: int
    end: int
    confidence: float


def extract_pincodes(text: str) -> list[str]:
    out: list[str] = []
    for m in _PIN_RE.finditer(text or ""):
        # avoid amounts/years: require not immediately followed by '.' + digit and not preceded by '₹'/'Rs'
        pre = text[max(0, m.start() - 4):m.start()]
        if "₹" in pre or pre.strip().lower().endswith("rs") or pre.strip().endswith("."):
            continue
        val = m.group(1)
        if val not in out:
            out.append(val)
    return out


def extract_locations(text: str) -> list[LocationMatch]:
    if not text:
        return []
    text = text[:200_000]
    out: list[LocationMatch] = []
    seen: set[tuple[str, str]] = set()
    for m in _CITY_RE.finditer(text):
        canon = _CITY_MAP[m.group(1)]
        state = state_for_city(canon)
        if (canon, state) in seen:
            continue
        seen.add((canon, state))
        out.append(LocationMatch(city=canon, state=state, start=m.start(), end=m.end(), confidence=0.7))
    for m in _STATE_RE.finditer(text):
        key = next((s for s in _STATE_MAP if s.lower() == m.group(1).lower()), m.group(1))
        state = _STATE_MAP.get(key, key)
        if ("", state) in seen or any(s == state for _, s in seen):
            continue
        seen.add(("", state))
        out.append(LocationMatch(city="", state=state, start=m.start(), end=m.end(), confidence=0.5))
    return out


def classify_address(raw: str) -> tuple[AddressClass, str]:
    low = (raw or "").lower()
    if re.search(r"\b(regd\.?|registered)\s+office\b", low):
        return AddressClass.REGISTERED_BUSINESS, "mentions registered office"
    if re.search(r"\b(hospital|school|college|university|government|govt|nagar palika|municipal|panchayat|court|"
                 r"police|post office|railway station)\b", low):
        return AddressClass.PUBLIC_INSTITUTION, "public institution keyword"
    if re.search(r"\b(office|floor|tower|complex|plaza|suite|corporate|business park|it park|cabin)\b", low):
        return AddressClass.OFFICE, "office/floor/tower keyword"
    if re.search(r"\b(shop|market|mall|industrial area|industrial estate|bazaar|bazar|mandi|godown|warehouse|"
                 r"showroom|factory|works|unit no)\b", low):
        return AddressClass.COMMERCIAL, "commercial keyword"
    if re.search(r"\b(flat|house no|h\.? ?no|villa|apartment|society|colony|residency|bungalow|quarter)\b", low):
        return AddressClass.RESIDENTIAL_LOOKING, "residential keyword without commercial words"
    return AddressClass.UNKNOWN, "no classifying keyword"


def extract_addresses(text: str) -> list[AddressMatch]:
    if not text:
        return []
    text = text[:200_000]
    out: list[AddressMatch] = []
    seen: set[str] = set()

    def add(raw: str, start: int, end: int, conf: float) -> None:
        raw = " ".join(raw.split()).strip(" ,;.-")
        if len(raw) < 10 or raw.lower() in seen:
            return
        seen.add(raw.lower())
        pins = extract_pincodes(raw)
        locs = extract_locations(raw)
        city = next((l.city for l in locs if l.city), "")
        state = next((l.state for l in locs if l.state), state_for_city(city) if city else "")
        out.append(AddressMatch(raw=raw[:220], city=city, state=state, pincode=pins[0] if pins else "",
                                start=start, end=end, confidence=conf))

    for m in _ADDR_LABEL_RE.finditer(text):
        addr = m.group("addr")
        # cut at the next label-like token (Phone:, Email:, Mobile:)
        cut = re.search(r"(?i)\b(phone|mobile|email|e-mail|tel|contact|website|gst|fax)\s*[:\-]", addr)
        if cut:
            addr = addr[:cut.start()]
        add(addr, m.start("addr"), m.start("addr") + len(addr), 0.8)
    for m in _PIN_RE.finditer(text):
        start = max(0, m.start() - 160)
        span = text[start:m.end()]
        # keep the last line-ish chunk before the pincode
        span = span.split("\n")[-1]
        # cut at the sentence / label boundary preceding the first address keyword so that the previous
        # sentence ("Sales Desk +91 ...") does not leak into the address
        kw = _ADDR_KEYWORDS.search(span)
        if kw:
            head = span[:kw.start()]
            cut = max(head.rfind(". "), head.rfind(": "), head.rfind("; "), head.rfind(" | "))
            if cut >= 0:
                span = span[cut + 2:]
        if _ADDR_KEYWORDS.search(span) or _CITY_RE.search(span):
            add(span, m.end() - len(span), m.end(), 0.65)
    return out
