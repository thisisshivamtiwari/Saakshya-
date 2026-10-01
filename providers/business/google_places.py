"""
Google Places API (New) - Text Search by phone number.

Source: https://developers.google.com/maps/documentation/places/web-service/text-search
Docs (verified 2026-09-08): "For best results when searching on a phone number, include the country code
followed by a space, and set the regionCode parameter ... Places API (New) supports the E.164 format."
Auth: header ``X-Goog-Api-Key``; field mask header ``X-Goog-FieldMask``.
Pricing: phone-number searches return enterprise fields and bill under the *Text Search Enterprise* SKU
(monthly free credit applies; PAID OPTIONAL PROVIDER beyond that).
Stored: business name, address, phone(s), website, types, Google Maps URL - all public listing data.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from core.http import RateLimitedError
from core.models import Business, NormalizedPhone
from core.normalize import normalize_indian_number
from providers.base import PlaceProvider

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ("places.id,places.displayName,places.formattedAddress,places.internationalPhoneNumber,"
              "places.nationalPhoneNumber,places.websiteUri,places.types,places.googleMapsUri,"
              "places.addressComponents,places.businessStatus")


class GooglePlacesProvider(PlaceProvider):
    name: ClassVar[str] = "google_places"
    requires: ClassVar[tuple[str, ...]] = ("google_places_api_key",)
    paid: ClassVar[bool] = True
    docs_url: ClassVar[str] = "https://developers.google.com/maps/documentation/places/web-service/text-search"
    rate_per_second: ClassVar[float] = 2.0

    async def find_by_phone(self, phone: NormalizedPhone) -> list[Business]:
        if not self.available or not phone.e164:
            return []
        headers = {"X-Goog-Api-Key": self.secret("google_places_api_key"), "X-Goog-FieldMask": FIELD_MASK,
                   "Content-Type": "application/json"}
        body = {"textQuery": phone.international or phone.e164, "regionCode": "IN", "languageCode": "en"}
        self.calls += 1
        try:
            payload, _ = await self.http.get_json(ENDPOINT, method="POST", json_body=body, headers=headers,
                                                  namespace="google_places", rate=self.rate_per_second)
        except RateLimitedError:
            self.errors.append("rate limited")
            self.log.warning("google places rate limited")
            return []
        except httpx.HTTPStatusError as exc:
            self.errors.append(f"http {exc.response.status_code}")
            self.log.warning("google places error", status=exc.response.status_code)
            return []
        except (httpx.HTTPError, ValueError) as exc:
            self.errors.append(type(exc).__name__)
            return []
        out: list[Business] = []
        for p in (payload or {}).get("places", []) or []:
            out.append(self._to_business(p, phone))
        return [b for b in out if b.name]

    @staticmethod
    def _to_business(p: dict[str, Any], phone: NormalizedPhone) -> Business:
        name = ((p.get("displayName") or {}).get("text") or "").strip()
        city = ""
        for comp in p.get("addressComponents", []) or []:
            if "locality" in (comp.get("types") or []):
                city = comp.get("longText") or comp.get("shortText") or ""
        numbers: list[str] = []
        for key in ("internationalPhoneNumber", "nationalPhoneNumber"):
            raw = p.get(key)
            if raw:
                n = normalize_indian_number(str(raw))
                if n.is_valid and n.e164 != phone.e164 and n.e164 not in numbers:
                    numbers.append(n.e164)
        return Business(
            name=name, category=", ".join(t for t in (p.get("types") or [])[:3]),
            address=p.get("formattedAddress") or "", city=city, website=p.get("websiteUri") or "",
            social_urls=[p["googleMapsUri"]] if p.get("googleMapsUri") else [], other_numbers=numbers,
        )
