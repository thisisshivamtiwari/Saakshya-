"""
Provider abstractions (spec section 26).

Every external source is a *provider* with a uniform lifecycle:

* declares which settings keys it needs (``requires``) and whether it is
  paid (``paid``);
* reports ``state`` (available / missing_key / disabled / not_installed);
* is skipped gracefully by the registry when unavailable;
* uses the shared ``HttpClient`` (rate limits, retries, caching);
* never returns raw provider payloads to the rest of the engine - only the
  core models (``SearchResult``, ``TelecomResult``, ``SocialProfile`` ...).

Categories
----------
``SearchProvider``       - web search (Brave, SerpAPI, Google CSE, Serper, SearXNG, fixture)
``PhoneIntelProvider``   - telecom / numbering intelligence
``UsernameProvider``     - public-profile existence checks for a username
``PlaceProvider``        - business/place lookup by phone number (Google Places, OSM)
``ImageSearchProvider``  - reverse image search
``RegistryProvider``     - public registry search (Indian Kanoon API etc.)
"""

from __future__ import annotations

import abc
from typing import Any, ClassVar, Optional

from config.settings import Settings, get_settings
from core.http import HttpClient
from core.logging import get_logger
from core.models import (
    Business,
    NormalizedPhone,
    ProviderInfo,
    ProviderState,
    SearchResult,
    SocialProfile,
    TelecomResult,
)


class BaseProvider(abc.ABC):
    """Common lifecycle for all providers."""

    name: ClassVar[str] = "base"
    category: ClassVar[str] = "base"  # search / phone / username / place / image / registry
    requires: ClassVar[tuple[str, ...]] = ()  # Settings attribute names that must be set
    paid: ClassVar[bool] = False
    docs_url: ClassVar[str] = ""
    rate_per_second: ClassVar[float] = 1.0
    default_cache_ttl: ClassVar[int] = 72 * 3600

    def __init__(self, settings: Optional[Settings] = None, http: Optional[HttpClient] = None) -> None:
        self.settings = settings or get_settings()
        self.http = http or HttpClient(self.settings)
        self._owns_http = http is None
        self.log = get_logger(f"providers.{self.name}")
        self.errors: list[str] = []
        self.calls = 0

    # ------------------------------------------------------------------ #
    @property
    def state(self) -> ProviderState:
        if not all(self.settings.secret(k) for k in self.requires):
            return ProviderState.MISSING_KEY
        return self.extra_state_check()

    def extra_state_check(self) -> ProviderState:
        """Override for providers that need a binary / package / URL."""
        return ProviderState.AVAILABLE

    @property
    def available(self) -> bool:
        return self.state == ProviderState.AVAILABLE

    def unavailable_reason(self) -> str:
        st = self.state
        if st == ProviderState.MISSING_KEY:
            return f"missing configuration: {', '.join(self.requires)}"
        if st == ProviderState.NOT_INSTALLED:
            return "required binary/package not installed"
        if st == ProviderState.DISABLED:
            return "disabled by configuration"
        return ""

    def info(self) -> ProviderInfo:
        return ProviderInfo(name=self.name, category=self.category, state=self.state, paid=self.paid,
                            reason=self.unavailable_reason(), docs_url=self.docs_url)

    def secret(self, key: str) -> str:
        value = self.settings.secret(key)
        if value is None:
            raise RuntimeError(f"{self.name}: missing setting {key}")
        return value

    async def aclose(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} name={self.name} state={self.state.value}>"


# --------------------------------------------------------------------------- #
# Category interfaces
# --------------------------------------------------------------------------- #


class SearchProvider(BaseProvider):
    category: ClassVar[str] = "search"
    supports_site_operator: ClassVar[bool] = True
    supports_filetype_operator: ClassVar[bool] = True
    supports_exact_phrase: ClassVar[bool] = True
    max_results_per_call: ClassVar[int] = 10

    @abc.abstractmethod
    async def search(self, query: str, *, max_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        """Execute one query and return normalised results (never raises for empty results)."""


class PhoneIntelProvider(BaseProvider):
    category: ClassVar[str] = "phone"

    @abc.abstractmethod
    async def lookup(self, phone: NormalizedPhone) -> list[TelecomResult]:
        """Return (provider, field, value, confidence) records - never identity claims."""


class UsernameProvider(BaseProvider):
    category: ClassVar[str] = "username"

    @abc.abstractmethod
    async def check(self, username: str, *, max_sites: int = 50) -> list[SocialProfile]:
        """Check public profile URLs for a username.  Public pages only; no login."""


class PlaceProvider(BaseProvider):
    category: ClassVar[str] = "place"

    @abc.abstractmethod
    async def find_by_phone(self, phone: NormalizedPhone) -> list[Business]:
        """Look up public business listings that display the phone number."""


class ImageSearchProvider(BaseProvider):
    category: ClassVar[str] = "image"

    @abc.abstractmethod
    async def reverse_search(self, image_url: str, *, max_results: int = 10) -> list[SearchResult]:
        """Reverse image search on a *public* image URL (no facial recognition)."""


class RegistryProvider(BaseProvider):
    category: ClassVar[str] = "registry"

    @abc.abstractmethod
    async def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]:
        """Full-text search of a public registry / legal database."""
