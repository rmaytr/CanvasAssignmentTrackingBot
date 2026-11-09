"""Pull Canvas into the store on a cadence, recording success and failure state (PRD §7.1).

The store is called synchronously from the event loop: every operation is
sub-millisecond for one user, and keeping the sqlite connection on one thread
avoids cross-thread connection problems.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from canvas_tracker.sources.canvas_client import (
    CanvasAuthError,
    CanvasClient,
    CanvasError,
    CanvasProtocolError,
    CanvasUnavailable,
)
from canvas_tracker.sources.enrichment import fetch_enrichment
from canvas_tracker.sources.feed import FeedClient, feed_items
from canvas_tracker.sources.planner import fetch_planner, planner_window
from canvas_tracker.store.repo import (
    AUTH_FAILED_SINCE,
    FEED_ETAG,
    FEED_LAST_MODIFIED,
    LAST_ENRICHMENT_AT,
    LAST_SUCCESSFUL_SYNC_AT,
    LAST_SYNC_ATTEMPT_AT,
    LAST_SYNC_ERROR,
    PLANNER_ETAG,
    SYNC_FAILING_SINCE,
    Store,
)

log = logging.getLogger(__name__)

SYNC_INTERVAL_AWAKE = timedelta(minutes=10)
SYNC_INTERVAL_QUIET = timedelta(minutes=30)
ENRICH_INTERVAL = timedelta(hours=12)
SYNC_TIMEOUT_S = 60.0  # bounds a hanging Canvas, so the tick and /sync stay responsive
ENRICH_TIMEOUT_S = 120.0


class CanvasHostRefused(CanvasUnavailable):
    """The Canvas host now resolves to a private address, so the bot won't call it."""


class SyncOutcome(StrEnum):
    OK = "ok"
    NOT_MODIFIED = "not_modified"
    AUTH_FAILED = "auth_failed"
    UNAVAILABLE = "unavailable"
    PROTOCOL_ERROR = "protocol_error"


def sync_due(now: datetime, last_attempt_at: datetime | None, quiet: bool) -> bool:
    if last_attempt_at is None:
        return True
    return now - last_attempt_at >= (SYNC_INTERVAL_QUIET if quiet else SYNC_INTERVAL_AWAKE)


def enrichment_due(
    now: datetime, last_enrichment_at: datetime | None, needs_enrichment: bool
) -> bool:
    return (
        needs_enrichment
        or last_enrichment_at is None
        or now - last_enrichment_at >= ENRICH_INTERVAL
    )


class SyncBase:
    """What every way of reading Canvas shares: success and failure bookkeeping in the
    user's store, and the host check before any request."""

    def __init__(
        self,
        store: Store,
        base_url: str,
        timeout_s: float | None = None,
        host_check: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.host_check = host_check
        self.store = store
        self.base_url = base_url
        self.sync_timeout_s = SYNC_TIMEOUT_S if timeout_s is None else timeout_s
        self.enrich_timeout_s = ENRICH_TIMEOUT_S if timeout_s is None else timeout_s

    async def sync(self, now: datetime) -> SyncOutcome:
        raise NotImplementedError

    async def enrich(self, now: datetime) -> SyncOutcome:
        raise NotImplementedError

    def _record_error(self, now: datetime, exc: BaseException) -> None:
        """Note the error, and when this run of failures started (kept until a sync
        works), so the owner's alert counts failing time, not time without syncs."""
        self.store.set_state(LAST_SYNC_ERROR, type(exc).__name__)
        if self.store.get_time(SYNC_FAILING_SINCE) is None:
            self.store.set_time(SYNC_FAILING_SINCE, now)

    def _failed(self, now: datetime, exc: CanvasError) -> SyncOutcome:
        self._record_error(now, exc)
        if isinstance(exc, CanvasAuthError):
            if self.store.get_time(AUTH_FAILED_SINCE) is None:
                self.store.set_time(AUTH_FAILED_SINCE, now)
            outcome = SyncOutcome.AUTH_FAILED
        elif isinstance(exc, CanvasUnavailable):
            outcome = SyncOutcome.UNAVAILABLE
        else:
            outcome = SyncOutcome.PROTOCOL_ERROR
        log.warning("canvas request failed", extra={"outcome": outcome.value})
        return outcome

    def _succeeded(self, now: datetime) -> None:
        self.store.set_time(LAST_SUCCESSFUL_SYNC_AT, now)
        self.store.set_time(AUTH_FAILED_SINCE, None)
        self.store.set_time(SYNC_FAILING_SINCE, None)
        self.store.set_state(LAST_SYNC_ERROR, None)

    async def _host_ok(self) -> bool:
        """The Canvas host still resolves only to public addresses (checked at sign-up and
        again here, so a later DNS change can't point the bot at this server)."""
        if self.host_check is None:
            return True
        try:
            return await self.host_check()
        except Exception:  # a broken check refuses rather than lets the request through
            log.exception("canvas host check failed")
            return False


class SyncService(SyncBase):
    """Reads the Canvas Planner API with the user's access token."""

    def __init__(
        self,
        client: CanvasClient,
        store: Store,
        base_url: str,
        timeout_s: float | None = None,
        host_check: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        super().__init__(store, base_url, timeout_s, host_check)
        self.client = client

    async def sync(self, now: datetime) -> SyncOutcome:
        self.store.set_time(LAST_SYNC_ATTEMPT_AT, now)
        if not await self._host_ok():
            return self._failed(now, CanvasHostRefused("Canvas host resolves privately"))
        try:
            async with asyncio.timeout(self.sync_timeout_s):
                fetch = await fetch_planner(
                    self.client, now, self.store.get_state(PLANNER_ETAG), self.base_url
                )
        except TimeoutError:
            return self._failed(now, CanvasUnavailable("Canvas timed out"))
        except CanvasError as exc:
            return self._failed(now, exc)
        except Exception as exc:  # anything else must not take the tick down with it
            self._record_error(now, exc)
            log.exception("planner sync failed")
            return SyncOutcome.PROTOCOL_ERROR
        if fetch.items is None:
            self._succeeded(now)
            return SyncOutcome.NOT_MODIFIED
        self.store.upsert_items(fetch.items, now)
        self.store.mark_gone(fetch.window, {item.ref for item in fetch.items}, now)
        # A 304 on page 1 says nothing about later pages, so only keep a single-page ETag.
        self.store.set_state(PLANNER_ETAG, fetch.etag if fetch.pages == 1 else None)
        self._succeeded(now)
        log.info("synced planner", extra={"items": len(fetch.items)})
        return SyncOutcome.OK

    async def enrich(self, now: datetime) -> SyncOutcome:
        if not await self._host_ok():
            return SyncOutcome.UNAVAILABLE
        try:
            async with asyncio.timeout(self.enrich_timeout_s):
                enrichment = await fetch_enrichment(self.client)
        except TimeoutError:
            log.warning("enrichment timed out")
            return SyncOutcome.UNAVAILABLE
        except CanvasError as exc:
            # Enrichment is best effort: its errors never set the auth or sync-error state,
            # which belong to the planner sync (a 401 here can just mean "not allowed").
            log.warning("enrichment failed", extra={"error": type(exc).__name__})
            if isinstance(exc, CanvasAuthError):
                return SyncOutcome.AUTH_FAILED
            if isinstance(exc, CanvasUnavailable):
                return SyncOutcome.UNAVAILABLE
            return SyncOutcome.PROTOCOL_ERROR
        except Exception:
            log.exception("enrichment failed")
            return SyncOutcome.PROTOCOL_ERROR
        self.store.apply_enrichment(enrichment)
        self.store.set_time(LAST_ENRICHMENT_AT, now)
        return SyncOutcome.OK


class FeedSync(SyncBase):
    """Reads the user's private calendar feed instead of the API (no token needed).

    Entries in the planner's window that the feed no longer lists are marked gone,
    as with the planner. The feed has no grade weights, so ``enrich`` only records
    that there is nothing to fetch."""

    def __init__(
        self,
        client: FeedClient,
        store: Store,
        base_url: str,
        zone: ZoneInfo,
        timeout_s: float | None = None,
        host_check: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        super().__init__(store, base_url, timeout_s, host_check)
        self.client = client
        self.zone = zone

    async def sync(self, now: datetime) -> SyncOutcome:
        self.store.set_time(LAST_SYNC_ATTEMPT_AT, now)
        if not await self._host_ok():
            return self._failed(now, CanvasHostRefused("Canvas host resolves privately"))
        etag = self.store.get_state(FEED_ETAG)
        modified = self.store.get_state(FEED_LAST_MODIFIED)
        try:
            async with asyncio.timeout(self.sync_timeout_s):
                response = await self.client.fetch(etag, modified)
            if response.not_modified:
                self._succeeded(now)
                return SyncOutcome.NOT_MODIFIED
            window = planner_window(now)
            try:  # parsing a big feed is CPU work: off the loop, so other users don't wait
                async with asyncio.timeout(self.sync_timeout_s):
                    items = await asyncio.to_thread(
                        feed_items, response.body, self.base_url, self.zone, window
                    )
            except ValueError:
                raise CanvasProtocolError("the calendar feed isn't iCalendar") from None
        except TimeoutError:
            return self._failed(now, CanvasUnavailable("Canvas timed out"))
        except CanvasError as exc:
            return self._failed(now, exc)
        except Exception as exc:  # anything else must not take the tick down with it
            self._record_error(now, exc)
            log.exception("feed sync failed")
            return SyncOutcome.PROTOCOL_ERROR
        self.store.upsert_items(items, now)
        self.store.mark_gone(window, {item.ref for item in items}, now)
        self.store.set_state(FEED_ETAG, response.etag)
        self.store.set_state(FEED_LAST_MODIFIED, response.last_modified)
        self._succeeded(now)
        log.info("synced calendar feed", extra={"items": len(items)})
        return SyncOutcome.OK

    async def enrich(self, now: datetime) -> SyncOutcome:
        self.store.set_time(LAST_ENRICHMENT_AT, now)
        return SyncOutcome.OK
