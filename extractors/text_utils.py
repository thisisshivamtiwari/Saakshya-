"""
Shared text helpers for the extractors package.

Everything here is pure Python / stdlib and deterministic:

* :func:`normalise_whitespace` - collapse runs of blanks while keeping line structure
* :func:`strip_html` - HTML -> visible text + title / meta / JSON-LD (``html.parser`` based)
* :func:`window` - bounded evidence window around a match
* :func:`normalise_name` - canonical lower-case person / business name for matching
* :func:`token_set_ratio` - difflib based fuzzy match on token sets (0..1)
* :class:`NameCandidate` - the dataclass shared by the name and business extractors
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

MAX_TEXT_CHARS = 200_000  # every extractor truncates its input to this many characters

_BLANK_RE = re.compile(r"[ \t\r\f\v  -​ 　]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_SPACE_NL_RE = re.compile(r"[ \t]*\n[ \t]*")

HONORIFICS: tuple[str, ...] = (
    "mr", "mrs", "ms", "miss", "dr", "shri", "smt", "sri", "er", "adv", "ca", "prof",
    "sh", "km", "kumari", "mohd", "md", "late", "capt", "col", "maj", "lt", "ar", "cs",
)
_HONORIFIC_RE = re.compile(
    r"^(?:(?:" + "|".join(HONORIFICS) + r")\.?\s+)+", re.IGNORECASE
)
_NAME_PUNCT_RE = re.compile(r"[^\w\s'&-]", re.UNICODE)


@dataclass
class NameCandidate:
    """A person or business name found in text (shared by name/business extractors)."""

    name: str
    confidence: float
    start: int
    end: int
    reason: str = ""


@dataclass
class PageText:
    """Visible text plus metadata pulled out of an HTML document."""

    text: str = ""
    title: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    jsonld: list[dict[str, Any]] = field(default_factory=list)


def truncate(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    """Bound input size for every extractor (defensive against huge pages)."""
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit]


def normalise_whitespace(text: str) -> str:
    """
    Collapse runs of spaces/tabs/NBSPs to one space, trim every line and collapse
    3+ consecutive newlines to 2.  Line breaks are preserved because several
    extractors (addresses) rely on "one line" heuristics.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_RE.sub(" ", text)
    text = _SPACE_NL_RE.sub("\n", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head", "iframe", "object"}
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "nav", "aside", "main", "address", "blockquote", "pre",
    "dd", "dt", "dl", "hr", "form", "fieldset", "figure", "figcaption", "summary", "details", "option",
}
_META_KEYS = {
    "description", "author", "keywords", "og:title", "og:description", "og:site_name", "og:url",
    "og:updated_time", "article:published_time", "article:modified_time", "article:author",
    "date", "pubdate", "publish-date", "publishdate", "dc.date", "dc.date.issued", "dc.creator",
    "dc.title", "last-modified", "datepublished", "datemodified", "twitter:title", "twitter:description",
    "geo.placename", "geo.region", "robots",
}
_JSONLD_KEYS = ("telephone", "name", "address", "email", "@type", "url", "datePublished", "dateModified",
                "author", "jobTitle", "legalName", "sameAs")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.jsonld_raw: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self._chars = 0

    # -- tags ------------------------------------------------------------- #
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs}
            key = (a.get("name") or a.get("property") or a.get("itemprop") or a.get("http-equiv") or "").lower()
            content = a.get("content", "")
            if key and content and (key in _META_KEYS or key.startswith(("article:", "og:", "dc."))):
                self.meta.setdefault(key, content.strip()[:500])
            return
        if tag == "script":
            a = {k.lower(): (v or "") for k, v in attrs}
            if "ld+json" in a.get("type", "").lower():
                self._in_jsonld = True
                self._jsonld_buf = []
                return
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            a = {k.lower(): (v or "") for k, v in attrs}
            href = a.get("href", "")
            if href.lower().startswith("mailto:"):
                self.parts.append(" " + href[7:].split("?")[0] + " ")
            elif href.lower().startswith("tel:"):
                self.parts.append(" " + href[4:] + " ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "meta":
            self.handle_starttag(tag, attrs)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            return
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld_raw.append("".join(self._jsonld_buf))
            self._jsonld_buf = []
            return
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    # -- data ------------------------------------------------------------- #
    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._skip_depth or not data:
            return
        if self._chars > MAX_TEXT_CHARS:
            return
        self.parts.append(data)
        self._chars += len(data)


def _flatten_jsonld(obj: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    """Collect dicts carrying interesting keys from arbitrarily nested JSON-LD."""
    if depth > 6 or len(out) >= 50:
        return
    if isinstance(obj, list):
        for item in obj[:50]:
            _flatten_jsonld(item, out, depth + 1)
        return
    if not isinstance(obj, dict):
        return
    record: dict[str, Any] = {}
    for key in _JSONLD_KEYS:
        if key in obj:
            val = obj[key]
            if key == "address" and isinstance(val, dict):
                pieces = [str(val.get(k, "")) for k in
                          ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
                val = ", ".join(p for p in pieces if p)
            elif key == "author" and isinstance(val, dict):
                val = val.get("name", "")
            elif isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False)[:500]
            record[key] = str(val)[:500]
    if any(k in record for k in ("telephone", "name", "address", "email")):
        out.append(record)
    for key, val in obj.items():
        if key == "@context":
            continue
        if isinstance(val, (dict, list)):
            _flatten_jsonld(val, out, depth + 1)


def strip_html(html: str) -> PageText:
    """
    Convert an HTML document into a :class:`PageText`.

    Script/style/noscript content is dropped, entities are decoded, block-level
    tags become line breaks, whitespace is collapsed.  ``<title>``, common
    ``<meta>`` fields and JSON-LD ``telephone``/``name``/``address``/``email``
    records are returned alongside the visible text.  Never raises on
    malformed markup.
    """
    if not html:
        return PageText()
    html = truncate(html, MAX_TEXT_CHARS * 4)
    parser = _VisibleTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # pragma: no cover - html.parser is very tolerant, but be safe
        pass
    text = normalise_whitespace("".join(parser.parts))
    title = normalise_whitespace(" ".join(parser.title_parts))
    jsonld: list[dict[str, Any]] = []
    for raw in parser.jsonld_raw[:10]:
        try:
            _flatten_jsonld(json.loads(raw), jsonld)
        except (ValueError, TypeError):
            continue
    return PageText(text=truncate(text), title=title[:300], meta=parser.meta, jsonld=jsonld)


# --------------------------------------------------------------------------- #
# Evidence windows & names
# --------------------------------------------------------------------------- #


def window(text: str, start: int, end: int, radius: int = 120) -> str:
    """Return the text around ``[start, end)`` extended by ``radius`` characters on each side."""
    if not text:
        return ""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = text[lo:hi]
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if lo > 0:
        snippet = "…" + snippet
    if hi < len(text):
        snippet = snippet + "…"
    return snippet


def normalise_name(name: str) -> str:
    """
    Canonical form for matching: lower-case, honorifics removed, punctuation
    stripped, whitespace collapsed.  ``"Dr. Rohan  Verma"`` -> ``"rohan verma"``.
    """
    if not name:
        return ""
    s = name.strip()
    s = _HONORIFIC_RE.sub("", s)
    s = s.replace("’", "'")
    s = _NAME_PUNCT_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    # trailing honorific-like suffixes ("ji", "sahab") add nothing for matching
    s = re.sub(r"\s+(ji|sahab|saheb|sahib)$", "", s)
    return s


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^\w']+", s.lower()) if t]


def token_set_ratio(a: str, b: str) -> float:
    """
    Fuzzy similarity of two strings on their token *sets* (order-insensitive),
    0.0..1.0.  Mirrors the classic ``fuzz.token_set_ratio`` idea using difflib:
    the shared tokens are compared against each string's remaining tokens and
    the best ratio wins, so ``"Rohan Verma"`` vs ``"Verma, Rohan K."`` is high.
    """
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    inter = " ".join(sorted(ta & tb))
    diff_a = " ".join(sorted(ta - tb))
    diff_b = " ".join(sorted(tb - ta))
    s1 = (inter + " " + diff_a).strip()
    s2 = (inter + " " + diff_b).strip()

    def ratio(x: str, y: str) -> float:
        if not x and not y:
            return 1.0
        if not x or not y:
            return 0.0
        return difflib.SequenceMatcher(None, x, y).ratio()

    candidates = [ratio(inter, s1), ratio(inter, s2), ratio(s1, s2)] if inter else [ratio(s1, s2)]
    return round(max(candidates), 4)


__all__ = [
    "MAX_TEXT_CHARS", "HONORIFICS", "NameCandidate", "PageText", "truncate", "normalise_whitespace",
    "strip_html", "window", "normalise_name", "token_set_ratio",
]
