"""Read-only, host-pinned Canvas REST client (PRD §7.1, §10.2).

Only GET exists. Requests go one at a time, only to /api/v1/ paths on the
configured host; redirects and cross-host pagination are refused so the
token never leaves that host. Throttling and server errors are retried with
capped exponential backoff and full jitter.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import zlib
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
MAX_PAGE_BYTES = 10 * 1024 * 1024  # one page of JSON, after decompression
MAX_TOTAL_BYTES = 40 * 1024 * 1024  # all pages of one paginated request together
MAX_PAGES = 100
ERROR_BODY_BYTES = 64 * 1024  # of an error response, read only to spot throttling
# Bodies are decompressed by ``read_capped``, never by httpx, so the size cap holds
# while unpacking: httpx would unpack stacked encodings ("gzip, gzip") without a bound.
ACCEPT_ENCODING = "gzip"
_IDENTITY = {"", "identity"}
_GZIP = {"gzip", "x-gzip"}


class CanvasError(Exception):
    """Base class. Messages never include tokens, URLs with secrets, or response bodies."""


class CanvasAuthError(CanvasError):
    """401. ``challenged`` is True when Canvas sent ``WWW-Authenticate``, which marks an
    invalid, expired or revoked token; without it a 401 can just mean "not allowed here"."""

    def __init__(self, message: str, challenged: bool = True) -> None:
        super().__init__(message)
        self.challenged = challenged


class CanvasUnavailable(CanvasError):
    """Throttled, server errors or network failures that outlasted the retries."""


class CanvasProtocolError(CanvasError):
    """An unexpected response: other 4xx, a redirect, or bad pagination."""


class ResponseTooLarge(CanvasProtocolError):
    """A response body is larger than the limit (counted after decompression)."""


async def read_capped(
    response: httpx.Response,
    limit: int,
    too_large: type[CanvasProtocolError] = ResponseTooLarge,
) -> bytes:
    """A streamed response's body, unpacked by hand so that no more than ``limit``
    bytes are ever held: a declared, streamed or decompressed size over the limit
    raises ``too_large``. Only identity and a single gzip layer are accepted."""
    encoding = response.headers.get("Content-Encoding", "").strip().lower()
    if encoding not in _IDENTITY and encoding not in _GZIP:
        raise CanvasProtocolError("unsupported response encoding")
    length = response.headers.get("Content-Length", "").strip()
    if length.isdigit() and int(length) > limit:
        raise too_large("the response is too large")
    unpack = zlib.decompressobj(wbits=31) if encoding in _GZIP else None
    chunks: list[bytes] = []
    total = 0

    def keep(data: bytes) -> None:
        nonlocal total
        total += len(data)
        if total > limit:
            raise too_large("the response is too large")
        chunks.append(data)

    try:
        async for raw in response.aiter_raw():
            if unpack is None:
                keep(raw)
                continue
            pending = raw
            while pending and not unpack.eof:
                keep(unpack.decompress(pending, limit - total + 1))
                pending = unpack.unconsumed_tail
        if unpack is not None:
            if not unpack.eof:
                raise CanvasProtocolError("the response's compression is cut short")
            keep(unpack.flush())
    except zlib.error:
        raise CanvasProtocolError("the response's compression is broken") from None
    except httpx.StreamConsumed:  # read in full before it got here (test transports do)
        chunks.clear()
        total = 0
        keep(response.content)
    return b"".join(chunks)


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
        max_page_bytes: int = MAX_PAGE_BYTES,
        max_total_bytes: int = MAX_TOTAL_BYTES,
    ) -> None:
        self._base = base_url.rstrip("/")
        origin = urlsplit(self._base)
        self._origin = (origin.scheme, origin.netloc)
        self._token = token
        self._sleep = sleep
        self._rand = rand
        self._max_retries = max_retries
        self._max_page_bytes = max_page_bytes
        self._max_total_bytes = max_total_bytes
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
        except (ValueError, RecursionError):  # e.g. a captive portal or maintenance page
            raise CanvasProtocolError("Canvas sent a response that isn't JSON") from None

    def _url(self, path: str) -> str:
        if not path.startswith(API_PREFIX):
            raise ValueError(f"only {API_PREFIX} paths may be requested")
        return f"{self._base}{path}"

    async def _collect(self, response: httpx.Response) -> tuple[list[Any], int]:
        items: list[Any] = []
        pages = 0
        total = 0
        while True:
            pages += 1
            total += len(response.content)
            if total > self._max_total_bytes:
                raise ResponseTooLarge("Canvas sent more than the bot reads at once")
            page = self._json(response)
            if not isinstance(page, list):
                raise CanvasProtocolError("expected a JSON list from a paginated endpoint")
            items.extend(page)
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return items, pages
            if pages >= MAX_PAGES:
                raise CanvasProtocolError("too many pages")
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

    async def _fetch(
        self, url: str, params: Params | None, headers: Mapping[str, str]
    ) -> httpx.Response:
        """GET ``url`` and read its body through ``read_capped``. The returned response
        holds the unpacked body, without the encoding headers that described the wire."""
        async with self._http.stream("GET", url, params=params, headers=headers) as streamed:
            status = streamed.status_code
            body = b""
            if 200 <= status < 300:
                body = await read_capped(streamed, self._max_page_bytes)
            elif status >= 400:  # only read to spot throttling; a bad body can't hide the status
                with contextlib.suppress(CanvasProtocolError):
                    body = await read_capped(streamed, ERROR_BODY_BYTES)
            kept = [
                (name, value)
                for name, value in streamed.headers.multi_items()
                if name.lower() not in ("content-encoding", "content-length", "transfer-encoding")
            ]
            return httpx.Response(
                streamed.status_code, headers=kept, content=body, request=streamed.request
            )

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
                "Accept-Encoding": ACCEPT_ENCODING,
                **(headers or {}),
            }
            try:
                async with self._lock:
                    response = await self._fetch(url, params, request_headers)
            except httpx.TransportError:
                if last_try:
                    raise CanvasUnavailable("network error talking to Canvas") from None
                await self._sleep(self._backoff(attempt))
                continue
            except (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError):
                raise CanvasProtocolError("unexpected response from Canvas") from None
            status = response.status_code
            if status == 401:
                raise CanvasAuthError(
                    "Canvas rejected the request (401)",
                    challenged="WWW-Authenticate" in response.headers,
                )
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
