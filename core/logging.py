"""
Structured logging with automatic masking of phone numbers, e-mail addresses
and API keys (spec section 38).

Usage::

    from core.logging import get_logger
    log = get_logger(__name__)
    log.info("Search provider queried", provider="brave", results=17)

Normal logs mask Indian numbers as ``+91******3210``.  Secrets from settings
are never logged (they are SecretStr) and, as a belt-and-braces measure, any
string that *looks* like a bearer/API key is redacted here too.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

_PHONE_RE = re.compile(r"(?<!\d)(\+?91[\s-]?)?([6-9]\d{4})[\s-]?(\d{5})(?!\d)")
_INTL_RE = re.compile(r"\+\d{1,3}[\s-]?\d{6,12}")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|authorization|x-subscription-token|auth_token)\s*[=:]\s*([A-Za-z0-9\-_.]{8,})"
)
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9]{32,}\b")


def mask_text(text: str) -> str:
    """Mask phone numbers, e-mails and secrets inside free text."""
    if not text:
        return text

    def _phone(m: re.Match[str]) -> str:
        prefix = "+91" if m.group(1) else ""
        return f"{prefix}******{m.group(3)[-4:]}"

    text = _PHONE_RE.sub(_phone, text)
    text = _INTL_RE.sub(lambda m: m.group(0)[:3] + "******" + m.group(0)[-3:], text)
    text = _EMAIL_RE.sub(lambda m: m.group(1)[:2] + "***@" + m.group(2), text)
    text = _KEY_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = _LONG_TOKEN_RE.sub("<redacted-token>", text)
    return text


class MaskingFormatter(logging.Formatter):
    def __init__(self, as_json: bool = False) -> None:
        super().__init__()
        self.as_json = as_json

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        msg = record.getMessage()
        extra = getattr(record, "extra_fields", None) or {}
        masked_extra = {k: (mask_text(v) if isinstance(v, str) else v) for k, v in extra.items()}
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="seconds")
        if self.as_json:
            payload: dict[str, Any] = {
                "ts": ts,
                "level": record.levelname,
                "logger": record.name,
                "message": mask_text(msg),
                **masked_extra,
            }
            if record.exc_info:
                payload["exc"] = mask_text(self.formatException(record.exc_info))
            return json.dumps(payload, ensure_ascii=False, default=str)
        kv = " ".join(f"{k}={v}" for k, v in masked_extra.items())
        line = f"[{record.levelname}] {ts} {record.name}: {mask_text(msg)}"
        if kv:
            line += f"  {kv}"
        if record.exc_info:
            line += "\n" + mask_text(self.formatException(record.exc_info))
        return line


class StructuredLogger(logging.LoggerAdapter):
    """Logger adapter that accepts keyword fields: ``log.info("msg", provider="brave")``."""

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        std = {k: kwargs.pop(k) for k in ("exc_info", "stack_info", "stacklevel") if k in kwargs}
        extra_fields = {k: v for k, v in kwargs.items()}
        kwargs.clear()
        kwargs.update(std)
        kwargs["extra"] = {"extra_fields": extra_fields}
        return msg, kwargs


_CONFIGURED = False


def configure_logging(level: str = "INFO", as_json: bool = False, stream: Any = None) -> None:
    global _CONFIGURED
    root = logging.getLogger("osint")
    root.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(MaskingFormatter(as_json=as_json))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False
    # keep third-party noise down
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> StructuredLogger:
    if not _CONFIGURED:
        configure_logging()
    base = logging.getLogger(f"osint.{name}")
    return StructuredLogger(base, {})
