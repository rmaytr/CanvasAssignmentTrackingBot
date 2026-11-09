"""All users of one bot: their tenants, the shared tick loop, sign-up checks and removal."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from canvas_tracker.bot.pairing import PairingCode
from canvas_tracker.hub.monitor import DiskCheck, HealthReport, Monitor, Watched, WatchedMailer
from canvas_tracker.hub.parsing import is_public_address
from canvas_tracker.hub.ratelimit import RateLimiter
from canvas_tracker.hub.registry import HUB_LAST_TICK_AT, OWNER_KEY, Registry, User
from canvas_tracker.hub.secretbox import SecretBox
from canvas_tracker.hub.tenant import (
    ClientFactory,
    FeedClientFactory,
    MailerFactory,
    Tenant,
    default_feed_client,
    user_db_path,
)
from canvas_tracker.notify.base import Notifier, NotifyError
from canvas_tracker.render.message import RenderedMessage
from canvas_tracker.runtime.logging import register_secret
from canvas_tracker.runtime.loop import next_tick_delay
from canvas_tracker.sources.canvas_client import (
    CanvasAuthError,
    CanvasClient,
    CanvasProtocolError,
    CanvasUnavailable,
)
from canvas_tracker.sources.ical import parse_calendar
from canvas_tracker.sources.planner import PLANNER_PATH
from canvas_tracker.store.repo import AUTH_FAILED_SINCE, LAST_SUCCESSFUL_SYNC_AT, LAST_SYNC_ERROR

log = logging.getLogger(__name__)

VERIFY_TIMEOUT_S = 30.0
HOST_CHECK_TTL = timedelta(minutes=5)
SIGNUP_ABANDONED_AFTER = timedelta(days=7)
TOKEN_CHECKS_PER_WINDOW = 5
TOKEN_CHECK_WINDOW = timedelta(minutes=15)
MANUAL_SYNC_WINDOW = timedelta(minutes=1)
FEEDBACK_PER_WINDOW = 5
FEEDBACK_WINDOW = timedelta(hours=1)
MONITOR_TIMEOUT_S = 30.0
Problem = Literal["rejected", "unreachable", "not_canvas", "no_planner", "not_feed"]


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


class HostGuard:
    """Re-checks that a Canvas host still resolves only to public addresses before the
    bot talks to it, so a host that later points at this server (DNS rebinding) is
    refused. A passing check is remembered for ``ttl``; a failing one never is, so a
    host that comes back is used again on the next try."""

    def __init__(
        self,
        check: Callable[[str], Awaitable[bool]],
        clock: Callable[[], datetime],
        ttl: timedelta = HOST_CHECK_TTL,
    ) -> None:
        self.check = check
        self.clock = clock
        self.ttl = ttl
        self._passed: dict[str, datetime] = {}

    async def __call__(self, host: str) -> bool:
        now = self.clock()
        passed = self._passed.get(host)
        if passed is not None and timedelta(0) <= now - passed < self.ttl:
            return True
        ok = bool(host) and await self.check(host)
        if ok:
            self._passed[host] = now
        else:
            self._passed.pop(host, None)
            log.warning("canvas host refused: it doesn't resolve only to public addresses")
        return ok


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
        mailer_factory: MailerFactory | None = None,
        disk_usage: DiskCheck = shutil.disk_usage,
        feed_client_factory: FeedClientFactory = default_feed_client,
    ) -> None:
        self.registry = registry
        self.feed_client_factory = feed_client_factory
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
        self.monitor = Monitor(
            clock=clock, registry=registry, data_dir=data_dir, disk_usage=disk_usage
        )
        self.mailer_factory = None if mailer_factory is None else self._watched(mailer_factory)
        self.tenants: dict[int, Tenant] = {}
        self.broken: set[int] = set()
        self.host_guard = HostGuard(host_check, clock)
        self.token_limiter = RateLimiter(TOKEN_CHECKS_PER_WINDOW, TOKEN_CHECK_WINDOW)
        self.sync_limiter = RateLimiter(1, MANUAL_SYNC_WINDOW)
        self.feedback_limiter = RateLimiter(FEEDBACK_PER_WINDOW, FEEDBACK_WINDOW)

    def _watched(self, factory: MailerFactory) -> MailerFactory:
        """Every email, the morning list and confirmation codes alike, reports to the
        monitor whether it went out, so the owner hears when emails keep failing."""

        def build(to: Callable[[], str | None]) -> Notifier:
            return WatchedMailer(factory(to), self.monitor.record_email)

        return build

    # --- owner ---------------------------------------------------------------

    def owner_id(self) -> int | None:
        if self.owner_env_id is not None:
            return self.owner_env_id
        stored = self.registry.get_state(OWNER_KEY)
        return int(stored) if stored is not None and stored.lstrip("-").isdigit() else None

    # --- tenants -------------------------------------------------------------

    def _build(self, user: User) -> Tenant:
        telegram_id = user.telegram_id
        host = urlsplit(user.canvas_base_url or "").hostname or ""

        async def host_ok() -> bool:
            return await self.host_guard(host)

        def sync_wait() -> timedelta | None:
            return self.sync_limiter.hit(telegram_id, self.clock())

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
            mailer_factory=self.mailer_factory,
            host_check=host_ok,
            sync_wait=sync_wait,
            on_send=self.monitor.record_send,
            feed_client_factory=self.feed_client_factory,
        )

    def load(self) -> list[int]:
        """Start every active user. Returns the users who couldn't be started; a token that
        doesn't decrypt means TOKEN_KEY changed, which is the owner's problem to fix, not a
        reason to tell the user Canvas rejected them."""
        broken: list[int] = []
        for user in self.registry.active_users():
            try:
                sealed = user.feed_sealed if user.feed_mode else user.token_sealed
                if sealed is not None:
                    self.box.open(sealed)
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

    async def prune_signups(self) -> list[int]:
        """Forget sign-ups that stalled for 7 days, so they stop taking a MAX_USERS slot.
        Only onboarding users go; the owner and active users never do. Each one is told
        (best effort) how to come back."""
        from canvas_tracker.notify.base import NotifyError
        from canvas_tracker.render import copy
        from canvas_tracker.render.message import RenderedMessage

        owner = self.owner_id()
        stale = self.registry.stale_signups(self.clock() - SIGNUP_ABANDONED_AFTER)
        removed = [telegram_id for telegram_id in stale if telegram_id != owner]
        for telegram_id in removed:
            await self.remove(telegram_id)
            with contextlib.suppress(NotifyError):
                await self.notifier_factory(telegram_id).send(RenderedMessage(copy.SIGNUP_EXPIRED))
        if removed:
            log.info("removed abandoned sign-ups", extra={"count": len(removed)})
        return removed

    async def tick_all(self, wait_s: float = 50.0) -> None:
        """Start every user's tick side by side and wait a little for them. A user whose
        previous tick is still running (a hung Canvas) is skipped, never waited on, so
        nobody else's minute is lost and the heartbeat keeps coming."""
        try:
            await self.prune_signups()
        except Exception:  # housekeeping must never cost anyone their minute
            log.exception("pruning abandoned sign-ups failed")
        tenants = list(self.tenants.values())
        busy = [t.running for t in tenants if t.running is not None]
        started = [task for task in (t.start_tick() for t in tenants) if task is not None]
        ticks = [*busy, *started]
        if ticks:
            await asyncio.wait(ticks, timeout=wait_s)
        self.registry.set_time(HUB_LAST_TICK_AT, self.clock())
        try:
            async with asyncio.timeout(MONITOR_TIMEOUT_S):
                await self.watch()
        except Exception:  # monitoring must never cost anyone their minute
            log.exception("monitoring failed")

    # --- monitoring ----------------------------------------------------------

    def watched(self) -> list[Watched]:
        """Each started user's name, ID and sync timestamps: all the monitor may see."""
        names = {user.telegram_id: user.display_name for user in self.registry.active_users()}
        found: list[Watched] = []
        for telegram_id, tenant in list(self.tenants.items()):
            store = tenant.store
            found.append(
                Watched(
                    telegram_id=telegram_id,
                    name=names.get(telegram_id, ""),
                    last_ok=store.get_time(LAST_SUCCESSFUL_SYNC_AT),
                    last_error=store.get_state(LAST_SYNC_ERROR),
                    auth_failed=store.get_time(AUTH_FAILED_SINCE) is not None,
                    tick_started_at=tenant.running_since,
                )
            )
        return found

    def _onboarding(self) -> int:
        return sum(1 for user in self.registry.all_users() if user.status != "active")

    async def _tell_owner(self, text: str) -> bool:
        owner = self.owner_id()
        if owner is None:
            return False
        try:
            await self.notifier_factory(owner).send(RenderedMessage(text))
        except NotifyError:
            log.warning("owner alert could not be delivered")
            return False
        return True

    async def watch(self) -> list[str]:
        """Alert the owner about what started or cleared, and log the hourly summary."""
        users = self.watched()
        delivered = await self.monitor.check(users, self._tell_owner)
        if self.monitor.summary_due():
            self.monitor.summarize(users, onboarding=self._onboarding())
        return delivered

    def health(self) -> HealthReport:
        return self.monitor.report(
            self.watched(),
            onboarding=self._onboarding(),
            broken=len(self.broken),
            last_tick=self.registry.get_time(HUB_LAST_TICK_AT),
            email_configured=self.mailer_factory is not None,
        )

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
        if not await self.host_guard(urlsplit(base_url).hostname or ""):
            return Verification("unreachable")
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

    async def verify_feed(self, url: str) -> Verification:
        """Check a calendar feed link: its host is public, Canvas serves it, and it is an
        iCalendar. The feed's own time zone (when it names one) is kept as a suggestion."""
        register_secret(url)
        base = f"https://{urlsplit(url).hostname or ''}"
        if not await self.host_guard(urlsplit(url).hostname or ""):
            return Verification("unreachable")
        client = self.feed_client_factory(base, lambda: url)
        try:
            async with asyncio.timeout(VERIFY_TIMEOUT_S):
                response = await client.fetch()
        except TimeoutError:
            return Verification("unreachable")
        except CanvasAuthError:
            return Verification("rejected")
        except CanvasUnavailable:
            return Verification("unreachable")
        except CanvasProtocolError:
            return Verification("not_feed")
        finally:
            await client.aclose()
        try:
            calendar = parse_calendar(response.body, ZoneInfo("UTC"))
        except ValueError:
            return Verification("not_feed")
        return Verification(None, _zone(calendar.time_zone))
