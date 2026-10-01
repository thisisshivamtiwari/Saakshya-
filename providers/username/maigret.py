"""
Maigret wrapper - optional, opt-in username correlation on PUBLIC profile pages.

Source: https://github.com/soxoj/maigret (MIT, PyPI ``maigret``; verified 2026-09-07: releases in 2026).
Install: ``pip install "maigret>=0.6.5,<0.7"``.  State is NOT_INSTALLED when the package is absent.

Boundary enforcement (hard-coded, not configurable):
* only unauthenticated GETs to public profile URLs from Maigret's bundled database;
* sites requiring "activation" (guest tokens / JWT), "protection" (TLS fingerprinting, Cloudflare
  challenges) or "similar_search" are filtered out;
* we never pass cookies, cloudflare_bypass, proxies or enrichment options;
* results are INFERRED only ("this username exists there"), never identity evidence.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

from core.models import Association, ProviderState, SocialProfile
from providers.base import UsernameProvider


def _maigret_available() -> bool:
    try:
        import maigret  # noqa: F401

        return True
    except Exception:
        return False


class MaigretProvider(UsernameProvider):
    name: ClassVar[str] = "maigret"
    requires: ClassVar[tuple[str, ...]] = ()
    paid: ClassVar[bool] = False
    docs_url: ClassVar[str] = "https://github.com/soxoj/maigret"
    top_sites: ClassVar[int] = 300
    timeout: ClassVar[int] = 15
    max_connections: ClassVar[int] = 10

    def extra_state_check(self) -> ProviderState:
        return ProviderState.AVAILABLE if _maigret_available() else ProviderState.NOT_INSTALLED

    def unavailable_reason(self) -> str:
        if self.state == ProviderState.NOT_INSTALLED:
            return "maigret not installed (pip install 'maigret>=0.6.5,<0.7'); username checks are opt-in"
        return super().unavailable_reason()

    def _sites(self, max_sites: int) -> dict[str, Any]:
        from maigret.db_updater import BUNDLED_DB_PATH  # type: ignore
        from maigret.sites import MaigretDatabase  # type: ignore

        db = MaigretDatabase().load_from_path(BUNDLED_DB_PATH)  # bundled, offline; no auto-update
        sites = db.ranked_sites_dict(top=max(max_sites, 1), disabled=False, excluded_tags=["nsfw", "dating"],
                                     id_type="username")
        return {
            n: s for n, s in sites.items()
            if not getattr(s, "activation", None) and not getattr(s, "protection", None)
            and not getattr(s, "similar_search", False)
        }

    async def check(self, username: str, *, max_sites: int = 50) -> list[SocialProfile]:
        if not self.available or not username:
            return []
        from maigret import search as maigret_search  # type: ignore

        sites = self._sites(min(max_sites, self.top_sites))
        log = logging.getLogger("maigret")
        log.setLevel(logging.ERROR)
        self.calls += 1
        try:
            results = await asyncio.wait_for(
                maigret_search(username=username, site_dict=sites, logger=log, query_notify=None,
                               timeout=self.timeout, max_connections=self.max_connections, retries=0,
                               is_parsing_enabled=False, is_enrich_enabled=False),
                timeout=self.timeout * 6,
            )
        except Exception as exc:
            self.errors.append(type(exc).__name__)
            self.log.warning("maigret run failed", error=type(exc).__name__)
            return []
        out: list[SocialProfile] = []
        for site_name, r in (results or {}).items():
            st = r.get("status")
            try:
                found = bool(st and st.is_found())
            except Exception:
                found = False
            if not found:
                continue
            out.append(SocialProfile(
                platform=str(site_name).lower(), username=username, profile_url=str(r.get("url_user") or ""),
                source_url=str(r.get("url_user") or ""), confidence=0.3, number_displayed=False,
                association=Association.INFERRED,
                matching_text=f"Username '{username}' exists on {site_name} (public profile URL responded). "
                              "Identical usernames are not proof of the same person.",
            ))
        return out
