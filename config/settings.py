"""
Application settings.  All secrets come from the environment / ``.env``
(never from source code) and are held as ``SecretStr`` so they cannot leak
into logs or reports by accident.

Add new provider keys here and in ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ------------------------------------------------------------------ #
    # Search providers
    # ------------------------------------------------------------------ #
    brave_api_key: Optional[SecretStr] = Field(default=None, alias="BRAVE_API_KEY")
    serpapi_key: Optional[SecretStr] = Field(default=None, alias="SERPAPI_KEY")
    google_cse_api_key: Optional[SecretStr] = Field(default=None, alias="GOOGLE_CSE_API_KEY")
    google_cse_cx: Optional[str] = Field(default=None, alias="GOOGLE_CSE_CX")
    serper_api_key: Optional[SecretStr] = Field(default=None, alias="SERPER_API_KEY")
    tavily_api_key: Optional[SecretStr] = Field(default=None, alias="TAVILY_API_KEY")
    store_provider_snippets: bool = Field(default=False, alias="OSINT_STORE_PROVIDER_SNIPPETS")

    # ------------------------------------------------------------------ #
    # Phone intelligence providers
    # ------------------------------------------------------------------ #
    numverify_api_key: Optional[SecretStr] = Field(default=None, alias="NUMVERIFY_API_KEY")
    abstract_phone_api_key: Optional[SecretStr] = Field(default=None, alias="ABSTRACT_PHONE_API_KEY")
    veriphone_api_key: Optional[SecretStr] = Field(default=None, alias="VERIPHONE_API_KEY")
    twilio_account_sid: Optional[str] = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[SecretStr] = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    phoneinfoga_url: Optional[str] = Field(default=None, alias="PHONEINFOGA_URL")  # e.g. http://localhost:5000
    phoneinfoga_bin: Optional[str] = Field(default=None, alias="PHONEINFOGA_BIN")  # path to CLI binary

    # ------------------------------------------------------------------ #
    # Business / social / image / registry providers
    # ------------------------------------------------------------------ #
    google_places_api_key: Optional[SecretStr] = Field(default=None, alias="GOOGLE_PLACES_API_KEY")
    github_token: Optional[SecretStr] = Field(default=None, alias="GITHUB_TOKEN")
    youtube_api_key: Optional[SecretStr] = Field(default=None, alias="YOUTUBE_API_KEY")
    tineye_api_key: Optional[SecretStr] = Field(default=None, alias="TINEYE_API_KEY")
    indiankanoon_api_token: Optional[SecretStr] = Field(default=None, alias="INDIANKANOON_API_TOKEN")

    # ------------------------------------------------------------------ #
    # Engine behaviour
    # ------------------------------------------------------------------ #
    user_agent: str = Field(
        default="IndianPhoneOSINT/0.1 (+public-source research; respects robots.txt)",
        alias="OSINT_USER_AGENT",
    )
    data_dir: Path = Field(default=Path("data"), alias="OSINT_DATA_DIR")
    output_dir: Path = Field(default=Path("output"), alias="OSINT_OUTPUT_DIR")
    cache_ttl_hours: int = Field(default=72, alias="OSINT_CACHE_TTL_HOURS")
    respect_robots: bool = Field(default=True, alias="OSINT_RESPECT_ROBOTS")
    http_timeout_seconds: float = Field(default=20.0, alias="OSINT_HTTP_TIMEOUT")
    http_max_retries: int = Field(default=3, alias="OSINT_HTTP_MAX_RETRIES")
    max_concurrency: int = Field(default=6, alias="OSINT_MAX_CONCURRENCY")
    per_host_rate_per_second: float = Field(default=1.0, alias="OSINT_PER_HOST_RATE")
    max_fetch_bytes: int = Field(default=5_000_000, alias="OSINT_MAX_FETCH_BYTES")
    log_level: str = Field(default="INFO", alias="OSINT_LOG_LEVEL")
    log_json: bool = Field(default=False, alias="OSINT_LOG_JSON")
    snapshot_excerpt_chars: int = Field(default=1200, alias="OSINT_SNAPSHOT_EXCERPT_CHARS")

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #
    @property
    def cache_path(self) -> Path:
        return self.data_dir / "cache.sqlite"

    @property
    def evidence_db_path(self) -> Path:
        return self.data_dir / "evidence.sqlite"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"

    def secret(self, name: str) -> Optional[str]:
        """Return the plain value of a SecretStr field (or a plain str field), never logged."""
        value = getattr(self, name, None)
        if value is None:
            return None
        if isinstance(value, SecretStr):
            v = value.get_secret_value()
            return v or None
        return str(value) or None

    def has(self, *names: str) -> bool:
        return all(self.secret(n) for n in names)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """For tests that monkeypatch the environment."""
    get_settings.cache_clear()
