"""One user's slice of the bot: their own database file, Canvas client, sync and tick loop.

Each user gets the same single-user machinery the bot always had (Store,
SyncService, Runtime), pointed at a file only they use. Nothing here can read
another user's data.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from canvas_tracker.bot.deps import BotDeps
from canvas_tracker.domain.models import MIN_REMINDER_INTERVAL, SendKind, Settings
from canvas_tracker.hub.parsing import quiet_window
from canvas_tracker.hub.registry import Registry, User
from canvas_tracker.hub.secretbox import SecretBox
from canvas_tracker.notify.base import Notifier
from canvas_tracker.runtime.logging import register_secret
from canvas_tracker.runtime.loop import Runtime
from canvas_tracker.runtime.sync import FeedSync, SyncBase, SyncService
from canvas_tracker.sources.canvas_client import CanvasClient
from canvas_tracker.sources.feed import FeedClient
from canvas_tracker.store.db import connect, migrate
from canvas_tracker.store.repo import Store

log = logging.getLogger(__name__)

DEFAULT_DIGEST = time(8, 0)
DIGEST_GRACE = timedelta(hours=4)
ClientFactory = Callable[[str, Callable[[], str]], CanvasClient]
FeedClientFactory = Callable[[str, Callable[[], str]], FeedClient]  # (Canvas base, feed link)
MailerFactory = Callable[[Callable[[], str | None]], Notifier]


def digest_grace_until(digest: time) -> time:
    """The morning list may still go out up to 4 h late (e.g. after an outage), same day."""
    minutes = digest.hour * 60 + digest.minute + int(DIGEST_GRACE.total_seconds() // 60)
    if minutes >= 24 * 60:
        return time(23, 59)
    return time(minutes // 60, minutes % 60)


def bot_defaults(shared: Mapping[str, object]) -> Settings:
    """The bot-wide reminder rhythm (from the environment), as a Settings value."""
    return Settings(tz="UTC", **shared)  # type: ignore[arg-type]


def rhythm(user: User) -> dict[str, object]:
    """The parts of the reminder rhythm this user chose; the rest stays the bot default.
    A value the bot could never have stored is ignored rather than locking the user out."""
    chosen: dict[str, object] = {}
    minutes = user.reminder_interval_minutes
    if minutes == 0:
        chosen["reminder_interval"] = None
    elif minutes is not None and timedelta(minutes=minutes) >= MIN_REMINDER_INTERVAL:
        chosen["reminder_interval"] = timedelta(minutes=minutes)
    if user.reminder_window_hours is not None and user.reminder_window_hours > 0:
        chosen["reminder_window"] = timedelta(hours=user.reminder_window_hours)
    if user.digest_lookahead_days is not None and user.digest_lookahead_days > 0:
        chosen["digest_lookahead"] = timedelta(days=user.digest_lookahead_days)
    return chosen


def user_settings(user: User, shared: Mapping[str, object], *, email: bool = False) -> Settings:
    if user.tz is None or user.canvas_base_url is None:
        raise ValueError("user hasn't finished signing up")
    digest = user.digest_time or DEFAULT_DIGEST
    quiet = quiet_window(user.quiet)
    start, end = (None, None) if quiet is None else quiet
    values = {**shared, **rhythm(user)}
    return Settings(
        tz=user.tz,
        digest_time=digest,
        digest_grace_until=digest_grace_until(digest),
        quiet_start=start,
        quiet_end=end,
        canvas_host=urlsplit(user.canvas_base_url).hostname or "",
        email=email,
        calendar_feed=user.feed_mode,
        **values,  # type: ignore[arg-type]
    )


def user_db_path(data_dir: Path, telegram_id: int) -> Path:
    return data_dir / "users" / f"{telegram_id}.db"


def default_feed_client(base_url: str, url: Callable[[], str]) -> FeedClient:
    return FeedClient(url, host=urlsplit(base_url).hostname)


class Tenant:
    def __init__(
        self,
        user: User,
        *,
        registry: Registry,
        box: SecretBox,
        data_dir: Path,
        shared: Mapping[str, object],
        notifier: Notifier,
        clock: Callable[[], datetime],
        client_factory: ClientFactory,
        item_retention: timedelta,
        mailer_factory: MailerFactory | None = None,
        host_check: Callable[[], Awaitable[bool]] | None = None,
        sync_wait: Callable[[], timedelta | None] | None = None,
        on_send: Callable[[SendKind, bool], None] | None = None,
        feed_client_factory: FeedClientFactory = default_feed_client,
    ) -> None:
        assert user.canvas_base_url is not None  # noqa: S101 - only active users get a tenant
        self.telegram_id = user.telegram_id
        path = user_db_path(data_dir, user.telegram_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(path)
        migrate(conn)
        self.store = Store(conn)
        self.store.use_source(user.mode)
        default_interval = bot_defaults(shared).reminder_interval
        if default_interval is not None:  # cycles from before intervals were per user
            self.store.fill_cycle_interval(default_interval)
        telegram_id = user.telegram_id
        email = mailer_factory is not None and user.email_sealed is not None
        self.settings = user_settings(user, shared, email=email)

        def address() -> str | None:
            current = registry.get_user(telegram_id)
            if current is None or current.email_sealed is None:
                return None
            try:
                return box.open(current.email_sealed)
            except ValueError:
                return None

        mailer = mailer_factory(address) if email and mailer_factory is not None else None

        def secret(field: str) -> Callable[[], str]:
            """Reads the user's token or feed link from the registry each time it's needed,
            so a replaced one is used at once and it isn't kept decrypted in memory."""

            def read() -> str:
                current = registry.get_user(telegram_id)
                sealed = None if current is None else getattr(current, field)
                if sealed is None:
                    raise OSError("nothing stored")  # the clients report this as an auth error
                try:
                    value = box.open(sealed)
                except ValueError:
                    raise OSError("can't be decrypted") from None
                register_secret(value)
                return value

            return read

        self.client: CanvasClient | FeedClient
        self.sync: SyncBase
        if user.feed_mode:
            token = secret("feed_sealed")  # a new link counts as a new "token" for rechecks
            self.client = feed_client_factory(user.canvas_base_url, token)
            self.sync = FeedSync(
                self.client,
                self.store,
                user.canvas_base_url,
                zone=self.settings.zone,
                host_check=host_check,
            )
        else:
            token = secret("token_sealed")
            self.client = client_factory(user.canvas_base_url, token)
            self.sync = SyncService(
                self.client, self.store, user.canvas_base_url, host_check=host_check
            )
        self.runtime = Runtime(
            store=self.store,
            sync=self.sync,
            notifier=notifier,
            settings=self.settings,
            clock=clock,
            can_send=lambda: True,
            token=token,
            item_retention=item_retention,
            mailer=mailer,
            on_send=on_send,
        )
        self.deps = BotDeps(
            store=self.store,
            settings=self.settings,
            clock=clock,
            sync=self.sync,
            sync_wait=sync_wait or (lambda: None),
            email_available=mailer_factory is not None,
            email_address=address,
        )
        self._clock = clock
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self.tick_started_at: datetime | None = None
        self.closed = False

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def running(self) -> asyncio.Task[None] | None:
        return self._task if self.busy else None

    @property
    def running_since(self) -> datetime | None:
        """When the tick that is still running started (None when none is)."""
        return self.tick_started_at if self.busy else None

    def start_tick(self) -> asyncio.Task[None] | None:
        """Run one tick in the background, unless the previous one is still going."""
        if self.closed or self.busy:
            return None
        self.tick_started_at = self._clock()
        self._task = asyncio.create_task(self.tick())
        return self._task

    async def tick(self) -> None:
        async with self._lock:
            if self.closed:
                return
            try:
                await self.runtime.tick()
            except Exception:  # one user's failure must never reach anyone else's tick
                log.exception("tick failed", extra={"user": self.telegram_id})

    async def close(self) -> None:
        """Stop a running tick (it may be stuck on a slow Canvas) and release the files."""
        if self.closed:
            return
        self.closed = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        async with self._lock:
            await self.client.aclose()
            self.store.conn.close()
