"""
Indian phone-number extraction from free text.

The regex is deliberately *tolerant* about formatting (``+91 98765 43210``,
``098765-43210``, ``(0522) 409-8765``, ``1800 123 4567`` ...) and deliberately
*strict* about what is accepted afterwards:

* every candidate is validated by ``core.normalize.normalize_indian_number``;
* digit runs are never split: a 13+ digit contiguous run (IDs, account numbers)
  or an Aadhaar-like 12-digit run is never reported, and a phone is never
  carved out of a longer run of digits;
* amounts (``9876543210.50``), years, pincodes and GSTIN/PAN fragments fall out
  because they are either too short, followed by a decimal fraction, or bound
  to letters.

Public API
----------
``extract_phones(text) -> list[PhoneMatch]``
``subject_number_positions(text, phone) -> list[tuple[int, int]]``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, Optional

from core.models import NormalizedPhone, PhoneKind
from core.normalize import normalize_indian_number
from extractors.text_utils import truncate

# A candidate is: optional "+", then 1..6 digit groups separated by a single
# space / dash / dot (optionally " - "), groups may be wrapped in brackets.
# Word boundaries on both sides keep us out of alphanumeric IDs; the trailing
# look-ahead refuses decimal fractions (amounts) and digits glued to letters.
_CANDIDATE_RE = re.compile(
    r"""
    (?<![\w+])                       # no letter/digit/plus immediately before
    (?P<plus>\+\s?)?                 # optional international plus
    \(?\d{1,20}\)?                   # first digit run (may be bracketed STD code)
    (?:(?:\s?[-.]\s?|\s)\(?\d{1,20}\)?){0,5}   # up to five more runs, single separator each
    (?!\w)(?!\.\d)                   # not glued to a word char, not a decimal
    """,
    re.VERBOSE,
)
_RUN_RE = re.compile(r"\d+")
_DECIMAL_TAIL_RE = re.compile(r"\.\d")
_MAX_MATCHES = 500


@dataclass(frozen=True)
class PhoneMatch:
    """One phone number located in text."""

    e164: str
    raw: str
    start: int
    end: int
    kind: str  # PhoneKind value, e.g. "mobile"


def _plausible_layout(runs: list[str], had_plus: bool, subject_digits: str) -> bool:
    """Formatting-based rejection rules that libphonenumber cannot express."""
    digits = "".join(runs)
    n = len(digits)
    if n < 10 or n > 13:
        return False
    if subject_digits and digits in (subject_digits, subject_digits[2:], "0" + subject_digits[2:]):
        return True  # the subject number itself, in any of its plain renderings
    if len(runs) == 1:  # one contiguous run
        if n == 13:
            return False  # M2M / IDs are never extracted from a bare 13-digit run
        if n == 12:
            # Only "91" + mobile is accepted contiguously (wa.me/919876543210 style);
            # anything else looks like an Aadhaar number or an account/ID.
            return digits.startswith("91") and digits[2] in "6789"
        if n == 11:
            return digits[0] == "0" or digits.startswith(("1800", "1860"))
        if n == 10:
            return digits[0] in "6789" or digits.startswith(("1800", "1860", "140", "160"))
        return True
    if n == 12 and len(runs) == 3 and all(len(r) == 4 for r in runs):
        return False  # "2345 6789 0123" - Aadhaar formatting
    if n == 12 and not had_plus and not digits.startswith("91"):
        return False
    if n == 13 and not (digits.startswith("091") or digits.startswith("910")):
        return False
    return True


def _iter_candidates(text: str, subject_digits: str = "") -> Iterator[tuple[int, int, str, NormalizedPhone]]:
    """
    Yield ``(start, end, raw, normalized)`` for every validated Indian number.

    A regex match that fails validation as a whole is retried after trimming
    leading/trailing digit *groups* (never splitting a contiguous run), so
    ``"9876543210 2019"`` still yields the phone.
    """
    count = 0
    for m in _CANDIDATE_RE.finditer(text):
        body = m.group(0)
        base = m.start()
        runs = [(r.start() + base, r.end() + base, r.group(0)) for r in _RUN_RE.finditer(body)]
        if not runs:
            continue
        found: Optional[tuple[int, int, str, NormalizedPhone]] = None
        n_runs = len(runs)
        # try longest sub-sequences first, bounded (<= 21 combos for 6 runs)
        for size in range(n_runs, 0, -1):
            for i in range(0, n_runs - size + 1):
                sub = runs[i:i + size]
                had_plus = i == 0 and m.group("plus") is not None
                if not _plausible_layout([r[2] for r in sub], had_plus, subject_digits):
                    continue
                start = m.start() if had_plus else sub[0][0]
                # include a bracket immediately before the first digit
                if not had_plus and start > 0 and text[start - 1] == "(":
                    start -= 1
                end = sub[-1][1]
                if _DECIMAL_TAIL_RE.match(text, end):
                    continue  # "9876543210.50" is an amount, not a phone
                if end < len(text) and text[end] == ")":
                    end += 1
                raw = text[start:end]
                norm = normalize_indian_number(raw)
                if norm.is_valid and norm.is_indian and len(norm.subscriber) in (10, 11):
                    found = (start, end, raw, norm)
                    break
            if found:
                break
        if found:
            count += 1
            yield found
            if count >= _MAX_MATCHES:
                return


def extract_phones(text: str) -> list[PhoneMatch]:
    """Return every valid Indian phone number written in ``text`` (in order of appearance)."""
    text = truncate(text)
    if not text:
        return []
    out: list[PhoneMatch] = []
    for start, end, raw, norm in _iter_candidates(text):
        kind = norm.kind.value if isinstance(norm.kind, PhoneKind) else str(norm.kind)
        out.append(PhoneMatch(e164=norm.e164, raw=raw, start=start, end=end, kind=kind))
    return out


def subject_number_positions(text: str, phone: NormalizedPhone) -> list[tuple[int, int]]:
    """
    Every ``(start, end)`` span at which the subject number appears in ``text``,
    whatever the written variant (``+91 98765 43210``, ``098765 43210``,
    ``9876543210``, ``tel:+919876543210`` ...).  Digit-aware: the number must
    not be embedded in a longer digit run.
    """
    text = truncate(text)
    if not text or not phone.e164:
        return []
    subject_digits = "".join(ch for ch in phone.e164 if ch.isdigit())
    target = phone.e164
    spans: list[tuple[int, int]] = []
    for start, end, _raw, norm in _iter_candidates(text, subject_digits):
        if norm.e164 == target:
            spans.append((start, end))
    return spans


__all__ = ["PhoneMatch", "extract_phones", "subject_number_positions"]
