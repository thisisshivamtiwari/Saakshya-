"""
PhoneInfoga sidecar provider (https://sundowndev.github.io/phoneinfoga/).

PhoneInfoga is run locally as a REST sidecar::

    phoneinfoga serve --no-client      # then PHONEINFOGA_URL=http://localhost:5000

Endpoints used (see ``web/docs/swagger.yaml`` upstream):

* ``GET  /api/``                                -> ``{"version", "commit", "success", "demo"}``
* ``POST /api/v2/numbers``                      -> ``{"valid","local","e164","international",
                                                      "countryCode","country","carrier"}``
* ``POST /api/v2/scanners/{name}/dryrun``       -> ``{"success", "error"}``
* ``POST /api/v2/scanners/{name}/run``          -> ``{"result": {...}}``

Only the ``local`` and ``numverify`` scanners are executed.  The
``googlesearch`` / ``googlecse`` scanners are never called (this engine has
its own search providers and query planner).

Caveat carried on every scanner record: PhoneInfoga is upstream-unmaintained
(README, 2026-01); its results are libphonenumber-2022-metadata or third-party
API passthrough and are never identity evidence.

All requests use a 10 s timeout; every error is recorded in ``self.errors``
and the provider returns whatever it collected so far (or ``[]``).
"""

from __future__ import annotations

from typing import Any, ClassVar, Optional

import httpx

from core.http import RateLimitedError
from core.models import NormalizedPhone, ProviderState, TelecomResult
from providers.base import PhoneIntelProvider
from storage.cache import cache_key

UNMAINTAINED_NOTE = (
    "PhoneInfoga is upstream-unmaintained (README 2026-01); results are libphonenumber-2022-metadata "
    "or third-party API passthrough; never identity evidence"
)
UNAVAILABLE_REASON = "PHONEINFOGA_URL not set (run `phoneinfoga serve --no-client`)"
SCANNERS: tuple[str, ...] = ("local", "numverify")
NEVER_SCANNERS: frozenset[str] = frozenset({"googlesearch", "googlecse"})
TIMEOUT_SECONDS = 10.0
_NUMBER_FIELDS: tuple[str, ...] = (
    "valid", "local", "e164", "international", "countryCode", "country", "carrier",
)
_SCALARS = (str, int, float, bool)


class PhoneInfogaProvider(PhoneIntelProvider):
    name: ClassVar[str] = "phoneinfoga"
    requires: ClassVar[tuple[str, ...]] = ()
    paid: ClassVar[bool] = False
    docs_url: ClassVar[str] = "https://sundowndev.github.io/phoneinfoga/"
    rate_per_second: ClassVar[float] = 5.0

    # ------------------------------------------------------------------ #
    # availability
    # ------------------------------------------------------------------ #
    @property
    def base_url(self) -> str:
        return (self.settings.phoneinfoga_url or "").rstrip("/")

    def extra_state_check(self) -> ProviderState:
        return ProviderState.AVAILABLE if self.base_url else ProviderState.NOT_INSTALLED

    def unavailable_reason(self) -> str:
        if self.state == ProviderState.NOT_INSTALLED:
            return UNAVAILABLE_REASON
        return super().unavailable_reason()

    # ------------------------------------------------------------------ #
    # HTTP helpers (10 s timeout, manual cache for POST results)
    # ------------------------------------------------------------------ #
    async def _call(self, method: str, path: str, body: Optional[dict[str, Any]] = None,
                    *, cache_parts: Optional[tuple[str, ...]] = None) -> Optional[dict[str, Any]]:
        """Return parsed JSON dict or None (error recorded)."""
        cache = self.http.cache
        key = cache_key(self.name, path, *cache_parts) if cache_parts is not None else None
        if key is not None and cache is not None:
            entry = cache.get(key, max_age=self.default_cache_ttl)
            if entry is not None and isinstance(entry.payload, dict):
                self.http.cache_hits += 1
                return entry.payload
        url = f"{self.base_url}{path}"
        try:
            response = await self.http.request(method, url, json_body=body, timeout=TIMEOUT_SECONDS,
                                               rate=self.rate_per_second, max_retries=0)
        except RateLimitedError:
            self.errors.append(f"{self.name}: rate limited on {path}")
            self.log.warning("phoneinfoga rate limited", provider=self.name, path=path)
            return None
        except (httpx.HTTPError, OSError) as exc:
            self.errors.append(f"{self.name}: {type(exc).__name__} on {path}")
            self.log.warning("phoneinfoga request error", provider=self.name, path=path,
                             error=type(exc).__name__)
            return None
        if response.status_code >= 400:
            self.errors.append(f"{self.name}: HTTP {response.status_code} on {path}")
            self.log.warning("phoneinfoga request failed", provider=self.name, path=path,
                             status=response.status_code)
            return None
        try:
            payload = response.json()
        except ValueError:
            self.errors.append(f"{self.name}: invalid JSON on {path}")
            return None
        if not isinstance(payload, dict):
            self.errors.append(f"{self.name}: unexpected payload on {path}")
            return None
        if key is not None and cache is not None:
            cache.set(key, payload, url=url, status=response.status_code)
        return payload

    # ------------------------------------------------------------------ #
    def _record(self, provider: str, field: str, value: Any, confidence: float, raw: dict[str, Any],
                note: str = UNMAINTAINED_NOTE) -> TelecomResult:
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        return TelecomResult(provider=provider, field=field, value=str(value), confidence=confidence,
                             note=note, raw=raw)

    async def lookup(self, phone: NormalizedPhone) -> list[TelecomResult]:
        if not self.base_url:
            self.errors.append(f"{self.name}: {UNAVAILABLE_REASON}")
            return []
        if not phone.e164:
            return []
        self.calls += 1
        number = phone.e164.lstrip("+")
        results: list[TelecomResult] = []

        health = await self._call("GET", "/api/")
        if health is None:
            return []
        version = health.get("version") or "unknown"
        commit = health.get("commit") or ""
        health_raw = {"version": version, "commit": commit, "demo": health.get("demo")}
        results.append(self._record(self.name, "phoneinfoga_version",
                                    f"{version}" + (f" ({commit})" if commit else ""), 0.9, health_raw,
                                    note="Version reported by the local PhoneInfoga sidecar."))

        info = await self._call("POST", "/api/v2/numbers", {"number": number}, cache_parts=(number,))
        if info is not None:
            raw = {k: info.get(k) for k in _NUMBER_FIELDS if k in info}
            for field in _NUMBER_FIELDS:
                value = info.get(field)
                if value is None or value == "":
                    continue
                note = UNMAINTAINED_NOTE
                if field == "carrier":
                    note = UNMAINTAINED_NOTE + "; carrier is original allocation (MNP applies)"
                results.append(self._record(self.name, field, value, 0.4, raw, note=note))

        for scanner in SCANNERS:
            if scanner in NEVER_SCANNERS:  # defensive: never run search-engine scanners
                continue
            results.extend(await self._run_scanner(scanner, number))
        return results

    async def _run_scanner(self, scanner: str, number: str) -> list[TelecomResult]:
        body = {"number": number, "options": {}}
        dry = await self._call("POST", f"/api/v2/scanners/{scanner}/dryrun", body)
        if dry is None or not dry.get("success"):
            reason = (dry or {}).get("error") or "dry run unavailable"
            self.log.info("phoneinfoga scanner skipped", provider=self.name, scanner=scanner,
                          reason=str(reason))
            return []
        run = await self._call("POST", f"/api/v2/scanners/{scanner}/run", body, cache_parts=(scanner, number))
        if run is None:
            return []
        result = run.get("result")
        if not isinstance(result, dict):
            return []
        provider_name = f"{self.name}:{scanner}"
        raw = {k: v for k, v in result.items() if isinstance(v, _SCALARS) or v is None}
        out: list[TelecomResult] = []
        for field, value in result.items():
            if value is None or value == "" or not isinstance(value, _SCALARS):
                continue
            out.append(self._record(provider_name, str(field), value, 0.4, raw))
        return out
