"""
Offline numbering-plan intelligence from Google libphonenumber (``phonenumbers``).

This provider never touches the network.  Everything it reports is derived
from the libphonenumber metadata bundled with the installed package:

* validity / possibility, formats (E.164, national, international);
* number type (mobile / fixed line / toll-free ...);
* the *original* carrier allocation of a mobile prefix (``phonenumbers.carrier``);
* the numbering-plan area of a fixed line (``phonenumbers.geocoder``);
* time zones (``phonenumbers.timezone``);
* whether the region participates in Mobile Number Portability (MNP).

India has had nationwide MNP since 2015, so the "original carrier" is a weak
signal (confidence 0.4) and is labelled as such.  Nothing here identifies a
person; the provider only ever emits numbering-plan facts.
"""

from __future__ import annotations

from typing import Any, ClassVar

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, carrier, geocoder, timezone

from core.models import NormalizedPhone, PhoneKind, TelecomResult
from providers.base import PhoneIntelProvider

MNP_NOTE = (
    "Original numbering-plan allocation from libphonenumber metadata. India has nationwide "
    "Mobile Number Portability; the current operator may differ."
)
GEOCODER_NOTE = "Numbering-plan area for fixed lines; for mobiles this is only 'India'"
_COUNTRY_NAMES: dict[str, str] = {"IN": "India"}


class LibPhoneNumberProvider(PhoneIntelProvider):
    """Always-available, fully offline numbering-plan lookup."""

    name: ClassVar[str] = "libphonenumber"
    requires: ClassVar[tuple[str, ...]] = ()
    paid: ClassVar[bool] = False
    docs_url: ClassVar[str] = "https://github.com/daviddrysdale/python-phonenumbers"
    rate_per_second: ClassVar[float] = 1000.0

    def _record(self, field: str, value: Any, confidence: float, raw: dict[str, Any],
                note: str = "") -> TelecomResult:
        return TelecomResult(provider=self.name, field=field, value=str(value), confidence=confidence,
                             note=note, raw=raw)

    async def lookup(self, phone: NormalizedPhone) -> list[TelecomResult]:
        self.calls += 1
        candidate = phone.e164 or phone.raw
        try:
            parsed = phonenumbers.parse(candidate, phone.region or "IN")
        except NumberParseException as exc:
            self.errors.append(f"{self.name}: could not parse number ({exc.error_type})")
            self.log.warning("libphonenumber parse failed", provider=self.name, error=str(exc.error_type))
            return []

        region_code = phonenumbers.region_code_for_number(parsed) or phone.region or ""
        is_valid = phonenumbers.is_valid_number(parsed)
        is_possible = phonenumbers.is_possible_number(parsed)
        e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        national = phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)
        international = phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL)
        original_carrier = carrier.name_for_number(parsed, "en") or ""
        description = geocoder.description_for_number(parsed, "en") or ""
        zones = list(timezone.time_zones_for_number(parsed))
        mnp = phonenumbers.is_mobile_number_portable_region(region_code or "IN")
        version = getattr(phonenumbers, "__version__", "unknown")
        kind = phone.kind if phone.kind != PhoneKind.UNKNOWN else PhoneKind.UNKNOWN

        raw: dict[str, Any] = {
            "country_code": parsed.country_code,
            "region_code": region_code,
            "e164": e164,
            "national_format": national,
            "international_format": international,
            "number_type": kind.value,
            "is_valid": is_valid,
            "is_possible": is_possible,
            "original_carrier": original_carrier,
            "geocoder_description": description,
            "timezones": zones,
            "mnp_region": mnp,
            "metadata_version": version,
        }

        results: list[TelecomResult] = [
            self._record("country", _COUNTRY_NAMES.get(region_code, region_code or "unknown"), 0.95, raw),
            self._record("country_code", parsed.country_code, 0.95, raw),
            self._record("region_code", region_code, 0.9, raw),
            self._record("national_format", national, 0.95, raw),
            self._record("international_format", international, 0.95, raw),
            self._record("e164", e164, 0.95, raw),
            self._record("number_type", kind.value, 0.8, raw,
                         note="Derived from libphonenumber number ranges (see core.normalize)."),
            self._record("is_valid", is_valid, 0.9, raw),
            self._record("is_possible", is_possible, 0.9, raw),
        ]
        if original_carrier:
            results.append(self._record(
                "original_carrier", original_carrier,
                0.4 if kind in (PhoneKind.MOBILE, PhoneKind.FIXED_LINE_OR_MOBILE) else 0.3,
                raw, note=MNP_NOTE,
            ))
        if description:
            results.append(self._record(
                "geocoder_description", description,
                0.6 if kind == PhoneKind.FIXED_LINE else 0.3, raw, note=GEOCODER_NOTE,
            ))
        if zones:
            results.append(self._record("timezones", ", ".join(zones), 0.7, raw))
        results.append(self._record(
            "mnp_region", mnp, 0.9, raw,
            note="Region supports Mobile Number Portability; carrier prefixes are not authoritative.",
        ))
        results.append(self._record("metadata_version", version, 1.0, raw,
                                    note="Version of the python-phonenumbers metadata used."))
        return results
