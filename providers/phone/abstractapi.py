"""
Abstract API phone validation (https://www.abstractapi.com/api/phone-validation-api).

* Endpoint: ``GET https://phonevalidation.abstractapi.com/v1/?api_key=..&phone=<digits>``
* Free tier: 100 requests.

Abstract only accepts the key as a **query parameter**.  ``HttpClient.get_json``
builds its cache key from the URL + params, which would persist the key inside
the SQLite cache.  This provider therefore calls ``HttpClient.request`` directly
and caches the parsed payload itself under ``cache_key("abstractapi", e164)`` -
the stored ``url``/``query`` columns never contain the key either.

Carrier / location are numbering-plan allocations (MNP caveat applies).
Nothing returned here is an identity claim.
"""

from __future__ import annotations

from typing import Any, ClassVar, Optional

import httpx

from core.http import RateLimitedError
from core.models import NormalizedPhone, TelecomResult
from providers.base import PhoneIntelProvider
from storage.cache import cache_key

ABSTRACT_URL = "https://phonevalidation.abstractapi.com/v1/"
CARRIER_NOTE = (
    "Carrier as reported by provider; usually the original numbering-plan allocation. "
    "India has nationwide Mobile Number Portability, so the current operator may differ."
)


def _dig(payload: dict[str, Any], path: str) -> Optional[Any]:
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


# (result field, path in payload, confidence, note)
_MAPPING: tuple[tuple[str, str, float, str], ...] = (
    ("valid", "valid", 0.6, ""),
    ("international_format", "format.international", 0.6, ""),
    ("local_format", "format.local", 0.6, ""),
    ("country_code", "country.code", 0.6, ""),
    ("country_name", "country.name", 0.6, ""),
    ("country_prefix", "country.prefix", 0.6, ""),
    ("location", "location", 0.5, "Numbering-plan location as reported by provider; not a current location."),
    ("line_type", "type", 0.6, ""),
    ("carrier", "carrier", 0.5, CARRIER_NOTE),
)


class AbstractPhoneProvider(PhoneIntelProvider):
    name: ClassVar[str] = "abstractapi"
    requires: ClassVar[tuple[str, ...]] = ("abstract_phone_api_key",)
    paid: ClassVar[bool] = False  # 100 free requests
    docs_url: ClassVar[str] = "https://docs.abstractapi.com/phone-validation"
    rate_per_second: ClassVar[float] = 1.0

    async def lookup(self, phone: NormalizedPhone) -> list[TelecomResult]:
        if not phone.e164:
            return []
        self.calls += 1
        key = cache_key(self.name, phone.e164)
        cache = self.http.cache
        if cache is not None:
            entry = cache.get(key, max_age=self.default_cache_ttl)
            if entry is not None and isinstance(entry.payload, dict):
                self.http.cache_hits += 1
                return self._to_results(entry.payload, cached=True)

        digits = phone.e164.lstrip("+")
        params = {"api_key": self.secret("abstract_phone_api_key"), "phone": digits}
        try:
            response = await self.http.request("GET", ABSTRACT_URL, params=params, rate=self.rate_per_second)
        except RateLimitedError:
            self.errors.append(f"{self.name}: rate limited")
            self.log.warning("abstractapi rate limited", provider=self.name)
            return []
        except (httpx.HTTPError, OSError) as exc:
            # never str(exc): an httpx error message could include the request URL (and key)
            self.errors.append(f"{self.name}: {type(exc).__name__}")
            self.log.warning("abstractapi request error", provider=self.name, error=type(exc).__name__)
            return []
        status = response.status_code
        if status >= 400:
            reason = {401: "invalid API key", 402: "quota exhausted", 422: "invalid request",
                      429: "rate limited"}.get(status, "HTTP error")
            self.errors.append(f"{self.name}: HTTP {status} ({reason})")
            self.log.warning("abstractapi request failed", provider=self.name, status=status, reason=reason)
            return []
        try:
            payload = response.json()
        except ValueError:
            self.errors.append(f"{self.name}: invalid JSON response")
            self.log.warning("abstractapi invalid JSON", provider=self.name, status=status)
            return []
        if not isinstance(payload, dict):
            self.errors.append(f"{self.name}: unexpected payload type")
            return []
        if "error" in payload:
            err = payload["error"]
            msg = err.get("message", "unknown") if isinstance(err, dict) else str(err)
            self.errors.append(f"{self.name}: API error: {msg}")
            return []
        if cache is not None:
            # url/query columns deliberately exclude the key-bearing query string
            cache.set(key, payload, url=ABSTRACT_URL, query=repr({"phone": digits}), status=status)
        return self._to_results(payload, cached=False)

    def _to_results(self, payload: dict[str, Any], cached: bool) -> list[TelecomResult]:
        raw: dict[str, Any] = {
            "valid": payload.get("valid"),
            "format": payload.get("format"),
            "country": payload.get("country"),
            "location": payload.get("location"),
            "type": payload.get("type"),
            "carrier": payload.get("carrier"),
            "from_cache": cached,
        }
        results: list[TelecomResult] = []
        for field, path, confidence, note in _MAPPING:
            value = _dig(payload, path)
            if value is None or value == "":
                continue
            results.append(TelecomResult(provider=self.name, field=field, value=str(value),
                                         confidence=confidence, note=note, raw=raw))
        return results
