"""
Social-profile URL and handle extraction.

Recognises profile URLs on the major platforms (LinkedIn, Facebook, Instagram,
X/Twitter, YouTube, GitHub, Reddit, Telegram, Medium, Quora, Pinterest,
Threads, TikTok ...), the synthetic ``<platform>.example`` hosts used by the
offline fixture, ``@handle`` mentions in text (platform ``unknown``) and
``Instagram: rohan.v`` / ``Twitter: @x`` label patterns.

Reserved paths (``/login``, ``/share``, ``/search``, ``/hashtag/..``, ``/p/..``
...) are never reported as profiles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from extractors.text_utils import truncate
from scoring.source_quality import SOCIAL_HOSTS, demo_host_alias

_URL_RE = re.compile(
    r"(?<![\w@/])(?:https?://)?(?:www\.|m\.|mobile\.)?"
    r"(?P<host>[a-z0-9][a-z0-9.-]*\.(?:com|net|me|app|in|example|tv|org|io))"
    r"(?P<path>/[^\s\"'<>()\[\]{}]*)",
    re.IGNORECASE,
)
_HANDLE_RE = re.compile(r"(?<![\w@./:])@(?P<user>[A-Za-z][A-Za-z0-9_.]{2,29})(?![\w@])")
_LABEL_RE = re.compile(
    r"\b(?P<platform>instagram|insta|ig|twitter|x|facebook|fb|linkedin|github|telegram|youtube|snapchat|"
    r"threads|reddit|medium|quora|pinterest|tiktok|koo|behance|dribbble|gitlab)"
    r"(?:\s*(?:id|handle|profile|username|user|page|account))?(?:\s*:\s*|\s+[-–]\s+)@?"
    r"(?P<user>[A-Za-z0-9][A-Za-z0-9._-]{1,63})(?![\w@])",
    re.IGNORECASE,
)
_USERNAME_OK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

_PLATFORM_ALIASES = {
    "insta": "instagram", "ig": "instagram", "twitter": "x", "fb": "facebook", "telegram": "telegram",
}
_DEMO_LABEL_PLATFORMS = {"t": "telegram", "twitter": "x"}

# paths that are never a profile, on any platform
_RESERVED_GLOBAL = {
    "login", "logout", "signin", "signup", "register", "share", "sharer", "search", "hashtag", "explore",
    "intent", "home", "watch", "p", "reel", "reels", "groups", "group", "pages", "page", "help", "about",
    "privacy", "terms", "i", "settings", "feed", "jobs", "job", "posts", "post", "pulse", "events", "event",
    "stories", "story", "tv", "accounts", "account", "legal", "policy", "policies", "static", "dialog",
    "plugins", "ads", "business", "developers", "developer", "api", "docs", "blog", "news", "support",
    "download", "downloads", "app", "apps", "mobile", "tag", "tags", "topic", "topics", "trending",
    "notifications", "messages", "inbox", "compose", "public", "embed", "oembed", "status", "video",
    "videos", "photo", "photos", "photo.php", "marketplace", "shop", "premium", "features", "pricing",
    "enterprise", "security", "site", "sitemap", "robots.txt", "favicon.ico", "wp-content", "wp-admin",
    "directory", "dir", "learning", "school", "sales", "talent", "advertising", "campaign", "checkpoint",
    "uas", "authwall", "redir", "safety", "signup.php", "recover", "friends", "people", "profile.php",
    "results", "playlist", "shorts", "hashtags", "join", "new", "orgs", "org", "sponsors", "collections",
    "customer-stories", "readme", "issues", "pulls", "team", "trust", "questions", "question", "answer",
    "unanswered", "r", "comments", "subreddits", "wiki", "message", "submit", "top", "hot", "rising",
    "joinchat", "addstickers", "proxy", "socks", "s", "c", "channel", "user", "in", "company", "pub",
    "pin", "ideas", "today", "categories", "category", "web", "www", "index", "index.html", "index.php",
    "contact", "contact-us", "contactus", "services", "products", "about-us", "aboutus", "career",
    "careers", "faq", "faqs", "gallery", "portfolio", "team", "cdn-cgi",
}


@dataclass(frozen=True)
class ProfileMatch:
    """A social profile URL or handle located in text."""

    platform: str
    username: str
    profile_url: str
    start: int
    end: int
    kind: str = "profile"  # profile | page | company | channel | handle
    confidence: float = 0.8

    def as_dict(self) -> dict[str, object]:
        return {
            "platform": self.platform, "username": self.username, "profile_url": self.profile_url,
            "kind": self.kind, "confidence": self.confidence, "start": self.start, "end": self.end,
        }


def platform_of_host(host: str) -> tuple[str, str]:
    """
    ``www.linkedin.example`` -> ("linkedin", "linkedin.com"); ``x.com`` -> ("x", "x.com").
    Returns ("", host) for hosts that are not a known social platform.
    """
    host = host.lower()
    if host.endswith(".example"):
        base = host[: -len(".example")]
        if base.startswith(("www.", "m.")):
            base = base.split(".", 1)[1]
        label = base.split(".")[-1]
        platform = _DEMO_LABEL_PLATFORMS.get(label, label)
        alias_host, _ = demo_host_alias(host)
        return platform, alias_host
    for dom, platform in SOCIAL_HOSTS.items():
        if host == dom or host.endswith("." + dom):
            return platform, host
    return "", host


def _clean_segment(seg: str) -> str:
    seg = unquote(seg).strip()
    seg = seg.rstrip(".,;:!?)]}'\"")
    return seg


def _valid_username(u: str) -> bool:
    if not u or not _USERNAME_OK_RE.match(u):
        return False
    if u.lower() in _RESERVED_GLOBAL:
        return False
    if "." in u and u.lower().rsplit(".", 1)[-1] in ("html", "php", "htm", "aspx", "jsp", "asp", "xml", "json"):
        return False
    return True


def _profile_from_path(platform: str, host: str, path: str) -> tuple[str, str, str] | None:
    """
    Return ``(username, kind, canonical_profile_url)`` for a platform path, or None.
    """
    segs = [_clean_segment(s) for s in path.split("?")[0].split("#")[0].split("/") if s]
    if not segs:
        return None
    first = segs[0]
    base = f"https://{host}"

    if platform == "linkedin":
        if len(segs) >= 2 and first.lower() == "in" and _valid_username(segs[1]):
            return segs[1], "profile", f"{base}/in/{segs[1]}"
        if len(segs) >= 2 and first.lower() == "company" and _valid_username(segs[1]):
            return segs[1], "company", f"{base}/company/{segs[1]}"
        if len(segs) >= 2 and first.lower() == "pub" and _valid_username(segs[1]):
            return segs[1], "profile", f"{base}/pub/{segs[1]}"
        return None
    if platform == "facebook":
        if first.lower() == "profile.php":
            m = re.search(r"[?&]id=(\d{5,20})", path)
            return (m.group(1), "profile", f"{base}/profile.php?id={m.group(1)}") if m else None
        if first.lower() == "people" and len(segs) >= 2 and _valid_username(segs[1]):
            return segs[1], "profile", f"{base}/people/{segs[1]}" + (f"/{segs[2]}" if len(segs) > 2 else "")
        if first.lower() in ("pg", "pages") and len(segs) >= 2 and _valid_username(segs[1]):
            return segs[1], "page", f"{base}/{segs[1]}"
        if _valid_username(first):
            return first, "page", f"{base}/{first}"
        return None
    if platform == "instagram" or platform == "pinterest" or platform == "tiktok":
        first_u = first.lstrip("@")
        if _valid_username(first_u) and first.lower() not in ("p", "reel", "reels", "explore", "accounts", "stories", "pin", "ideas"):
            return first_u, "profile", f"{base}/{first_u}"
        return None
    if platform == "x":
        if _valid_username(first) and first.lower() not in ("i", "intent", "search", "hashtag", "home", "share", "explore", "settings", "login"):
            return first, "profile", f"{base}/{first}"
        return None
    if platform == "youtube":
        if first.startswith("@") and _valid_username(first[1:]):
            return first[1:], "channel", f"{base}/{first}"
        if first.lower() in ("c", "channel", "user") and len(segs) >= 2 and _valid_username(segs[1]):
            return segs[1], "channel", f"{base}/{first.lower()}/{segs[1]}"
        return None
    if platform in ("github", "gitlab"):
        if _valid_username(first) and first.lower() not in ("orgs", "features", "topics", "explore", "marketplace", "sponsors", "trending", "collections", "events", "apps", "site", "security", "enterprise", "team", "customer-stories", "readme", "issues", "pulls", "notifications", "new", "login", "join", "settings", "about", "pricing", "search"):
            return first, "profile", f"{base}/{first}"
        return None
    if platform == "reddit":
        if first.lower() in ("user", "u") and len(segs) >= 2 and _valid_username(segs[1]):
            return segs[1], "profile", f"{base}/user/{segs[1]}"
        return None
    if platform == "telegram":
        if _valid_username(first) and not first.startswith("+") and first.lower() not in ("joinchat", "share", "addstickers", "s", "proxy", "socks"):
            return first, "channel", f"https://t.me/{first}"
        return None
    if platform in ("medium", "threads"):
        if first.startswith("@") and _valid_username(first[1:]):
            return first[1:], "profile", f"{base}/{first}"
        return None
    if platform == "quora":
        if first.lower() == "profile" and len(segs) >= 2 and _valid_username(segs[1]):
            return segs[1], "profile", f"{base}/profile/{segs[1]}"
        return None
    if platform in ("behance", "dribbble", "koo", "aboutme", "stackoverflow"):
        if platform == "stackoverflow":
            if first.lower() == "users" and len(segs) >= 3 and _valid_username(segs[2]):
                return segs[2], "profile", f"{base}/users/{segs[1]}/{segs[2]}"
            return None
        if _valid_username(first):
            return first, "profile", f"{base}/{first}"
        return None
    return None


def parse_profile_url(url: str) -> ProfileMatch | None:
    """Parse a single URL into a :class:`ProfileMatch` (start/end = 0) or None."""
    if not url:
        return None
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    try:
        parts = urlsplit(u)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host.startswith(("www.", "m.", "mobile.")):
        host = host.split(".", 1)[1]
    platform, alias_host = platform_of_host(host)
    if not platform:
        # user.medium.com style subdomains
        if host.endswith(".medium.com") and host.count(".") == 2:
            sub = host.split(".")[0]
            if _valid_username(sub):
                return ProfileMatch("medium", sub, f"https://{host}", 0, 0, "profile", 0.7)
        return None
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    parsed = _profile_from_path(platform, alias_host if alias_host else host, path)
    if not parsed:
        return None
    username, kind, profile_url = parsed
    if host.endswith(".example"):
        # keep the fixture host so the URL remains resolvable offline
        profile_url = profile_url.replace(f"https://{alias_host}", f"https://{host}", 1)
    return ProfileMatch(platform, username, profile_url, 0, 0, kind, 0.85)


def _normalise_platform(name: str) -> str:
    n = name.lower()
    return _PLATFORM_ALIASES.get(n, n)


def _label_profile_url(platform: str, user: str) -> str:
    table = {
        "instagram": f"https://www.instagram.com/{user}", "x": f"https://x.com/{user}",
        "facebook": f"https://www.facebook.com/{user}", "linkedin": f"https://www.linkedin.com/in/{user}",
        "github": f"https://github.com/{user}", "telegram": f"https://t.me/{user}",
        "youtube": f"https://www.youtube.com/@{user}", "threads": f"https://www.threads.net/@{user}",
        "reddit": f"https://www.reddit.com/user/{user}", "medium": f"https://medium.com/@{user}",
        "quora": f"https://www.quora.com/profile/{user}", "pinterest": f"https://www.pinterest.com/{user}",
        "tiktok": f"https://www.tiktok.com/@{user}", "snapchat": f"https://www.snapchat.com/add/{user}",
        "koo": f"https://www.kooapp.com/profile/{user}", "behance": f"https://www.behance.net/{user}",
        "dribbble": f"https://dribbble.com/{user}", "gitlab": f"https://gitlab.com/{user}",
    }
    return table.get(platform, "")


_LABEL_JUNK_VALUES = {"page", "profile", "link", "yes", "no", "available", "n/a", "na", "none", "here",
                      "click", "follow", "us", "me", "id", "handle", "com", "www", "http", "https", "the"}


def extract_profiles(text: str, url: str = "") -> list[ProfileMatch]:
    """
    Find social-profile URLs, ``Platform: handle`` labels and bare ``@handles``.

    ``url`` (the page's own URL) is parsed too: a LinkedIn/GitHub/... profile
    page is itself a profile match (start = end = -1).  Results are de-duplicated
    by (platform, username) keeping the highest-confidence occurrence.
    """
    text = truncate(text)
    found: dict[tuple[str, str], ProfileMatch] = {}

    def _add(pm: ProfileMatch) -> None:
        key = (pm.platform, pm.username.lower())
        cur = found.get(key)
        if cur is None or pm.confidence > cur.confidence:
            found[key] = pm

    if url:
        own = parse_profile_url(url)
        if own:
            _add(ProfileMatch(own.platform, own.username, own.profile_url, -1, -1, own.kind, 0.9))

    if not text:
        return sorted(found.values(), key=lambda p: p.start)

    for m in _URL_RE.finditer(text):
        raw = m.group(0).rstrip(".,;:!?'\"")
        pm = parse_profile_url(raw)
        if pm:
            _add(ProfileMatch(pm.platform, pm.username, pm.profile_url, m.start(), m.start() + len(raw), pm.kind, pm.confidence))
        if len(found) > 200:
            break

    for m in _LABEL_RE.finditer(text):
        user = m.group("user").rstrip(".-_")
        if user.lower() in _LABEL_JUNK_VALUES or not _valid_username(user):
            continue
        platform = _normalise_platform(m.group("platform"))
        # skip if what follows is really a URL (handled above)
        if text[m.end():m.end() + 1] in ("/", ":"):
            continue
        if "." in user and user.lower().rsplit(".", 1)[-1] in ("com", "in", "net", "org", "example", "me"):
            continue
        _add(ProfileMatch(platform, user, _label_profile_url(platform, user), m.start(), m.end(), "handle", 0.6))

    for m in _HANDLE_RE.finditer(text):
        user = m.group("user").rstrip(".")
        if user.lower() in _LABEL_JUNK_VALUES or not _valid_username(user) or len(user) < 3:
            continue
        if "." in user and user.lower().rsplit(".", 1)[-1] in ("com", "in", "net", "org", "example", "me", "co"):
            continue
        key_exists = any(k[1] == user.lower() for k in found)
        if key_exists:
            continue  # already attributed to a platform
        _add(ProfileMatch("unknown", user, "", m.start(), m.end(), "handle", 0.4))

    return sorted(found.values(), key=lambda p: (p.start, p.platform))


__all__ = ["ProfileMatch", "extract_profiles", "parse_profile_url", "platform_of_host"]
