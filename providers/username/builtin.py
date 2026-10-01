"""
Built-in username checker using ONLY documented public APIs (no page scraping, no login):

* GitHub REST API  GET https://api.github.com/users/{username}   (public; 60 req/h anonymous, more with GITHUB_TOKEN)
* GitLab REST API  GET https://gitlab.com/api/v4/users?username=  (public)
* Keybase API      GET https://keybase.io/_/api/1.0/user/lookup.json?usernames=  (public)

Results are INFERRED ("a public account with this username exists"), never identity evidence.
Free; always available.  Opt-in via --username-enum.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from core.http import RateLimitedError
from core.models import Association, SocialProfile
from providers.base import UsernameProvider

_NOTE = "Identical usernames are not proof of the same person; INFERRED association only."


class BuiltinProfileChecker(UsernameProvider):
    name: ClassVar[str] = "builtin"
    requires: ClassVar[tuple[str, ...]] = ()
    paid: ClassVar[bool] = False
    docs_url: ClassVar[str] = "https://docs.github.com/en/rest/users/users"
    rate_per_second: ClassVar[float] = 0.5

    async def _get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        try:
            payload, _ = await self.http.get_json(url, params=params, headers=headers, namespace="builtin_username",
                                                  rate=self.rate_per_second)
            return payload
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                self.errors.append(f"{url.split('/')[2]}: http {exc.response.status_code}")
            return None
        except (RateLimitedError, httpx.HTTPError, ValueError) as exc:
            self.errors.append(f"{url.split('/')[2]}: {type(exc).__name__}")
            return None

    async def check(self, username: str, *, max_sites: int = 50) -> list[SocialProfile]:
        username = username.strip().lstrip("@")
        if not username or len(username) > 64 or "/" in username:
            return []
        out: list[SocialProfile] = []
        self.calls += 1
        gh_headers = {"Accept": "application/vnd.github+json"}
        token = self.settings.secret("github_token")
        if token:
            gh_headers["Authorization"] = f"Bearer {token}"
        gh = await self._get(f"https://api.github.com/users/{username}", headers=gh_headers)
        if isinstance(gh, dict) and gh.get("login"):
            out.append(SocialProfile(
                platform="github", username=gh["login"], display_name=gh.get("name") or "",
                profile_url=gh.get("html_url") or f"https://github.com/{username}",
                source_url=f"https://api.github.com/users/{username}", confidence=0.35, number_displayed=False,
                association=Association.INFERRED,
                matching_text=f"GitHub public profile exists (public repos: {gh.get('public_repos', '?')}; "
                              f"location: {gh.get('location') or 'n/a'}; blog: {gh.get('blog') or 'n/a'}). {_NOTE}",
            ))
        gl = await self._get("https://gitlab.com/api/v4/users", params={"username": username})
        if isinstance(gl, list) and gl:
            u = gl[0]
            out.append(SocialProfile(
                platform="gitlab", username=u.get("username") or username, display_name=u.get("name") or "",
                profile_url=u.get("web_url") or f"https://gitlab.com/{username}", source_url="https://gitlab.com/api/v4/users",
                confidence=0.3, number_displayed=False, association=Association.INFERRED,
                matching_text=f"GitLab public profile exists. {_NOTE}",
            ))
        kb = await self._get("https://keybase.io/_/api/1.0/user/lookup.json", params={"usernames": username})
        if isinstance(kb, dict):
            for them in kb.get("them") or []:
                if them and (them.get("basics") or {}).get("username"):
                    out.append(SocialProfile(
                        platform="keybase", username=them["basics"]["username"],
                        display_name=((them.get("profile") or {}).get("full_name") or ""),
                        profile_url=f"https://keybase.io/{username}", source_url="https://keybase.io/_/api/1.0/user/lookup.json",
                        confidence=0.3, number_displayed=False, association=Association.INFERRED,
                        matching_text=f"Keybase public profile exists. {_NOTE}",
                    ))
        return out[:max_sites]
