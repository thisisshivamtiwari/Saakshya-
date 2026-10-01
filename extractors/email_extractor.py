"""
E-mail address extraction (plain and lightly obfuscated forms).

Handles ``name@domain.tld``, ``name [at] domain [dot] com``, ``name (at) domain.com``
and ``name {at} domain {dot} in``.  Results are lower-cased and de-duplicated
(first occurrence wins).  Obvious junk - image filenames, ``noreply@``,
placeholder addresses such as ``your@email.com``, error-tracker addresses - is
dropped.  ``example.com`` / ``example.in`` addresses are *kept* because the
offline fixture uses them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from extractors.text_utils import truncate

_PLAIN_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9])?)@([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,24})(?![\w-])"
)
# "name [at] domain [dot] com" / "name (at) domain.com" / "name {at} domain {dot} in"
_OBF_AT = r"(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|<\s*at\s*>|\s+at\s+)"
_OBF_DOT = r"(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|<\s*dot\s*>|\s+dot\s+|\.)"
_OBFUSCATED_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63})\s*" + _OBF_AT +
    r"\s*([A-Za-z0-9][A-Za-z0-9-]{0,62})((?:\s*" + _OBF_DOT + r"\s*[A-Za-z0-9][A-Za-z0-9-]{0,62}){1,4})(?![\w-])",
    re.IGNORECASE,
)
_DOT_TOKEN_RE = re.compile(r"\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|<\s*dot\s*>|\s+dot\s+|\.", re.IGNORECASE)
_BRACKET_DOT_RE = re.compile(r"\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|<\s*dot\s*>|\s+dot\s+", re.IGNORECASE)

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".css", ".js")
_JUNK_LOCAL = {
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "do_not_reply", "example",
    "your", "youremail", "your.email", "email", "e-mail", "name", "user", "username", "someone",
    "test", "mail", "yourname", "firstname", "lastname", "first.last", "john.doe", "jane.doe",
    "abc", "xyz", "xxx", "yourmail", "sample", "demo", "null", "undefined",
}
_JUNK_DOMAIN_PARTS = ("sentry", "wixpress", "yourdomain", "domain.com", "email.com", "yourcompany",
                      "mailinator", "localhost", "your-domain", "company.com", "website.com", "mysite",
                      "2x.png", "w3.org", "schema.org")
_JUNK_FULL = {"email@domain.com", "your@email.com", "name@email.com", "user@domain.com",
              "email@example.com", "name@example.com", "you@example.com"}
_MAX_MATCHES = 300


@dataclass(frozen=True)
class EmailMatch:
    """One e-mail address located in text (lower-cased)."""

    email: str
    start: int
    end: int


def domain_of(email: str) -> str:
    """``rohan@Example.IN`` -> ``example.in`` (empty string if not an address)."""
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[1].strip().lower().rstrip(".")


def is_junk_email(email: str) -> bool:
    """True for placeholders, no-reply senders, asset filenames and tracker addresses."""
    e = email.lower().strip()
    if e in _JUNK_FULL:
        return True
    local, _, domain = e.partition("@")
    if not local or not domain or "." not in domain:
        return True
    if e.endswith(_IMAGE_EXT) or domain.endswith(_IMAGE_EXT):
        return True
    if local in _JUNK_LOCAL or local.startswith(("noreply", "no-reply", "donotreply", "do-not-reply", "example@")):
        return True
    if any(part in domain for part in _JUNK_DOMAIN_PARTS):
        return True
    if local.startswith("your@") or e.startswith("your@") or e.startswith("example@"):
        return True
    tld = domain.rsplit(".", 1)[-1]
    if tld.isdigit() or len(tld) < 2:
        return True
    if len(local) > 64 or len(domain) > 253:
        return True
    return False


def _clean_obfuscated_domain(head: str, tail: str) -> str:
    parts = [head] + [p for p in _DOT_TOKEN_RE.split(tail) if p and p.strip()]
    return ".".join(p.strip() for p in parts if p.strip())


def extract_emails(text: str) -> list[EmailMatch]:
    """Return unique, lower-cased e-mail addresses in order of first appearance."""
    text = truncate(text)
    if not text or "@" not in text and " at " not in text.lower() and "(at)" not in text.lower():
        return []
    found: dict[str, EmailMatch] = {}
    taken: list[tuple[int, int]] = []

    for m in _PLAIN_RE.finditer(text):
        email = f"{m.group(1)}@{m.group(2)}".lower().rstrip(".")
        if is_junk_email(email):
            continue
        taken.append((m.start(), m.end()))
        if email not in found:
            found[email] = EmailMatch(email=email, start=m.start(), end=m.end())
        if len(found) >= _MAX_MATCHES:
            break

    for m in _OBFUSCATED_RE.finditer(text):
        # plain " at " needs at least one bracketed/spelled "dot" to avoid "meet at cafe.com" noise
        at_token = text[m.end(1):m.start(2)]
        if not any(ch in at_token for ch in "[({<") and not _BRACKET_DOT_RE.search(m.group(3)):
            continue
        if any(s <= m.start() < e or s < m.end() <= e for s, e in taken):
            continue
        domain = _clean_obfuscated_domain(m.group(2), m.group(3))
        email = f"{m.group(1)}@{domain}".lower()
        if not re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,24}", email) or is_junk_email(email):
            continue
        if email not in found:
            found[email] = EmailMatch(email=email, start=m.start(), end=m.end())
        if len(found) >= _MAX_MATCHES:
            break

    return sorted(found.values(), key=lambda e: e.start)


__all__ = ["EmailMatch", "extract_emails", "domain_of", "is_junk_email"]
