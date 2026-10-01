"""
Indian phone-number normalisation and search-variant generation (spec section 3).

Design notes
------------
* We lean on Google libphonenumber (``phonenumbers``) for validation and
  formatting, but pre-clean the input ourselves because Indian numbers are
  written in many informal ways (``(98)76543210``, ``98-7654-3210``,
  ``+91 0 98765 43210`` ...).
* We never guess a carrier or circle here.  Mobile Number Portability (MNP)
  has been nationwide in India since 2015, so a prefix only tells you the
  *original* allocation.  Carrier hints live in ``providers/phone`` and are
  labelled as such.
* Non-Indian numbers are normalised too (so the engine can refuse them with a
  useful message) but ``is_indian`` is False.
"""

from __future__ import annotations

import re

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

from core.models import NormalizedPhone, PhoneKind, mask_phone

_TYPE_MAP: dict[int, PhoneKind] = {
    PhoneNumberType.MOBILE: PhoneKind.MOBILE,
    PhoneNumberType.FIXED_LINE: PhoneKind.FIXED_LINE,
    PhoneNumberType.FIXED_LINE_OR_MOBILE: PhoneKind.FIXED_LINE_OR_MOBILE,
    PhoneNumberType.TOLL_FREE: PhoneKind.TOLL_FREE,
    PhoneNumberType.PREMIUM_RATE: PhoneKind.PREMIUM_RATE,
    PhoneNumberType.SHARED_COST: PhoneKind.SHARED_COST,
    PhoneNumberType.VOIP: PhoneKind.VOIP,
    PhoneNumberType.UAN: PhoneKind.UAN,
    PhoneNumberType.UNKNOWN: PhoneKind.UNKNOWN,
}

_NON_DIGIT = re.compile(r"[^\d+]")


def clean_digits(raw: str) -> tuple[str, bool]:
    """Return (digits, had_plus).  Removes spaces, dashes, brackets, dots, unicode dashes."""
    s = raw.strip()
    # unicode dashes / spaces
    s = s.replace("‐", "-").replace("‑", "-").replace("‒", "-").replace("–", "-")
    s = s.replace("—", "-").replace(" ", " ").replace(" ", " ")
    # "00" international prefix -> "+"
    if s.startswith("00"):
        s = "+" + s[2:]
    had_plus = s.startswith("+")
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits, had_plus


def to_e164_candidate(raw: str) -> tuple[str, list[str]]:
    """
    Best-effort conversion of an informal Indian number string to an E.164
    candidate.  Returns (candidate, notes).  The candidate still has to be
    validated by libphonenumber.
    """
    notes: list[str] = []
    digits, had_plus = clean_digits(raw)
    if not digits:
        return "", ["no digits found"]

    if had_plus:
        # +91 0 98765 43210 -> drop the trunk '0' after the country code
        if digits.startswith("910") and len(digits) == 13:
            notes.append("dropped trunk prefix '0' after +91")
            digits = "91" + digits[3:]
        return "+" + digits, notes

    n = len(digits)
    if n == 10:
        if digits[0] in "6789":
            return "+91" + digits, notes
        if digits.startswith("140") or digits.startswith("160"):
            notes.append("140/160-series (TRAI telemarketing / transactional prefix)")
            return "+91" + digits, notes
        if digits.startswith("1800") or digits.startswith("1860"):
            return "+91" + digits, notes
        # possibly a landline written without trunk prefix (e.g. 2212345678 for Delhi 011)
        notes.append("10 digits not starting with 6-9; treated as Indian national number")
        return "+91" + digits, notes
    if n == 11:
        if digits.startswith("0"):
            notes.append("dropped national trunk prefix '0'")
            return "+91" + digits[1:], notes
        if digits.startswith("1800") or digits.startswith("1860"):
            return "+91" + digits, notes
    if n == 12 and digits.startswith("91"):
        return "+" + digits, notes
    if n == 13 and digits.startswith("091"):
        notes.append("dropped leading '0' before country code")
        return "+" + digits[1:], notes
    if n == 13 and digits.startswith("910"):
        notes.append("dropped trunk prefix '0' after 91")
        return "+91" + digits[3:], notes
    if n == 13:
        notes.append("13-digit number: possibly Indian M2M numbering")
        return "+91" + digits[-10:], notes  # will most likely be flagged invalid
    if n == 14 and digits.startswith("910"):
        notes.append("dropped trunk prefix '0' after 91")
        return "+91" + digits[3:], notes
    # fallback: let libphonenumber try with region IN
    return digits, notes


def _search_variants(subscriber: str, kind: PhoneKind) -> tuple[list[str], list[str]]:
    """Generate search-engine variants for an Indian national significant number."""
    variants: list[str] = []
    if len(subscriber) == 10 and kind in (
        PhoneKind.MOBILE,
        PhoneKind.FIXED_LINE_OR_MOBILE,
        PhoneKind.UNKNOWN,
        PhoneKind.TELEMARKETING,
    ):
        a, b = subscriber[:5], subscriber[5:]
        variants = [
            f"+91{subscriber}",
            f"91{subscriber}",
            f"0{subscriber}",
            subscriber,
            f"{a} {b}",
            f"+91 {a} {b}",
            f"+91 {subscriber}",
            f"+91-{subscriber}",
            f"{subscriber[:2]}-{subscriber[2:6]}-{subscriber[6:]}",
            f"{subscriber[:2]} {subscriber[2:6]} {subscriber[6:]}",
            f"{subscriber[:3]} {subscriber[3:6]} {subscriber[6:]}",
            f"{subscriber[:3]}-{subscriber[3:6]}-{subscriber[6:]}",
            f"0{a} {b}",
        ]
    elif kind == PhoneKind.FIXED_LINE and len(subscriber) == 10:
        variants = [f"+91{subscriber}", f"0{subscriber}", subscriber, f"91{subscriber}"]
        # try common STD splits (2/3/4-digit area codes)
        for k in (2, 3, 4):
            variants.append(f"0{subscriber[:k]}-{subscriber[k:]}")
            variants.append(f"0{subscriber[:k]} {subscriber[k:]}")
            variants.append(f"+91 {subscriber[:k]} {subscriber[k:]}")
    else:
        variants = [f"+91{subscriber}", subscriber, f"91{subscriber}", f"0{subscriber}"]
        if subscriber.startswith("1800") or subscriber.startswith("1860"):
            rest = subscriber[4:]
            if len(rest) == 7:
                variants.append(f"{subscriber[:4]} {rest[:3]} {rest[3:]}")
                variants.append(f"{subscriber[:4]}-{rest[:3]}-{rest[3:]}")
            elif len(rest) == 6:
                variants.append(f"{subscriber[:4]} {rest[:3]} {rest[3:]}")
    # dedupe preserving order
    seen: set[str] = set()
    ordered = [v for v in variants if not (v in seen or seen.add(v))]  # type: ignore[func-returns-value]
    quoted = [f'"{v}"' for v in ordered]
    return ordered, quoted


def normalize_indian_number(raw: str) -> NormalizedPhone:
    """
    Normalise any reasonable rendering of an Indian phone number.

    >>> normalize_indian_number("(98)76543210").e164
    '+919876543210'
    """
    result = NormalizedPhone(raw=raw)
    candidate, notes = to_e164_candidate(raw)
    result.notes.extend(notes)
    if not candidate:
        result.kind = PhoneKind.INVALID
        result.warnings.append("No digits found in input.")
        return result

    try:
        parsed = phonenumbers.parse(candidate, "IN")
    except NumberParseException as exc:  # pragma: no cover - defensive
        result.kind = PhoneKind.INVALID
        result.warnings.append(f"Could not parse number: {exc}")
        return result

    result.country_code = parsed.country_code
    result.region = phonenumbers.region_code_for_number(parsed) or ("IN" if parsed.country_code == 91 else "")
    result.is_indian = parsed.country_code == 91
    result.subscriber = phonenumbers.national_significant_number(parsed)
    result.is_possible = phonenumbers.is_possible_number(parsed)
    result.is_valid = phonenumbers.is_valid_number(parsed)
    result.e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    result.national = phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)
    result.international = phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL)
    result.masked = mask_phone(result.e164)

    ntype = phonenumbers.number_type(parsed)
    kind = _TYPE_MAP.get(ntype, PhoneKind.UNKNOWN)
    sub = result.subscriber
    if result.is_indian:
        if sub.startswith(("140", "160")) and len(sub) == 10:
            kind = PhoneKind.TELEMARKETING
            result.notes.append(
                "140/160-series numbers are allocated by TRAI for telemarketing/transactional calls "
                "and normally belong to registered senders, not individuals."
            )
        elif len(sub) == 13:
            kind = PhoneKind.M2M
        elif len(sub) < 10 and not result.is_valid:
            kind = PhoneKind.SERVICE if len(sub) <= 6 else kind
    if not result.is_valid and kind in (PhoneKind.UNKNOWN,):
        kind = PhoneKind.INVALID
    result.kind = kind

    if not result.is_indian:
        result.warnings.append(
            f"Number is not Indian (country code +{parsed.country_code}, region {result.region or '?'}). "
            "This engine only investigates Indian numbers."
        )
    if result.is_indian and not result.is_valid:
        result.warnings.append("Number does not match a valid Indian numbering-plan range.")
    if result.is_indian and result.is_valid and kind == PhoneKind.FIXED_LINE:
        result.notes.append("Number is a fixed-line (landline) number; searches use STD-code variants.")
    if result.is_indian and result.is_valid and kind == PhoneKind.TOLL_FREE:
        result.notes.append("Toll-free numbers usually belong to organisations, not individuals.")
    if result.is_indian and result.is_valid and kind == PhoneKind.MOBILE:
        result.notes.append(
            "Mobile Number Portability: the prefix indicates original allocation only; the current "
            "operator and service area may differ."
        )

    if result.is_indian and result.subscriber:
        result.variants, result.quoted_variants = _search_variants(result.subscriber, kind)
    return result


def looks_like_indian_number(text: str) -> bool:
    """Quick predicate used by extractors/tests."""
    digits, _ = clean_digits(text)
    return len(digits) in (10, 11, 12, 13) and (
        digits[-10] in "6789" or digits[-10:].startswith(("1800", "1860", "140", "160"))
    )
