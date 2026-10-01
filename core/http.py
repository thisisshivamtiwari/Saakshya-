"""
Shared asynchronous HTTP client used by every provider and collector.

Guarantees (spec sections 25, 34, 36):
* timeouts, bounded retries with exponential backoff (honouring ``Retry-After``
  on 429/503 - we back off, we never try to evade a rate limit);
* per-host token-bucket rate limiting and a global concurrency cap;
* optional robots.txt enforcement for page fetches (API calls are exempt
  because they are governed by the API's own terms);
* response-size limits and content-type allow-lists for page fetches;
* transparent SQLite caching of JSON API responses and fetched pages;
* secrets never appear in logs (headers are not logged).
"""

from __future__ import annotations

import asyncio
import random
import time
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

import httpx

from config.settings import Settings, get_settings
from core.logging import get_logger
from storage.cache import ResponseCache, cache_key, content_hash

log = get_logger("http")

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
PAGE_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/pdf",
    "application/json",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/rtf",
    "text/csv",
    "application/xml",
    "text/xml",
)


class RateLimitedError(Exception):
    """Raised when a provider keeps returning 429 after all retries."""


class RobotsDisallowedError(Exception):
    """Raised when robots.txt forbids fetching a URL."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str = ""
    text: str = ""
    content: bytes = b""
    from_cache: bool = False
    content_hash: str = ""
    elapsed_ms: int = 0
    error: str = ""
    robots_allowed: Optional[bool] = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and not self.error


class TokenBucket:
    """Simple async token bucket: ``rate`` tokens per second, burst of ``burst``."""

    def __init__(self, rate: float, burst: int = 2) -> None:
        self.rate = max(rate, 0.01)
        self.capacity = max(burst, 1)
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            wait = (1 - self.tokens) / self.rate
        await asyncio.sleep(wait)
        async with self._lock:
            self.tokens = max(0.0, self.tokens - 1)
            self.updated = time.monotonic()


class RobotsCache:
    """Fetches and caches robots.txt per host; fails open only on network errors, never on Disallow."""

    def __init__(self, client: "HttpClient") -> None:
        self._client = client
        self._parsers: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._lock = asyncio.Lock()

    async def allowed(self, url: str, user_agent: str) -> bool:
        parts = urlsplit(url)
        host_key = f"{parts.scheme}://{parts.netloc}"
        async with self._lock:
            if host_key not in self._parsers:
                self._parsers[host_key] = await self._load(host_key)
        parser = self._parsers[host_key]
        if parser is None:
            return True  # no robots.txt reachable -> permitted (standard behaviour)
        try:
            return parser.can_fetch(user_agent, url) and parser.can_fetch("*", url)
        except Exception:  # pragma: no cover - defensive
            return True

    async def _load(self, host_key: str) -> Optional[urllib.robotparser.RobotFileParser]:
        robots_url = f"{host_key}/robots.txt"
        try:
            res = await self._client.raw_get(robots_url, timeout=8.0)
        except Exception:
            return None
        if res.status_code >= 400:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(res.text.splitlines())
        return parser


class HttpClient:
    """
    Facade over ``httpx.AsyncClient``.

    Use ``get_json`` for API calls (cached, rate-limited, retried) and
    ``fetch_page`` for public web pages/documents (adds robots.txt and
    size/content-type checks).
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        cache: Optional[ResponseCache] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.http_timeout_seconds),
            headers={"User-Agent": self.settings.user_agent, "Accept-Language": "en-IN,en;q=0.9"},
            follow_redirects=True,
            transport=transport,
        )
        self._buckets: dict[str, TokenBucket] = {}
        self._semaphore = asyncio.Semaphore(max(1, self.settings.max_concurrency))
        self.robots = RobotsCache(self)
        self.request_count = 0
        self.cache_hits = 0

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def bucket_for(self, host: str, rate: Optional[float] = None, burst: int = 2) -> TokenBucket:
        if host not in self._buckets:
            self._buckets[host] = TokenBucket(rate or self.settings.per_host_rate_per_second, burst)
        return self._buckets[host]

    async def raw_get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Uncached, un-retried GET (used for robots.txt)."""
        return await self._client.get(url, **kwargs)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        json_body: Any = None,
        data: Any = None,
        auth: Any = None,
        rate: Optional[float] = None,
        max_retries: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Rate-limited, retried request.  Raises ``RateLimitedError`` after repeated 429s."""
        host = urlsplit(url).netloc
        retries = self.settings.http_max_retries if max_retries is None else max_retries
        attempt = 0
        while True:
            await self.bucket_for(host, rate).acquire()
            async with self._semaphore:
                self.request_count += 1
                try:
                    response = await self._client.request(
                        method, url, params=params, headers=headers, json=json_body, data=data,
                        auth=auth, timeout=timeout or self.settings.http_timeout_seconds,
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= retries:
                        raise
                    delay = self._backoff(attempt)
                    log.warning("HTTP transient error; retrying", host=host, attempt=attempt + 1,
                                delay=round(delay, 1), error=type(exc).__name__)
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
            if response.status_code in RETRYABLE_STATUS and attempt < retries:
                delay = self._retry_after(response) or self._backoff(attempt)
                log.warning("HTTP retryable status; backing off", host=host, status=response.status_code,
                            attempt=attempt + 1, delay=round(delay, 1))
                await asyncio.sleep(delay)
                attempt += 1
                continue
            if response.status_code == 429:
                raise RateLimitedError(f"{host} rate limit persisted after {retries} retries")
            return response

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, (2 ** attempt) + random.uniform(0, 0.5))

    @staticmethod
    def _retry_after(response: httpx.Response) -> Optional[float]:
        ra = response.headers.get("Retry-After")
        if not ra:
            return None
        try:
            return min(60.0, float(ra))
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    # public helpers
    # ------------------------------------------------------------------ #
    async def get_json(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        auth: Any = None,
        namespace: str = "api",
        cache_ttl: Optional[int] = None,
        rate: Optional[float] = None,
        method: str = "GET",
        json_body: Any = None,
    ) -> tuple[Any, bool]:
        """
        GET/POST a JSON API endpoint.  Returns ``(payload, from_cache)``.
        Cache key = namespace + url + sorted params (+ body); headers/auth are
        deliberately excluded so secrets never reach the cache.
        """
        key_parts = [url, repr(sorted((params or {}).items())), repr(json_body) if json_body else ""]
        key = cache_key(namespace, *key_parts)
        if self.cache is not None:
            entry = self.cache.get(key, max_age=cache_ttl)
            if entry is not None:
                self.cache_hits += 1
                return entry.payload, True
        response = await self.request(method, url, params=params, headers=headers, auth=auth,
                                      rate=rate, json_body=json_body)
        response.raise_for_status()
        payload = response.json()
        if self.cache is not None:
            self.cache.set(key, payload, url=url, query=repr(params or {}), status=response.status_code)
        return payload, False

    async def fetch_page(
        self,
        url: str,
        *,
        cache_ttl: Optional[int] = None,
        check_robots: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        allowed_types: tuple[str, ...] = PAGE_CONTENT_TYPES,
    ) -> FetchResult:
        """
        Fetch a public web page or document with robots.txt, size and
        content-type safeguards.  Never raises for HTTP errors; inspect
        ``FetchResult.ok`` / ``.error``.
        """
        started = time.monotonic()
        check = self.settings.respect_robots if check_robots is None else check_robots
        key = cache_key("page", url)
        if self.cache is not None:
            entry = self.cache.get(key, max_age=cache_ttl)
            if entry is not None:
                self.cache_hits += 1
                p = entry.payload
                return FetchResult(url=url, final_url=p.get("final_url", url), status=p.get("status", 0),
                                   content_type=p.get("content_type", ""), text=p.get("text", ""),
                                   from_cache=True, content_hash=entry.content_hash,
                                   robots_allowed=p.get("robots_allowed"))
        robots_allowed: Optional[bool] = None
        if check:
            robots_allowed = await self.robots.allowed(url, self.settings.user_agent)
            if not robots_allowed:
                log.info("robots.txt disallows fetch; skipping", host=urlsplit(url).netloc)
                return FetchResult(url=url, final_url=url, status=0, error="robots_disallowed",
                                   robots_allowed=False)
        limit = max_bytes or self.settings.max_fetch_bytes
        try:
            response = await self.request("GET", url)
        except RateLimitedError as exc:
            return FetchResult(url=url, final_url=url, status=429, error=str(exc), robots_allowed=robots_allowed)
        except (httpx.HTTPError, OSError) as exc:
            return FetchResult(url=url, final_url=url, status=0, error=f"{type(exc).__name__}: {exc}",
                               robots_allowed=robots_allowed)
        ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype and not any(ctype.startswith(t) for t in allowed_types):
            return FetchResult(url=url, final_url=str(response.url), status=response.status_code,
                               content_type=ctype, error=f"unsupported content-type {ctype}",
                               robots_allowed=robots_allowed)
        content = response.content
        if len(content) > limit:
            return FetchResult(url=url, final_url=str(response.url), status=response.status_code,
                               content_type=ctype, error=f"response too large ({len(content)} bytes)",
                               robots_allowed=robots_allowed)
        text = "" if ctype.startswith("application/pdf") or "officedocument" in ctype or ctype.startswith(
            "application/msword") or ctype.startswith("application/vnd.ms-") else response.text
        digest = content_hash(content)
        result = FetchResult(url=url, final_url=str(response.url), status=response.status_code,
                             content_type=ctype, text=text, content=content, content_hash=digest,
                             elapsed_ms=int((time.monotonic() - started) * 1000), robots_allowed=robots_allowed,
                             headers={k.lower(): v for k, v in response.headers.items()
                                      if k.lower() in ("last-modified", "content-type", "content-length")})
        if self.cache is not None and result.ok and text:
            # binary documents are not cached (they are parsed once by the document collector)
            self.cache.set(key, {"final_url": result.final_url, "status": result.status,
                                 "content_type": ctype, "text": text, "robots_allowed": robots_allowed},
                           url=url, status=result.status)
        return result

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
