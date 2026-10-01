"""
Security / privacy boundary tests (ARCHITECTURE §11).

The codebase must never contain login, OTP, password-reset, account-recovery, breach-lookup, contact-sync
or CAPTCHA-bypass logic, and forbidden Twilio fields must stay guarded.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ["config", "core", "providers", "collectors", "extractors", "correlation", "scoring", "reports",
               "storage", "ui", "main.py"]

FORBIDDEN_ENDPOINT_PATTERNS = [
    r"haveibeenpwned\.com/api", r"api\.dehashed", r"intelx\.io", r"leakcheck", r"snusbase", r"leak-lookup",
    r"accounts\.snapchat\.com/accounts/validate_phone_number", r"i\.instagram\.com/api/v1/users/lookup",
    r"amazon\.com/ap/signin", r"password_reset", r"forgot[_-]?password", r"/recover", r"sim_swap",
    r"identity_match", r"reassigned_number", r"caller_name", r"truecaller", r"2captcha", r"anticaptcha",
    r"capsolver", r"cloudflare_bypass", r"curl_cffi", r"tls_fingerprint",
]
# these strings may legitimately appear only in prose that *forbids* them
ALLOWED_CONTEXT = re.compile(r"(?i)(never|forbid|forbidden|excluded?|not|no |do not|must not|out of bounds|guard|"
                             r"prohibit|boundary|drop|filter|skip|blocked|removed|disallow)")
# Files that are *allowed* to name a forbidden thing because they exist to block/rate it:
#  - the Twilio provider's FORBIDDEN_FIELDS guard (covered by test_twilio_forbidden_fields_guarded)
#  - the source-quality table that rates truecaller.com pages as E (unreliable); no API is called
EXEMPT = {
    ("providers/phone/twilio.py", "caller_name"), ("providers/phone/twilio.py", "sim_swap"),
    ("providers/phone/twilio.py", "identity_match"), ("providers/phone/twilio.py", "reassigned_number"),
    ("scoring/source_quality.py", "truecaller"),
}


def _source_files():
    for d in SOURCE_DIRS:
        p = ROOT / d
        if p.is_file():
            yield p
        else:
            yield from p.rglob("*.py")


@pytest.mark.parametrize("pattern", FORBIDDEN_ENDPOINT_PATTERNS)
def test_no_forbidden_endpoints_or_techniques(pattern):
    rx = re.compile(pattern, re.IGNORECASE)
    offenders = []
    for path in _source_files():
        rel = str(path.relative_to(ROOT))
        if (rel, pattern) in EXEMPT:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if rx.search(line) and not ALLOWED_CONTEXT.search(line):
                # a line that merely names the thing inside a FORBIDDEN/blocked set is fine
                if "FORBIDDEN" in line or "forbidden" in line.lower():
                    continue
                offenders.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()[:100]}")
    assert not offenders, f"forbidden technique reference for /{pattern}/:\n" + "\n".join(offenders)


def test_no_scraping_search_engine_html():
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in _source_files())
    for host in ("html.duckduckgo.com", "www.google.com/search", "www.bing.com/search", "search.brave.com/search"):
        assert host not in text, f"HTML scraping endpoint {host} must not be used"


def test_twilio_forbidden_fields_guarded():
    from providers.phone.twilio import FORBIDDEN_FIELDS, validate_fields

    for f in ("caller_name", "sim_swap", "identity_match", "reassigned_number"):
        assert f in FORBIDDEN_FIELDS
        with pytest.raises(ValueError):
            validate_fields((f,))


def test_secrets_never_logged(capsys):
    from core.logging import configure_logging, get_logger
    import io

    buf = io.StringIO()
    configure_logging("DEBUG", stream=buf)
    log = get_logger("boundary")
    log.info("token=abcdefghijklmnopqrstuvwxyz123456 for +919876543210 rohan@example.in")
    out = buf.getvalue()
    assert "abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "+919876543210" not in out and "+91******3210" in out
    assert "rohan@example.in" not in out


def test_env_example_has_no_values():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if key.strip().isupper() and not key.startswith("OSINT_"):
                assert value.strip() == "", f"{key} must be empty in .env.example"


def test_gitignore_excludes_secrets_and_data():
    gi = (ROOT / ".gitignore").read_text()
    for entry in (".env", "data/", "output/", "*.sqlite"):
        assert entry in gi
