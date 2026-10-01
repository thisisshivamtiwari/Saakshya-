"""
Twilio Lookup v2 - line type intelligence ONLY (PAID, optional).

* Endpoint: ``GET https://lookups.twilio.com/v2/PhoneNumbers/<e164>?Fields=line_type_intelligence``
* Auth: HTTP Basic (Account SID, Auth Token) via ``httpx.BasicAuth`` - passed as
  ``auth=`` so it is excluded from the response-cache key.
* Cost: ~US$0.008 per request for ``line_type_intelligence`` (basic formatting
  is free).  ``paid = True``.

HARD RULE
---------
This engine only ever requests numbering/line-type data.  The following
Twilio data packages are **forbidden** because they are identity, risk or
account-state lookups that go beyond public-source research:

``caller_name``, ``sim_swap``, ``identity_match``, ``reassigned_number``,
``pre_fill``, ``phone_number_quality_score``, ``sms_pumping_risk``, ``line_status``.

``validate_fields`` raises ``ValueError`` if any of them (or any unknown
package) is requested; it is enforced on construction and on every lookup.

The MCC/MNC returned by Twilio is decoded with the offline table in
``providers.phone.india_mccmnc`` (confidence 0.5).  Carrier information is the
current network-level operator as seen by Twilio's data partners, but is still
labelled as non-identity information.
"""

from __future__ import annotations

from typing import Any, ClassVar, Iterable, Optional

import httpx

from core.http import RateLimitedError
from core.models import NormalizedPhone, TelecomResult
from providers.base import PhoneIntelProvider
from providers.phone.india_mccmnc import decode_mccmnc

TWILIO_LOOKUP_URL = "https://lookups.twilio.com/v2/PhoneNumbers/{e164}"

FORBIDDEN_FIELDS: frozenset[str] = frozenset({
    "caller_name",
    "sim_swap",
    "identity_match",
    "reassigned_number",
    "pre_fill",
    "phone_number_quality_score",
    "sms_pumping_risk",
    "line_status",
})
ALLOWED_FIELDS: frozenset[str] = frozenset({"line_type_intelligence"})
DEFAULT_FIELDS: tuple[str, ...] = ("line_type_intelligence",)

CARRIER_NOTE = (
    "Carrier name from Twilio line-type intelligence (network-level data). "
    "Not an identity claim; may lag behind number portability."
)


def validate_fields(fields: Iterable[str]) -> tuple[str, ...]:
    """Return the fields as a tuple, raising ``ValueError`` for forbidden or unknown packages."""
    requested = tuple(str(f).strip() for f in fields)
    forbidden = sorted(f for f in requested if f in FORBIDDEN_FIELDS)
    if forbidden:
        raise ValueError(
            f"Twilio Lookup fields {forbidden} are forbidden by policy (identity/risk lookups); "
            f"only {sorted(ALLOWED_FIELDS)} may be requested."
        )
    unknown = sorted(f for f in requested if f not in ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"Twilio Lookup fields {unknown} are not allowed; only {sorted(ALLOWED_FIELDS)}.")
    if not requested:
        raise ValueError("At least one Twilio Lookup field is required (line_type_intelligence).")
    return requested


class TwilioLookupProvider(PhoneIntelProvider):
    name: ClassVar[str] = "twilio"
    requires: ClassVar[tuple[str, ...]] = ("twilio_account_sid", "twilio_auth_token")
    paid: ClassVar[bool] = True  # ~$0.008 / request for line_type_intelligence
    docs_url: ClassVar[str] = "https://www.twilio.com/docs/lookup/v2-api"
    rate_per_second: ClassVar[float] = 2.0

    def __init__(self, *args: Any, fields: Optional[Iterable[str]] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields: tuple[str, ...] = validate_fields(fields if fields is not None else DEFAULT_FIELDS)

    async def lookup(self, phone: NormalizedPhone) -> list[TelecomResult]:
        if not phone.e164:
            return []
        fields = validate_fields(self.fields)  # guard again in case the attribute was mutated
        self.calls += 1
        url = TWILIO_LOOKUP_URL.format(e164=phone.e164)
        auth = httpx.BasicAuth(self.secret("twilio_account_sid"), self.secret("twilio_auth_token"))
        try:
            payload, cached = await self.http.get_json(
                url, params={"Fields": ",".join(fields)}, auth=auth, namespace=self.name,
                cache_ttl=self.default_cache_ttl, rate=self.rate_per_second,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason = {401: "invalid credentials", 402: "payment required", 404: "number not found",
                      429: "rate limited"}.get(status, "HTTP error")
            self.errors.append(f"{self.name}: HTTP {status} ({reason})")
            self.log.warning("twilio lookup failed", provider=self.name, status=status, reason=reason)
            return []
        except RateLimitedError:
            self.errors.append(f"{self.name}: rate limited")
            self.log.warning("twilio rate limited", provider=self.name)
            return []
        except (httpx.HTTPError, OSError, ValueError) as exc:
            self.errors.append(f"{self.name}: {type(exc).__name__}")
            self.log.warning("twilio request error", provider=self.name, error=type(exc).__name__)
            return []
        if not isinstance(payload, dict):
            self.errors.append(f"{self.name}: unexpected payload type")
            return []
        return self._to_results(payload, cached)

    def _to_results(self, payload: dict[str, Any], cached: bool) -> list[TelecomResult]:
        lti = payload.get("line_type_intelligence") or {}
        if not isinstance(lti, dict):
            lti = {}
        raw: dict[str, Any] = {
            "valid": payload.get("valid"),
            "validation_errors": payload.get("validation_errors"),
            "national_format": payload.get("national_format"),
            "country_code": payload.get("country_code"),
            "calling_country_code": payload.get("calling_country_code"),
            "line_type_intelligence": {
                k: lti.get(k) for k in ("type", "carrier_name", "mobile_country_code",
                                        "mobile_network_code", "error_code")
            },
            "from_cache": cached,
        }
        results: list[TelecomResult] = []

        def add(field: str, value: Any, confidence: float, note: str = "") -> None:
            if value is None or value == "" or value == []:
                return
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            results.append(TelecomResult(provider=self.name, field=field, value=str(value),
                                         confidence=confidence, note=note, raw=raw))

        add("valid", payload.get("valid"), 0.7)
        add("validation_errors", payload.get("validation_errors"), 0.7)
        add("national_format", payload.get("national_format"), 0.7)
        add("country_code", payload.get("country_code"), 0.7)
        add("line_type", lti.get("type"), 0.6)
        add("carrier_name", lti.get("carrier_name"), 0.6, CARRIER_NOTE)
        mcc = lti.get("mobile_country_code")
        mnc = lti.get("mobile_network_code")
        add("mobile_country_code", mcc, 0.6)
        add("mobile_network_code", mnc, 0.6)
        if mcc and mnc:
            decoded = decode_mccmnc(str(mcc), str(mnc))
            if decoded:
                label = decoded["operator"]
                if decoded.get("circle"):
                    label += f" ({decoded['circle']})"
                add("operator_from_mccmnc", label, 0.5,
                    "Decoded offline from MCC/MNC using a public-source table (best-effort; "
                    f"status: {decoded.get('status', 'unknown')}). Not an identity claim.")
        if lti.get("error_code"):
            add("line_type_error_code", lti.get("error_code"), 0.5)
        return results
