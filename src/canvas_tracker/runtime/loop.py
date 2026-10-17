"""The tick loop: sync when due, plan, freshen, claim, send (PRD §9.3)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from canvas_tracker.domain.models import FRESHNESS, Settings
from canvas_tracker.notify.base import Notifier, NotifyError
from canvas_tracker.planning.plan import plan
from canvas_tracker.planning.timeutil import in_quiet
from canvas_tracker.render.alerts import render_send
from canvas_tracker.runtime.sync import SyncOutcome, enrichment_due, sync_due
from canvas_tracker.store.repo import (
    AUTH_FAILED_SINCE,
    LAST_ENRICHMENT_AT,
    LAST_PURGE_AT,
    LAST_SUCCESSFUL_SYNC_AT,
    LAST_SYNC_ATTEMPT_AT,
    LAST_TICK_AT,
    Store,
)

log = logging.getLogger(__name__)

AUTH_RECHECK = timedelta(hours=6)
PURGE_EVERY = timedelta(hours=24)
PRESEND_SYNC_TIMEOUT_S = 30.0


class SyncLike(Protocol):
    async def sync(self, now: datetime) -> SyncOutcome: ...

    async def enrich(self, now: datetime) -> SyncOutcome: ...


class Runtime:
    def __init__(
        self,
        *,
        store: Store,
        sync: SyncLike,
        notifier: Notifier,
        settings: Settings,
        clock: Callable[[], datetime],
        can_send: Callable[[], bool],
        token: Callable[[], str],
        hidden_courses: frozenset[str] = frozenset(),
        item_retention: timedelta = timedelta(days=30),
    ) -> None:
        self.store = store
        self.sync = sync
        self.notifier = notifier
        self.settings = settings
        self.clock = clock
        self.can_send = can_send
        self.token = token
        self.hidden_courses = hidden_courses
        self.item_retention = item_retention
        self._failed_token_digest: str | None = None  # never the token itself

    def _token_digest(self) -> str:
        try:
            return hashlib.sha256(self.token().encode()).hexdigest()
        except OSError:
            return ""

    def _should_sync(self, now: datetime) -> bool:
        s = self.settings
        last_attempt = self.store.get_time(LAST_SYNC_ATTEMPT_AT)
        if not sync_due(now, last_attempt, in_quiet(now, s.zone, s.quiet_start, s.quiet_end)):
            return False
        if self.store.get_time(AUTH_FAILED_SINCE) is None:
            return True
        if self._token_digest() != self._failed_token_digest:
            return True  # the token was replaced: try it now
        return last_attempt is None or now - last_attempt >= AUTH_RECHECK

    async def _sync(self, now: datetime) -> None:
        try:
            outcome = await self.sync.sync(now)
        except Exception:  # planning and sending must go on with the data we have
            log.exception("sync crashed")
            return
        if outcome is SyncOutcome.AUTH_FAILED:
            self._failed_token_digest = self._token_digest()
        elif outcome in (SyncOutcome.OK, SyncOutcome.NOT_MODIFIED) and enrichment_due(
            now, self.store.get_time(LAST_ENRICHMENT_AT), self.store.needs_enrichment()
        ):
            try:
                await self.sync.enrich(now)
            except Exception:
                log.exception("enrichment crashed")

    async def tick(self) -> None:
        now = self.clock()
        if self._should_sync(now):
            await self._sync(now)
        snap = self.store.snapshot(self.hidden_courses)
        result = plan(now, snap, self.settings)
        last_ok = self.store.get_time(LAST_SUCCESSFUL_SYNC_AT)
        stale = last_ok is None or now - last_ok > FRESHNESS
        if result.sends and stale and self.store.get_time(AUTH_FAILED_SINCE) is None:
            try:
                async with asyncio.timeout(PRESEND_SYNC_TIMEOUT_S):
                    await self._sync(now)  # never nag from stale data if Canvas can tell us more
            except TimeoutError:
                log.warning("pre-send sync timed out")
            snap = self.store.snapshot(self.hidden_courses)
            result = plan(now, snap, self.settings)

        if result.open_cycle_at is not None:
            self.store.open_cycle(result.open_cycle_at)
        if result.close_cycle:
            self.store.close_cycle(now)

        if self.can_send():
            for send in result.sends:
                if not self.store.claim(send.key, send.kind, send.item_refs, now):
                    continue
                messages = render_send(send, snap, now, self.settings)
                try:
                    first_id: int | None = None
                    for message in messages:
                        message_id = await self.notifier.send(message)
                        first_id = message_id if first_id is None else first_id
                except NotifyError as exc:
                    self.store.mark_failed(send.key, str(exc) or type(exc).__name__)
                    log.warning("send failed", extra={"kind": send.kind.value})
                else:
                    self.store.mark_sent(send.key, now, first_id)
                    log.info("sent", extra={"kind": send.kind.value, "items": len(send.item_refs)})

        self.store.set_time(LAST_TICK_AT, now)
        last_purge = self.store.get_time(LAST_PURGE_AT)
        if last_purge is None or now - last_purge >= PURGE_EVERY:
            self.store.purge(now, self.item_retention)
            self.store.set_time(LAST_PURGE_AT, now)

    async def run_forever(self, interval_s: float = 60.0) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")  # logged through the redaction filter
            await asyncio.sleep(interval_s)
