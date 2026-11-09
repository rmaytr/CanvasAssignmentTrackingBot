"""Watching the server for the owner: alerts, /health and an hourly summary log line.

The owner hears about four things over Telegram: a user whose Canvas sync keeps
failing for a reason other than a rejected token, emails that keep failing, a data
volume that is nearly full, and a user's tick that has been running too long. Each
alert goes out at most once per 24 h per condition, and a short "resolved" note
follows when it clears.

Nothing here reads anyone's assignments, tokens or addresses: the hub hands over
each user's name, Telegram ID and a few sync timestamps (``Watched``), and only
those, counts and sizes ever reach a message or the log. The clock and the disk
check are injected, so everything can be tested without a real disk or time.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from canvas_tracker.domain.models import SendKind
from canvas_tracker.hub.registry import Registry
from canvas_tracker.notify.base import Notifier, NotifyError
from canvas_tracker.render import copy
from canvas_tracker.render.format import escape, format_bytes
from canvas_tracker.render.message import RenderedMessage
from canvas_tracker.store.repo import from_db, to_db

log = logging.getLogger(__name__)

SYNC_FAILING_AFTER = timedelta(hours=6)
STUCK_AFTER = timedelta(minutes=10)
DISK_CHECK_EVERY = timedelta(minutes=10)
DISK_MIN_FREE_BYTES = 200 * 1024 * 1024
DISK_MIN_FREE_FRACTION = 0.05
EMAIL_FAILURES_TO_ALERT = 3
ALERT_REPEAT = timedelta(hours=24)
SUMMARY_EVERY = timedelta(hours=1)
ALERTS_STATE_KEY = "monitor_alerts"  # registry state, so a restart doesn't repeat alerts

# The non-auth sync errors (``LAST_SYNC_ERROR`` holds the exception's class name).
_REASONS = {
    "CanvasHostRefused": copy.MONITOR_REASON_HOST,
    "CanvasUnavailable": copy.MONITOR_REASON_UNREACHABLE,
    "CanvasProtocolError": copy.MONITOR_REASON_PROTOCOL,
    "FeedTooLarge": copy.MONITOR_REASON_FEED_TOO_LARGE,
}


class DiskUsage(Protocol):
    @property
    def total(self) -> int: ...

    @property
    def free(self) -> int: ...


DiskCheck = Callable[[Path], DiskUsage]


@dataclass(frozen=True, slots=True)
class Watched:
    """What the monitor may know about one active user: who, and how their sync is going."""

    telegram_id: int
    name: str
    last_ok: datetime | None = None
    last_error: str | None = None
    auth_failed: bool = False
    tick_started_at: datetime | None = None  # set only while a tick is running
    failing_since: datetime | None = None  # the first failed sync since the last good one


@dataclass(frozen=True, slots=True)
class AlertState:
    alerted_at: datetime | None = None
    active: bool = False  # the owner was told and hasn't been told it's resolved


Action = Literal["alert", "resolved"]


def decide(now: datetime, failing: bool, state: AlertState) -> tuple[Action | None, AlertState]:
    """Alert when a condition starts (and again every 24 h while it lasts), but never
    more than once per 24 h, even if it flaps; say "resolved" once when it clears."""
    if failing:
        if state.alerted_at is None or now - state.alerted_at >= ALERT_REPEAT:
            return "alert", AlertState(alerted_at=now, active=True)
        return None, state
    if state.active:
        return "resolved", AlertState(alerted_at=state.alerted_at, active=False)
    return None, state


def is_sync_problem(user: Watched) -> bool:
    """Any sync trouble right now: a rejected token or a failing request."""
    return user.auth_failed or user.last_error is not None


def failing_since(user: Watched, first_seen: datetime | None) -> datetime | None:
    """Since when a non-auth sync error has lasted: from the first failed sync since the
    last good one (not from the last good sync: time the server was down, or the user
    wasn't syncing at all, isn't failing time), or, when that wasn't recorded (data from
    an older version), from when the monitor first saw it. None if not failing."""
    if user.auth_failed or user.last_error is None:
        return None
    return user.failing_since if user.failing_since is not None else first_seen


def disk_low(usage: DiskUsage) -> bool:
    if usage.total <= 0:
        return False
    return usage.free < DISK_MIN_FREE_BYTES or usage.free / usage.total < DISK_MIN_FREE_FRACTION


def disk_label(usage: DiskUsage | None) -> str:
    if usage is None:
        return copy.HEALTH_UNKNOWN
    percent = 0 if usage.total <= 0 else round(100 * usage.free / usage.total)
    text = copy.HEALTH_DISK.format(
        free=format_bytes(usage.free), total=format_bytes(usage.total), percent=percent
    )
    return text + (copy.HEALTH_DISK_LOW if disk_low(usage) else "")


def _label(user: Watched) -> dict[str, object]:
    return {"name": escape(user.name or "?"), "telegram_id": user.telegram_id}


@dataclass(frozen=True, slots=True)
class HealthReport:
    started_at: datetime
    users_active: int
    users_onboarding: int
    users_broken: int
    last_tick: datetime | None
    disk: DiskUsage | None
    email_configured: bool
    email_failures: int
    sync_problems: int
    auth_problems: int
    stuck: int
    open_alerts: int


class WatchedMailer:
    """Passes every email through and tells the monitor whether it went out."""

    def __init__(self, inner: Notifier, record: Callable[[bool], None]) -> None:
        self.inner = inner
        self.record = record

    async def send(self, msg: RenderedMessage) -> int | None:
        try:
            result = await self.inner.send(msg)
        except NotifyError:
            self.record(False)
            raise
        self.record(True)
        return result


@dataclass
class _Counts:
    sends: Counter[str] = field(default_factory=Counter)
    failures: Counter[str] = field(default_factory=Counter)


class Monitor:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        registry: Registry,
        data_dir: Path,
        disk_usage: DiskCheck = shutil.disk_usage,
    ) -> None:
        self.clock = clock
        self.registry = registry
        self.data_dir = data_dir
        self.disk_usage = disk_usage
        self.started_at = clock()
        self.email_failures = 0  # in a row; any delivered email resets it
        self._counts = _Counts()
        self._last_summary = self.started_at
        self._disk: DiskUsage | None = None
        self._disk_at: datetime | None = None
        self._first_failure: dict[int, datetime] = {}
        self._alerts = self._load()

    # --- what the bot reports in -------------------------------------------------

    def record_send(self, kind: SendKind, ok: bool) -> None:
        (self._counts.sends if ok else self._counts.failures)[kind.value] += 1

    def record_email(self, ok: bool) -> None:
        self.email_failures = 0 if ok else self.email_failures + 1

    # --- persisted alert state ---------------------------------------------------

    def _load(self) -> dict[str, AlertState]:
        raw = self.registry.get_state(ALERTS_STATE_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return {
                str(key): AlertState(from_db(value.get("at")), bool(value.get("active")))
                for key, value in data.items()
                if isinstance(value, dict)
            }
        except (ValueError, TypeError, AttributeError):
            log.warning("monitor alert state unreadable; starting fresh")
            return {}

    def _save(self, now: datetime) -> None:
        # A resolved alert is only kept while it still holds back a repeat (24 h).
        self._alerts = {
            key: state
            for key, state in self._alerts.items()
            if state.alerted_at is not None
            and (state.active or now - state.alerted_at < ALERT_REPEAT)
        }
        data = {
            key: {"at": to_db(state.alerted_at), "active": state.active}
            for key, state in self._alerts.items()
        }
        self.registry.set_state(ALERTS_STATE_KEY, json.dumps(data, sort_keys=True))

    # --- checks ------------------------------------------------------------------

    def disk(self, *, fresh: bool = False) -> DiskUsage | None:
        """The data volume's usage, read at most every 10 minutes (unless ``fresh``)."""
        now = self.clock()
        if (
            not fresh
            and self._disk_at is not None
            and timedelta(0) <= now - self._disk_at < DISK_CHECK_EVERY
        ):
            return self._disk
        self._disk_at = now
        try:
            self._disk = self.disk_usage(self.data_dir)
        except OSError:
            log.warning("disk usage check failed")
            self._disk = None
        return self._disk

    def _conditions(self, now: datetime, users: Sequence[Watched]) -> dict[str, tuple[bool, str]]:
        """Every condition the monitor knows of: key → (failing, alert or resolved text)."""
        found: dict[str, tuple[bool, str]] = {}
        for user in users:
            if user.auth_failed or user.last_error is None:
                self._first_failure.pop(user.telegram_id, None)
            else:
                self._first_failure.setdefault(user.telegram_id, now)
            since = failing_since(user, self._first_failure.get(user.telegram_id))
            failing = since is not None and now - since >= SYNC_FAILING_AFTER
            key = f"sync:{user.telegram_id}"
            if failing and since is not None:
                hours = int((now - since).total_seconds() // 3600)
                reason = _REASONS.get(user.last_error or "", copy.MONITOR_REASON_OTHER)
                text = copy.MONITOR_SYNC_FAILING.format(hours=hours, reason=reason, **_label(user))
            else:
                text = copy.MONITOR_SYNC_RESOLVED.format(**_label(user))
            found[key] = (failing, text)

            started = user.tick_started_at
            stuck = started is not None and now - started >= STUCK_AFTER
            if stuck and started is not None:
                minutes = int((now - started).total_seconds() // 60)
                text = copy.MONITOR_STUCK.format(minutes=minutes, **_label(user))
            else:
                text = copy.MONITOR_STUCK_RESOLVED.format(**_label(user))
            found[f"stuck:{user.telegram_id}"] = (stuck, text)
        present = {user.telegram_id for user in users}
        for telegram_id in list(self._first_failure):
            if telegram_id not in present:
                del self._first_failure[telegram_id]

        email_failing = self.email_failures >= EMAIL_FAILURES_TO_ALERT
        found["email"] = (
            email_failing,
            copy.MONITOR_EMAIL_FAILING.format(count=self.email_failures)
            if email_failing
            else copy.MONITOR_EMAIL_RESOLVED,
        )

        usage = self.disk()
        if usage is not None:
            low = disk_low(usage)
            values = {"free": format_bytes(usage.free), "total": format_bytes(usage.total)}
            text = copy.MONITOR_DISK_LOW if low else copy.MONITOR_DISK_RESOLVED
            found["disk"] = (low, text.format(**values))
        return found

    async def check(
        self, users: Sequence[Watched], tell: Callable[[str], Awaitable[bool]]
    ) -> list[str]:
        """Look at everything once and tell the owner what started or cleared. ``tell``
        returns whether the message reached them; an undelivered alert is tried again
        on the next check. Returns the messages delivered."""
        now = self.clock()
        delivered: list[str] = []
        conditions = self._conditions(now, users)
        changed = False
        for key in list(self._alerts):
            if key not in conditions and self._gone(key):  # they left: nothing to resolve
                del self._alerts[key]
                changed = True
        for key, (failing, text) in conditions.items():
            state = self._alerts.get(key, AlertState())
            action, new_state = decide(now, failing, state)
            if action is None:
                continue
            if not await tell(text):
                continue
            delivered.append(text)
            self._alerts[key] = new_state
            changed = True
            log.warning("owner alert", extra={"alert": key.split(":")[0], "action": action})
        if changed:
            self._save(now)
        return delivered

    def _gone(self, key: str) -> bool:
        """A user's alert whose user is no longer signed up. A user who is only missing
        for a moment (their tenant being rebuilt) keeps theirs, so it isn't repeated;
        the disk alert stays while the disk can't be read."""
        _kind, _, telegram_id = key.partition(":")
        if not telegram_id.lstrip("-").isdigit():
            return False
        user = self.registry.get_user(int(telegram_id))
        return user is None or user.status != "active"

    @property
    def open_alerts(self) -> int:
        return sum(1 for state in self._alerts.values() if state.active)

    # --- the hourly log line -----------------------------------------------------

    def summary_due(self) -> bool:
        return self.clock() - self._last_summary >= SUMMARY_EVERY

    def summarize(self, users: Sequence[Watched], *, onboarding: int) -> dict[str, object]:
        """One log line of counts for ``docker compose logs``; resets the send counters.
        Nobody's name or ID is in it."""
        now = self.clock()
        usage = self._disk
        fields: dict[str, object] = {
            "users_active": len(users),
            "users_signing_up": onboarding,
            "sends": dict(sorted(self._counts.sends.items())),
            "send_failures": dict(sorted(self._counts.failures.items())),
            "sync_problems": sum(1 for user in users if is_sync_problem(user)),
            "email_failures_in_a_row": self.email_failures,
            "open_alerts": self.open_alerts,
            "disk_free_mb": None if usage is None else usage.free // (1024 * 1024),
            "period_minutes": max(0, math.floor((now - self._last_summary).total_seconds() / 60)),
        }
        self._counts = _Counts()
        self._last_summary = now
        log.info("hourly summary", extra=fields)
        return fields

    # --- /health -----------------------------------------------------------------

    def report(
        self,
        users: Sequence[Watched],
        *,
        onboarding: int,
        broken: int,
        last_tick: datetime | None,
        email_configured: bool,
    ) -> HealthReport:
        now = self.clock()
        return HealthReport(
            started_at=self.started_at,
            users_active=len(users),
            users_onboarding=onboarding,
            users_broken=broken,
            last_tick=last_tick,
            disk=self.disk(fresh=True),
            email_configured=email_configured,
            email_failures=self.email_failures,
            sync_problems=sum(1 for user in users if is_sync_problem(user)),
            auth_problems=sum(1 for user in users if user.auth_failed),
            stuck=sum(
                1
                for user in users
                if user.tick_started_at is not None and now - user.tick_started_at >= STUCK_AFTER
            ),
            open_alerts=self.open_alerts,
        )
