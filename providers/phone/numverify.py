"""
NumVerify phone validation (apilayer marketplace edition).

* Endpoint: ``GET https://api.apilayer.com/number_verification/validate?number=<digits>``
  with header ``apikey: <key>``.  The key travels in a header only, so it is
  never part of the response-cache key.
* Free tier: 100 requests / month; paid tiers exist (``paid = False`` because a
  free tier is available).
* A legacy endpoint ``https://apilayer.net/api/validate?access_key=..&number=..``
  also exists for older numverify.com accounts.  It puts the key in the query
  string (which would leak into cache keys) and is therefore *not* implemented
  here; marketplace keys are the supported path.

Carrier / location are numbering-plan allocations and are labelled with an
MNP caveat.  Nothing returned here is an identity claim.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from core.http import RateLimitedError
from core.models import NormalizedPhone, TelecomResult
from providers.base import PhoneIntelProvider

NUMVERIFY_URL = "https://api.apilayer.com/number_verification/validate"
CARRIER_NOTE = (
    "Carrier as reported by provider; usually the original numbering-plan allocation. "
    "India has nationwide Mobile Number Portability, so the current operator may differ."
)
LOCATION_NOTE = "Numbering-plan location as reported by provider; not a current location."
_FIELDS: tuple[str, ...] = (
    "valid", "number", "local_format", "international_format", "country_prefix",
    "country_code", "country_name", "location", "carrier", "line_type",
)


class NumVerifyProvider(PhoneIntelProvider):
    name: ClassVar[str] = "numverify"
    requires: ClassVar[tuple[str, ...]] = ("numverify_api_key",)
    paid: ClassVar[bool] = False  # 100 free requests / month; paid tiers available
    docs_url: ClassVar[str] = "https://apilayer.com/marketplace/number_verification-api"
    rate_per_second: ClassVar[float] = 1.0

    async def lookup(self, phone: NormalizedPhone) -> list[TelecomResult]:
        if not phone.e164:
            return []
        self.calls += 1
        digits = phone.e164.lstrip("+")  # digits including the 91 country code
        headers = {"apikey": self.secret("numverify_api_key")}
        try:
            payload, cached = await self.http.get_json(
                NUMVERIFY_URL, params={"number": digits}, headers=headers, namespace=self.name,
                cache_ttl=self.default_cache_ttl, rate=self.rate_per_second,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason = {401: "invalid API key", 402: "quota exhausted",
                      429: "rate limited"}.get(status, "HTTP error")
            self.errors.append(f"{self.name}: HTTP {status} ({reason})")
            self.log.warning("numverify request failed", provider=self.name, status=status, reason=reason)
            return []
        except RateLimitedError:
            self.errors.append(f"{self.name}: rate limited")
            self.log.warning("numverify rate limited", provider=self.name)
            return []
        except (httpx.HTTPError, OSError, ValueError) as exc:
            self.errors.append(f"{self.name}: {type(exc).__name__}")
            self.log.warning("numverify request error", provider=self.name, error=type(exc).__name__)
            return []
        if not isinstance(payload, dict):
            self.errors.append(f"{self.name}: unexpected payload type")
            return []
        if payload.get("success") is False or "error" in payload:
            err = payload.get("error") or {}
            info = err.get("info", err.get("type", "unknown")) if isinstance(err, dict) else str(err)
            self.errors.append(f"{self.name}: API error: {info}")
            self.log.warning("numverify API error", provider=self.name, message=str(info))
            return []
        return self._to_results(payload, cached)

    def _to_results(self, payload: dict[str, Any], cached: bool) -> list[TelecomResult]:
        raw = {k: payload.get(k) for k in _FIELDS if k in payload}
        raw["from_cache"] = cached
        results: list[TelecomResult] = []
        for field in _FIELDS:
            value = payload.get(field)
            if value is None or value == "":
                continue
            note = ""
            if field == "carrier":
                note = CARRIER_NOTE
            elif field == "location":
                note = LOCATION_NOTE
            results.append(TelecomResult(provider=self.name, field=field, value=str(value),
                                         confidence=0.6, note=note, raw=raw))
        return results
