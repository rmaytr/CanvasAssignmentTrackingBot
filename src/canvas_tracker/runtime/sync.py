"""Pull Canvas into the store on a cadence, recording success and failure state (PRD §7.1).

The store is called synchronously from the event loop: every operation is
sub-millisecond for one user, and keeping the sqlite connection on one thread
avoids cross-thread connection problems.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import StrEnum

from canvas_tracker.sources.canvas_client import (
    CanvasAuthError,
    CanvasClient,
    CanvasError,
    CanvasUnavailable,
)
from canvas_tracker.sources.enrichment import fetch_enrichment
from canvas_tracker.sources.planner import fetch_planner
from canvas_tracker.store.repo import (
    AUTH_FAILED_SINCE,
    LAST_ENRICHMENT_AT,
    LAST_SUCCESSFUL_SYNC_AT,
    LAST_SYNC_ATTEMPT_AT,
    LAST_SYNC_ERROR,
    PLANNER_ETAG,
    Store,
)

log = logging.getLogger(__name__)

SYNC_INTERVAL_AWAKE = timedelta(minutes=10)
SYNC_INTERVAL_QUIET = timedelta(minutes=30)
ENRICH_INTERVAL = timedelta(hours=12)


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


class SyncService:
    def __init__(self, client: CanvasClient, store: Store, base_url: str) -> None:
        self.client = client
        self.store = store
        self.base_url = base_url

    def _failed(self, now: datetime, exc: CanvasError) -> SyncOutcome:
        self.store.set_state(LAST_SYNC_ERROR, type(exc).__name__)
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
        self.store.set_state(LAST_SYNC_ERROR, None)

    async def sync(self, now: datetime) -> SyncOutcome:
        self.store.set_time(LAST_SYNC_ATTEMPT_AT, now)
        try:
            fetch = await fetch_planner(
                self.client, now, self.store.get_state(PLANNER_ETAG), self.base_url
            )
        except CanvasError as exc:
            return self._failed(now, exc)
        except Exception as exc:  # anything else must not take the tick down with it
            self.store.set_state(LAST_SYNC_ERROR, type(exc).__name__)
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
        try:
            enrichment = await fetch_enrichment(self.client)
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
