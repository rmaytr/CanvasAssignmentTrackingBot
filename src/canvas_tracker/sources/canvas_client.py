"""Read-only, host-pinned Canvas REST client (PRD §7.1, §10.2).

Only GET exists. Requests go one at a time, only to /api/v1/ paths on the
configured host; redirects and cross-host pagination are refused so the
token never leaves that host. Throttling and server errors are retried with
capped exponential backoff and full jitter.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from canvas_tracker import __version__

USER_AGENT = (
    f"CanvasAssignmentTrackingBot/{__version__} "
    "(+https://github.com/rmaytr/CanvasAssignmentTrackingBot)"
)
API_PREFIX = "/api/v1/"
Params = Mapping[str, str | Sequence[str]]


class CanvasError(Exception):
    """Base class. Messages never include tokens, URLs with secrets, or response bodies."""


class CanvasAuthError(CanvasError):
    """401: the token is invalid, expired or revoked."""


class CanvasUnavailable(CanvasError):
    """Throttled, server errors or network failures that outlasted the retries."""


class CanvasProtocolError(CanvasError):
    """An unexpected response: other 4xx, a redirect, or bad pagination."""


@dataclass(frozen=True, slots=True)
class EtagResult:
    not_modified: bool
    data: list[Any]
    etag: str | None
    pages: int = 1  # an ETag only describes the first page, so it is only safe when this is 1


class CanvasClient:
    def __init__(
        self,
        base_url: str,
        token: Callable[[], str],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = random.random,
        max_retries: int = 4,
    ) -> None:
        self._base = base_url.rstrip("/")
        origin = urlsplit(self._base)
        self._origin = (origin.scheme, origin.netloc)
        self._token = token
        self._sleep = sleep
        self._rand = rand
        self._max_retries = max_retries
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            transport=transport, follow_redirects=False, timeout=httpx.Timeout(20.0)
        )

    async def get_json(self, path: str, params: Params | None = None) -> Any:
        return self._json(await self._get(self._url(path), params))

    async def get_all(self, path: str, params: Params | None = None) -> list[Any]:
        items, _pages = await self._collect(await self._get(self._url(path), params))
        return items

    async def get_all_if_changed(
        self, path: str, params: Params | None, etag: str | None
    ) -> EtagResult:
        headers = {"If-None-Match": etag} if etag else None
        first = await self._get(self._url(path), params, headers)
        if first.status_code == 304:
            return EtagResult(not_modified=True, data=[], etag=etag)
        items, pages = await self._collect(first)
        return EtagResult(
            not_modified=False, data=items, etag=first.headers.get("ETag"), pages=pages
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- internals -------------------------------------------------------------

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:  # e.g. a captive portal or maintenance page
            raise CanvasProtocolError("Canvas sent a response that isn't JSON") from None

    def _url(self, path: str) -> str:
        if not path.startswith(API_PREFIX):
            raise ValueError(f"only {API_PREFIX} paths may be requested")
        return f"{self._base}{path}"

    async def _collect(self, response: httpx.Response) -> tuple[list[Any], int]:
        items: list[Any] = []
        pages = 0
        while True:
            pages += 1
            page = self._json(response)
            if not isinstance(page, list):
                raise CanvasProtocolError("expected a JSON list from a paginated endpoint")
            items.extend(page)
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return items, pages
            parts = urlsplit(next_url)
            if (parts.scheme, parts.netloc) != self._origin or not parts.path.startswith(
                API_PREFIX
            ):
                raise CanvasProtocolError("cross-host pagination refused")
            response = await self._get(next_url, None)

    def _backoff(self, attempt: int) -> float:
        return self._rand() * min(60.0, 2.0 * 2.0**attempt)

    @staticmethod
    def _throttled(response: httpx.Response) -> bool:
        if response.status_code == 429:
            return True
        return response.status_code == 403 and "Rate Limit Exceeded" in response.text

    async def _get(
        self, url: str, params: Params | None, headers: Mapping[str, str] | None = None
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            last_try = attempt == self._max_retries
            try:
                token = self._token()
            except OSError:
                raise CanvasAuthError("could not read the Canvas access token") from None
            request_headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                **(headers or {}),
            }
            try:
                async with self._lock:
                    response = await self._http.get(url, params=params, headers=request_headers)
            except httpx.TransportError:
                if last_try:
                    raise CanvasUnavailable("network error talking to Canvas") from None
                await self._sleep(self._backoff(attempt))
                continue
            status = response.status_code
            if status == 401:
                raise CanvasAuthError("Canvas rejected the access token (401)")
            if self._throttled(response) or status >= 500:
                if last_try:
                    raise CanvasUnavailable(f"Canvas unavailable (HTTP {status})")
                await self._sleep(self._backoff(attempt))
                continue
            if status == 304:
                return response
            if 300 <= status < 400:
                raise CanvasProtocolError("redirect refused")
            if status >= 400:
                raise CanvasProtocolError(f"unexpected Canvas response (HTTP {status})")
            return response
        raise AssertionError("unreachable")
