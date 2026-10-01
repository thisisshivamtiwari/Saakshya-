"""URL canonicalisation and domain helpers (used for dedup and source quality)."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

# Offline extractor: uses the suffix list bundled with the package, never the network.
_extract = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src",
    "trk", "trkInfo", "originalSubdomain", "_ga", "yclid", "si", "feature", "srsltid",
}
_DOC_EXT_RE = re.compile(r"\.(pdf|xlsx?|docx?|pptx?|csv|rtf|odt|ods|txt)(?:$|[?#])", re.IGNORECASE)


def canonical_url(url: str) -> str:
    """Lower-case scheme/host, drop fragments, tracking params, default ports, trailing slashes."""
    if not url:
        return ""
    url = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2 and not host.startswith("m.me"):
        host = host[2:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query_items = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
                   if k not in _TRACKING_PARAMS and not k.lower().startswith("utm_")]
    query = urlencode(sorted(query_items))
    if scheme == "http":
        scheme = "https"  # treat http/https duplicates as one source
    return urlunsplit((scheme, netloc, path, query, ""))


def registrable_domain(url: str) -> str:
    """``https://www.sub.example.co.in/x`` -> ``example.co.in``."""
    try:
        ext = _extract(url)
    except Exception:  # pragma: no cover
        return ""
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return (ext.domain or "").lower()


def host_of(url: str) -> str:
    try:
        return (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
    except ValueError:
        return ""


def file_type_from_url(url: str) -> str:
    m = _DOC_EXT_RE.search(url or "")
    return m.group(1).lower() if m else ""


def is_probably_document(url: str) -> bool:
    return bool(file_type_from_url(url))


def normalize_website(url_or_domain: str) -> str:
    """For WEBSITE findings: return a bare registrable-ish host without scheme/path."""
    h = host_of(url_or_domain) if "://" in url_or_domain or "/" in url_or_domain else url_or_domain.lower()
    h = h.strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h
