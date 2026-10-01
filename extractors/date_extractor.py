"""Date extraction for Indian-style text (DD/MM/YYYY) plus page-date heuristics (spec section 15)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.models import DatePrecision

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"])}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|" \
       r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ISO_RE = re.compile(r"\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?\b")
_DMY_TEXT_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\.?,?\s+((?:19|20)\d{{2}})\b", re.I)
_MDY_TEXT_RE = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+((?:19|20)\d{{2}})\b", re.I)
_NUMERIC_RE = re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.]((?:19|20)\d{2}|\d{2})(?!\d)")
_MONTH_YEAR_RE = re.compile(rf"\b({_MON})\.?,?\s+((?:19|20)\d{{2}})\b", re.I)
_YEAR_CTX_RE = re.compile(r"(?i)\b(posted|updated|dated|published|©|copyright|on|since|est\.?|established)\s*[:\-]?\s*"
                          r"((?:20[0-3]\d)|(?:200\d))\b")
_LABELLED_RE = re.compile(r"(?i)\b(posted|published|updated|dated|date|last modified|modified)\s*(?:on)?\s*[:\-–]?\s*")


@dataclass
class DateMatch:
    date: datetime
    precision: DatePrecision
    start: int
    end: int
    raw: str


def _dt(y: int, m: int, d: int) -> Optional[datetime]:
    try:
        return datetime(y, m, d, tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_iso(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    m = _ISO_RE.match(v)
    if m:
        return _dt(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DMY_TEXT_RE.search(v) or _MDY_TEXT_RE.search(v)
    if m:
        matches = extract_dates(v)
        return matches[0].date if matches else None
    return None


def extract_dates(text: str) -> list[DateMatch]:
    if not text:
        return []
    text = text[:200_000]
    out: list[DateMatch] = []
    taken: list[tuple[int, int]] = []

    def free(s: int, e: int) -> bool:
        return not any(s < te and e > ts for ts, te in taken)

    def add(dt: Optional[datetime], prec: DatePrecision, s: int, e: int, raw: str) -> None:
        if dt and free(s, e) and 1990 <= dt.year <= 2035:
            taken.append((s, e))
            out.append(DateMatch(date=dt, precision=prec, start=s, end=e, raw=raw))

    for m in _ISO_RE.finditer(text):
        add(_dt(int(m.group(1)), int(m.group(2)), int(m.group(3))), DatePrecision.DAY, m.start(), m.end(), m.group(0))
    for m in _DMY_TEXT_RE.finditer(text):
        add(_dt(int(m.group(3)), _MONTHS.get(m.group(2).lower()[:3], 0), int(m.group(1))), DatePrecision.DAY,
            m.start(), m.end(), m.group(0))
    for m in _MDY_TEXT_RE.finditer(text):
        add(_dt(int(m.group(3)), _MONTHS.get(m.group(1).lower()[:3], 0), int(m.group(2))), DatePrecision.DAY,
            m.start(), m.end(), m.group(0))
    for m in _NUMERIC_RE.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if mo > 12 and d <= 12:  # clearly MM/DD -> swap
            d, mo = mo, d
        add(_dt(y, mo, d), DatePrecision.DAY, m.start(), m.end(), m.group(0))
    for m in _MONTH_YEAR_RE.finditer(text):
        add(_dt(int(m.group(2)), _MONTHS.get(m.group(1).lower()[:3], 0), 1), DatePrecision.MONTH, m.start(), m.end(),
            m.group(0))
    for m in _YEAR_CTX_RE.finditer(text):
        add(_dt(int(m.group(2)), 1, 1), DatePrecision.YEAR, m.start(2), m.end(2), m.group(2))
    out.sort(key=lambda d: d.start)
    return out


def best_page_date(text: str, meta: dict | None = None) -> tuple[Optional[datetime], DatePrecision]:
    """Prefer structured metadata, then labelled dates in text, else nothing."""
    meta = meta or {}
    for key in ("article:published_time", "datePublished", "date", "dc.date", "dcterms.created", "pubdate",
                "publish-date", "og:updated_time", "article:modified_time", "last-modified", "dateModified"):
        for k, v in meta.items():
            if k.lower() == key.lower() and v:
                dt = parse_iso(str(v))
                if dt:
                    return dt, DatePrecision.DAY
    dates = extract_dates(text or "")
    labelled = []
    for m in _LABELLED_RE.finditer(text or ""):
        for d in dates:
            if 0 <= d.start - m.end() <= 3:
                labelled.append(d)
    if labelled:
        best = min(labelled, key=lambda d: d.date)
        return best.date, best.precision
    return None, DatePrecision.UNKNOWN
