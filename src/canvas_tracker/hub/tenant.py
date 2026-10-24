"""One user's slice of the bot: their own database file, Canvas client, sync and tick loop.

Each user gets the same single-user machinery the bot always had (Store,
SyncService, Runtime), pointed at a file only they use. Nothing here can read
another user's data.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from canvas_tracker.bot.deps import BotDeps
from canvas_tracker.domain.models import Settings
from canvas_tracker.hub.parsing import quiet_window
from canvas_tracker.hub.registry import Registry, User
from canvas_tracker.hub.secretbox import SecretBox
from canvas_tracker.notify.base import Notifier
from canvas_tracker.runtime.logging import register_secret
from canvas_tracker.runtime.loop import Runtime
from canvas_tracker.runtime.sync import SyncService
from canvas_tracker.sources.canvas_client import CanvasClient
from canvas_tracker.store.db import connect, migrate
from canvas_tracker.store.repo import Store

log = logging.getLogger(__name__)

DEFAULT_DIGEST = time(8, 0)
DIGEST_GRACE = timedelta(hours=4)
ClientFactory = Callable[[str, Callable[[], str]], CanvasClient]


def digest_grace_until(digest: time) -> time:
    """The morning list may still go out up to 4 h late (e.g. after an outage), same day."""
    minutes = digest.hour * 60 + digest.minute + int(DIGEST_GRACE.total_seconds() // 60)
    if minutes >= 24 * 60:
        return time(23, 59)
    return time(minutes // 60, minutes % 60)


def user_settings(user: User, shared: Mapping[str, object]) -> Settings:
    if user.tz is None or user.canvas_base_url is None:
        raise ValueError("user hasn't finished signing up")
    digest = user.digest_time or DEFAULT_DIGEST
    quiet = quiet_window(user.quiet)
    start, end = (None, None) if quiet is None else quiet
    return Settings(
        tz=user.tz,
        digest_time=digest,
        digest_grace_until=digest_grace_until(digest),
        quiet_start=start,
        quiet_end=end,
        canvas_host=urlsplit(user.canvas_base_url).hostname or "",
        **shared,  # type: ignore[arg-type]
    )


def user_db_path(data_dir: Path, telegram_id: int) -> Path:
    return data_dir / "users" / f"{telegram_id}.db"


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
    ) -> None:
        assert user.canvas_base_url is not None  # noqa: S101 - only active users get a tenant
        self.telegram_id = user.telegram_id
        path = user_db_path(data_dir, user.telegram_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(path)
        migrate(conn)
        self.store = Store(conn)
        self.settings = user_settings(user, shared)
        telegram_id = user.telegram_id

        def token() -> str:
            current = registry.get_user(telegram_id)
            if current is None or current.token_sealed is None:
                raise OSError("no token stored")  # the client reports this as an auth error
            try:
                secret = box.open(current.token_sealed)
            except ValueError:
                raise OSError("token can't be decrypted") from None
            register_secret(secret)
            return secret

        self.client = client_factory(user.canvas_base_url, token)
        self.sync = SyncService(self.client, self.store, user.canvas_base_url)
        self.runtime = Runtime(
            store=self.store,
            sync=self.sync,
            notifier=notifier,
            settings=self.settings,
            clock=clock,
            can_send=lambda: True,
            token=token,
            item_retention=item_retention,
        )
        self.deps = BotDeps(store=self.store, settings=self.settings, clock=clock, sync=self.sync)
        self._lock = asyncio.Lock()

    async def tick(self) -> None:
        async with self._lock:
            try:
                await self.runtime.tick()
            except Exception:  # one user's failure must never reach anyone else's tick
                log.exception("tick failed", extra={"user": self.telegram_id})

    async def close(self) -> None:
        async with self._lock:
            await self.client.aclose()
            self.store.conn.close()
