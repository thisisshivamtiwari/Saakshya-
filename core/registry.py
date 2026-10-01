"""
Provider registry: instantiates every known provider, reports availability,
and hands the engine only the providers that are configured and enabled.

Provider classes are discovered from ``providers.catalog.PROVIDER_CLASSES``.
A provider whose module fails to import (e.g. an optional dependency is
missing) is recorded as ``NOT_INSTALLED`` rather than crashing the engine.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from config.settings import Settings, get_settings
from core.http import HttpClient
from core.logging import get_logger
from core.models import ProviderInfo, ProviderState
from providers.base import (
    BaseProvider,
    ImageSearchProvider,
    PhoneIntelProvider,
    PlaceProvider,
    RegistryProvider,
    SearchProvider,
    UsernameProvider,
)

log = get_logger("registry")


class ProviderRegistry:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        http: Optional[HttpClient] = None,
        *,
        only: Optional[Sequence[str]] = None,
        offline: bool = False,
        fixture_path: Optional[str] = None,
        extra_providers: Optional[Iterable[BaseProvider]] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http = http or HttpClient(self.settings)
        self.only = {n.strip().lower() for n in only} if only else None
        self.offline = offline
        self.providers: dict[str, BaseProvider] = {}
        self.import_errors: dict[str, str] = {}
        self._load(fixture_path)
        for p in extra_providers or []:
            self.providers[p.name] = p

    # ------------------------------------------------------------------ #
    def _load(self, fixture_path: Optional[str]) -> None:
        from providers.catalog import load_provider_classes

        classes, errors = load_provider_classes()
        self.import_errors.update(errors)
        for cls in classes:
            try:
                if cls.name == "fixture":
                    inst = cls(self.settings, self.http, fixture_path=fixture_path)  # type: ignore[call-arg]
                else:
                    inst = cls(self.settings, self.http)
            except Exception as exc:  # pragma: no cover - defensive
                self.import_errors[cls.name] = f"{type(exc).__name__}: {exc}"
                continue
            self.providers[inst.name] = inst

    # ------------------------------------------------------------------ #
    def _enabled(self, p: BaseProvider) -> bool:
        if self.offline:
            return p.name == "fixture" or p.name == "libphonenumber"
        if p.name == "fixture":
            return bool(self.only and "fixture" in self.only)
        if self.only is not None and p.name not in self.only:
            return False
        return p.available

    def get(self, name: str) -> Optional[BaseProvider]:
        return self.providers.get(name)

    def _of(self, kind: type) -> list:
        return [p for p in self.providers.values() if isinstance(p, kind) and self._enabled(p)]

    def search_providers(self) -> list[SearchProvider]:
        return self._of(SearchProvider)

    def phone_providers(self) -> list[PhoneIntelProvider]:
        return self._of(PhoneIntelProvider)

    def username_providers(self) -> list[UsernameProvider]:
        return self._of(UsernameProvider)

    def place_providers(self) -> list[PlaceProvider]:
        return self._of(PlaceProvider)

    def image_providers(self) -> list[ImageSearchProvider]:
        return self._of(ImageSearchProvider)

    def registry_providers(self) -> list[RegistryProvider]:
        return self._of(RegistryProvider)

    def infos(self) -> list[ProviderInfo]:
        infos = [p.info() for p in self.providers.values()]
        for name, err in self.import_errors.items():
            infos.append(ProviderInfo(name=name, category="unknown", state=ProviderState.NOT_INSTALLED, reason=err))
        for info in infos:
            if self.only is not None and info.name not in self.only and info.state == ProviderState.AVAILABLE:
                info.state = ProviderState.DISABLED
                info.reason = "not selected via --providers"
        return sorted(infos, key=lambda i: (i.category, i.name))

    def summary(self) -> str:
        lines = []
        for i in self.infos():
            flag = "PAID" if i.paid else "free"
            lines.append(f"{i.category:9} {i.name:18} {i.state.value:14} {flag:5} {i.reason}")
        return "\n".join(lines)

    async def aclose(self) -> None:
        await self.http.aclose()
