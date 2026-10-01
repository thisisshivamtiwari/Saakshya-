"""
Veriphone phone validation (https://veriphone.io/docs/v3).

* Endpoint: ``GET https://api.veriphone.io/v3/verify``
* Auth: ``Authorization: Bearer <key>`` (header - never a query parameter, so
  the key never reaches the response cache).
* Free tier: 1,000 credits / month.  ``mode=static`` (the default) costs one
  credit; ``mode=current`` costs **ten** and is therefore never sent unless a
  subclass deliberately sets ``allow_current_mode = True``.
* ``402 Payment Required`` means the account is out of credits: the provider
  records the error and returns ``[]``.

The carrier reported by Veriphone is the numbering-plan allocation (it may be
the original operator rather than the current one because of Indian MNP).
Nothing returned here is an identity claim.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from core.http import RateLimitedError
from core.models import NormalizedPhone, TelecomResult
from providers.base import PhoneIntelProvider

VERIPHONE_URL = "https://api.veriphone.io/v3/verify"
CARRIER_NOTE = "carrier as reported by provider; may be original allocation"
_FIELDS: tuple[str, ...] = (
    "status", "phone_valid", "phone_type", "carrier", "phone_region", "country",
    "country_code", "country_prefix", "international_number", "local_number", "e164", "timezone",
)


class VeriphoneProvider(PhoneIntelProvider):
    name: ClassVar[str] = "veriphone"
    requires: ClassVar[tuple[str, ...]] = ("veriphone_api_key",)
    paid: ClassVar[bool] = False  # free tier: 1,000 credits / month
    docs_url: ClassVar[str] = "https://veriphone.io/docs/v3"
    rate_per_second: ClassVar[float] = 2.0
    allow_current_mode: ClassVar[bool] = False  # mode=current costs 10 credits - keep off

    async def lookup(self, phone: NormalizedPhone) -> list[TelecomResult]:
        if not phone.e164:
            return []
        self.calls += 1
        params: dict[str, str] = {"phone": phone.e164, "default_country": "IN"}
        if self.allow_current_mode:
            params["mode"] = "current"
        headers = {"Authorization": f"Bearer {self.secret('veriphone_api_key')}"}
        try:
            payload, cached = await self.http.get_json(
                VERIPHONE_URL, params=params, headers=headers, namespace=self.name,
                cache_ttl=self.default_cache_ttl, rate=self.rate_per_second,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason = {401: "invalid API key", 402: "out of credits",
                      429: "rate limited"}.get(status, "HTTP error")
            self.errors.append(f"{self.name}: HTTP {status} ({reason})")
            self.log.warning("veriphone request failed", provider=self.name, status=status, reason=reason)
            return []
        except RateLimitedError:
            self.errors.append(f"{self.name}: rate limited")
            self.log.warning("veriphone rate limited", provider=self.name)
            return []
        except (httpx.HTTPError, OSError, ValueError) as exc:
            self.errors.append(f"{self.name}: {type(exc).__name__}")
            self.log.warning("veriphone request error", provider=self.name, error=type(exc).__name__)
            return []
        if not isinstance(payload, dict):
            self.errors.append(f"{self.name}: unexpected payload type")
            return []
        if payload.get("status") == "error":
            self.errors.append(f"{self.name}: API error: {payload.get('message', 'unknown')}")
            self.log.warning("veriphone API error", provider=self.name,
                             message=str(payload.get("message", "")))
            return []
        return self._to_results(payload, cached)

    def _to_results(self, payload: dict[str, Any], cached: bool) -> list[TelecomResult]:
        raw = {k: payload.get(k) for k in _FIELDS if k in payload}
        raw["from_cache"] = cached
        results: list[TelecomResult] = []
        for field in _FIELDS:
            value = payload.get(field)
            if value is None or value == "" or value == []:
                continue
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            note = ""
            if field == "carrier":
                note = CARRIER_NOTE
            elif field == "phone_region":
                note = "numbering-plan region as reported by provider; not a current location"
            results.append(TelecomResult(provider=self.name, field=field, value=str(value),
                                         confidence=0.6, note=note, raw=raw))
        return results
