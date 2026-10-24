"""All users of one bot: their tenants, the shared tick loop, sign-up checks and removal."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from canvas_tracker.bot.pairing import PairingCode
from canvas_tracker.hub.parsing import is_public_address
from canvas_tracker.hub.registry import HUB_LAST_TICK_AT, OWNER_KEY, Registry, User
from canvas_tracker.hub.secretbox import SecretBox
from canvas_tracker.hub.tenant import ClientFactory, Tenant, user_db_path
from canvas_tracker.notify.base import Notifier
from canvas_tracker.runtime.loop import next_tick_delay
from canvas_tracker.sources.canvas_client import (
    CanvasAuthError,
    CanvasClient,
    CanvasProtocolError,
    CanvasUnavailable,
)
from canvas_tracker.sources.planner import PLANNER_PATH

log = logging.getLogger(__name__)

VERIFY_TIMEOUT_S = 30.0
Problem = Literal["rejected", "unreachable", "not_canvas", "no_planner"]


@dataclass(frozen=True, slots=True)
class Verification:
    problem: Problem | None
    time_zone: str | None = None


def default_client(base_url: str, token: Callable[[], str]) -> CanvasClient:
    return CanvasClient(base_url, token)


async def resolves_publicly(host: str) -> bool:
    """True if every address ``host`` resolves to is public (so it can't be this server)."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {str(info[4][0]) for info in infos}
    return bool(addresses) and all(is_public_address(a) for a in addresses)


def _zone(value: object) -> str | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return value


class Hub:
    def __init__(
        self,
        *,
        registry: Registry,
        box: SecretBox,
        data_dir: Path,
        shared: Mapping[str, object],
        clock: Callable[[], datetime],
        notifier_factory: Callable[[int], Notifier],
        client_factory: ClientFactory = default_client,
        host_check: Callable[[str], Awaitable[bool]] = resolves_publicly,
        item_retention: timedelta = timedelta(days=30),
        max_users: int = 25,
        owner_env_id: int | None = None,
        pairing: PairingCode | None = None,
    ) -> None:
        self.registry = registry
        self.box = box
        self.data_dir = data_dir
        self.shared = shared
        self.clock = clock
        self.notifier_factory = notifier_factory
        self.client_factory = client_factory
        self.host_check = host_check
        self.item_retention = item_retention
        self.max_users = max_users
        self.owner_env_id = owner_env_id
        self.pairing = pairing
        self.tenants: dict[int, Tenant] = {}
        self.broken: set[int] = set()

    # --- owner ---------------------------------------------------------------

    def owner_id(self) -> int | None:
        if self.owner_env_id is not None:
            return self.owner_env_id
        stored = self.registry.get_state(OWNER_KEY)
        return int(stored) if stored is not None and stored.lstrip("-").isdigit() else None

    # --- tenants -------------------------------------------------------------

    def _build(self, user: User) -> Tenant:
        return Tenant(
            user,
            registry=self.registry,
            box=self.box,
            data_dir=self.data_dir,
            shared=self.shared,
            notifier=self.notifier_factory(user.telegram_id),
            clock=self.clock,
            client_factory=self.client_factory,
            item_retention=self.item_retention,
        )

    def load(self) -> list[int]:
        """Start every active user. Returns the users who couldn't be started; a token that
        doesn't decrypt means TOKEN_KEY changed, which is the owner's problem to fix, not a
        reason to tell the user Canvas rejected them."""
        broken: list[int] = []
        for user in self.registry.active_users():
            try:
                if user.token_sealed is not None:
                    self.box.open(user.token_sealed)
                self.tenants[user.telegram_id] = self._build(user)
            except ValueError:
                broken.append(user.telegram_id)
                log.error("stored token can't be decrypted: TOKEN_KEY doesn't match the data")
            except Exception:  # one broken record must not keep the others offline
                broken.append(user.telegram_id)
                log.exception("could not start user", extra={"user": user.telegram_id})
        self.broken = set(broken)
        return broken

    async def tell_owner_about_broken(self) -> None:
        owner = self.owner_id()
        if not self.broken or owner is None:
            return
        from canvas_tracker.notify.base import NotifyError
        from canvas_tracker.render import copy
        from canvas_tracker.render.message import RenderedMessage

        with contextlib.suppress(NotifyError):
            text = copy.OWNER_BROKEN_USERS.format(count=len(self.broken))
            await self.notifier_factory(owner).send(RenderedMessage(text))

    def tenant(self, telegram_id: int) -> Tenant | None:
        return self.tenants.get(telegram_id)

    async def refresh(self, telegram_id: int) -> Tenant | None:
        """(Re)build a user's tenant from the registry and start its first tick, e.g. after
        sign-up or a settings change."""
        old = self.tenants.pop(telegram_id, None)
        if old is not None:
            await old.close()
        user = self.registry.get_user(telegram_id)
        if user is None or user.status != "active":
            return None
        tenant = self._build(user)
        self.tenants[telegram_id] = tenant
        self.broken.discard(telegram_id)
        tenant.start_tick()
        return tenant

    async def remove(self, telegram_id: int) -> None:
        """Erase a user: their tenant, their database file and their registry row."""
        old = self.tenants.pop(telegram_id, None)
        if old is not None:
            await old.close()
        path = user_db_path(self.data_dir, telegram_id)
        for suffix in ("", "-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        self.registry.delete_user(telegram_id)

    async def tick_all(self, wait_s: float = 50.0) -> None:
        """Start every user's tick side by side and wait a little for them. A user whose
        previous tick is still running (a hung Canvas) is skipped, never waited on, so
        nobody else's minute is lost and the heartbeat keeps coming."""
        tenants = list(self.tenants.values())
        busy = [t.running for t in tenants if t.running is not None]
        started = [task for task in (t.start_tick() for t in tenants) if task is not None]
        ticks = [*busy, *started]
        if ticks:
            await asyncio.wait(ticks, timeout=wait_s)
        self.registry.set_time(HUB_LAST_TICK_AT, self.clock())

    async def run_forever(self, interval_s: float = 60.0) -> None:
        while True:
            try:
                await self.tick_all()
            except Exception:
                log.exception("hub tick failed")
            await asyncio.sleep(next_tick_delay(self.clock(), interval_s))

    async def close(self) -> None:
        for telegram_id in list(self.tenants):
            await self.tenants.pop(telegram_id).close()

    # --- sign-up checks ------------------------------------------------------

    async def verify(self, base_url: str, token: str) -> Verification:
        """Check a token against its Canvas: who it belongs to (only the time zone is kept)
        and that it can read the To Do list."""
        client = self.client_factory(base_url, lambda: token)
        try:
            async with asyncio.timeout(VERIFY_TIMEOUT_S):
                try:
                    profile = await client.get_json("/api/v1/users/self/profile")
                except CanvasAuthError:
                    return Verification("rejected")
                except CanvasUnavailable:
                    return Verification("unreachable")
                except CanvasProtocolError:
                    return Verification("not_canvas")
                zone = _zone(profile.get("time_zone")) if isinstance(profile, dict) else None
                try:
                    await client.get_json(PLANNER_PATH, {"per_page": "1"})
                except CanvasAuthError as exc:
                    return Verification("rejected" if exc.challenged else "no_planner", zone)
                except (CanvasUnavailable, CanvasProtocolError):
                    return Verification("no_planner", zone)
                return Verification(None, zone)
        except TimeoutError:
            return Verification("unreachable")
        finally:
            await client.aclose()
