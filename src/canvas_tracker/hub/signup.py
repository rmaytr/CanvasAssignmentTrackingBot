"""The sign-up conversation, /settings, /disconnect and the owner's commands.

Telegram-free: every function takes a user and what they sent, updates the
registry or hub, and returns the replies to send. ``handlers.py`` wires it up.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from canvas_tracker.hub.hub import Hub
from canvas_tracker.hub.parsing import (
    looks_like_token,
    normalize_canvas_url,
    parse_clock,
    parse_quiet,
    quiet_window,
    resolve_timezone,
)
from canvas_tracker.hub.registry import OWNER_KEY, User
from canvas_tracker.notify.base import NotifyError
from canvas_tracker.render import copy
from canvas_tracker.render.format import format_due
from canvas_tracker.render.message import Button, RenderedMessage
from canvas_tracker.store.repo import AUTH_FAILED_SINCE, LAST_SUCCESSFUL_SYNC_AT

log = logging.getLogger(__name__)

Keyboard = tuple[tuple[Button, ...], ...]
TOKEN_STEPS = frozenset({"token", "edit_token"})
_KIND_STEPS = {
    "tz": frozenset({"tz", "edit_tz"}),
    "dt": frozenset({"digest", "edit_digest"}),
    "qh": frozenset({"quiet", "edit_quiet"}),
}
_US_ZONES = (
    ("Eastern", "America/New_York"),
    ("Central", "America/Chicago"),
    ("Mountain", "America/Denver"),
    ("Arizona", "America/Phoenix"),
    ("Pacific", "America/Los_Angeles"),
    ("Alaska", "America/Anchorage"),
    ("Hawaii", "Pacific/Honolulu"),
)
_DIGEST_CHOICES = (time(7, 0), time(8, 0), time(9, 0))
_QUIET_CHOICES = ((time(0, 0), time(8, 0)), (time(23, 0), time(7, 0)), (time(1, 0), time(9, 0)))


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    keyboard: Keyboard = ()


def fmt_time(t: time) -> str:
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def fmt_quiet(quiet: str) -> str:
    window = quiet_window(quiet)
    if window is None:
        return copy.QUIET_OFF
    return copy.QUIET_RANGE.format(start=fmt_time(window[0]), end=fmt_time(window[1]))


def _quiet_text(start: time, end: time) -> str:
    return f"{start:%H:%M}-{end:%H:%M}"


def _inside(t: time, start: time, end: time) -> bool:
    if start < end:
        return start <= t < end
    return t >= start or t < end


def _rows(buttons: list[Button], per_row: int) -> Keyboard:
    return tuple(tuple(buttons[i : i + per_row]) for i in range(0, len(buttons), per_row))


def tz_keyboard(suggested: str | None) -> Keyboard:
    rows: list[tuple[Button, ...]] = []
    if suggested:
        rows.append((Button(copy.BTN_TZ_CANVAS.format(zone=suggested), f"su:tz:{suggested}"),))
    rows += _rows([Button(label, f"su:tz:{zone}") for label, zone in _US_ZONES], 3)
    return tuple(rows)


def digest_keyboard() -> Keyboard:
    return ((*(Button(fmt_time(t), f"su:dt:{t:%H:%M}") for t in _DIGEST_CHOICES),),)


def quiet_keyboard() -> Keyboard:
    buttons = [
        Button(
            copy.QUIET_RANGE.format(start=fmt_time(a), end=fmt_time(b)),
            f"su:qh:{_quiet_text(a, b)}",
        )
        for a, b in _QUIET_CHOICES
    ]
    buttons.append(Button(copy.BTN_QUIET_OFF, "su:qh:off"))
    return _rows(buttons, 2)


def settings_keyboard() -> Keyboard:
    return (
        (Button(copy.BTN_SET_TZ, "set:tz"), Button(copy.BTN_SET_DIGEST, "set:dt")),
        (Button(copy.BTN_SET_QUIET, "set:qh"), Button(copy.BTN_SET_TOKEN, "set:tok")),
    )


class Signup:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.registry = hub.registry
        self._background: set[asyncio.Task[None]] = set()

    # --- prompts -------------------------------------------------------------

    def _token_prompt(self, user: User, edit: bool) -> Reply:
        base = user.canvas_base_url or ""
        link = Button(copy.BTN_OPEN_SETTINGS, url=f"{base}/profile/settings")
        return Reply(copy.ASK_TOKEN_EDIT if edit else copy.ASK_TOKEN, ((link,),) if base else ())

    def prompt(self, user: User) -> list[Reply]:
        """Ask again for whatever the user's current step needs."""
        step = user.step
        if step == "url":
            return [Reply(copy.ASK_URL)]
        if step in TOKEN_STEPS:
            return [self._token_prompt(user, edit=step == "edit_token")]
        if step in _KIND_STEPS["tz"]:
            text = copy.ASK_TZ if step == "tz" else copy.ASK_TZ_EDIT
            return [Reply(text, tz_keyboard(user.suggested_tz))]
        if step in _KIND_STEPS["dt"]:
            text = copy.ASK_DIGEST if step == "digest" else copy.ASK_DIGEST_EDIT
            return [Reply(text, digest_keyboard())]
        if step in _KIND_STEPS["qh"]:
            text = copy.ASK_QUIET if step == "quiet" else copy.ASK_QUIET_EDIT
            return [Reply(text, quiet_keyboard())]
        return [Reply(copy.HELP)]

    # --- /start --------------------------------------------------------------

    async def start(self, telegram_id: int, name: str, arg: str | None) -> list[Reply]:
        user = self.registry.get_user(telegram_id)
        if user is not None:
            if user.status == "active":
                return [self.welcome(user)]
            self.registry.update_user(telegram_id, step="url")
            return [Reply(copy.ASK_URL)]
        now = self.hub.clock()
        owner = self.hub.owner_id()
        if owner is None and self.hub.pairing is not None and arg:
            from canvas_tracker.bot.pairing import PairingResult

            if self.hub.pairing.check(arg) is PairingResult.OK:
                self.registry.set_state(OWNER_KEY, str(telegram_id))
                self.registry.create_user(telegram_id, name, now=now, is_owner=True)
                return [Reply(copy.PAIRED_OWNER), Reply(copy.SIGNUP_INTRO), Reply(copy.ASK_URL)]
        if owner == telegram_id:
            self.registry.create_user(telegram_id, name, now=now, is_owner=True)
            return [Reply(copy.SIGNUP_INTRO), Reply(copy.ASK_URL)]
        if arg:
            if self.registry.count_users() >= self.hub.max_users:
                return [Reply(copy.BOT_FULL)]
            if self.registry.redeem_invite(arg, telegram_id, now):
                self.registry.create_user(telegram_id, name, now=now)
                return [Reply(copy.SIGNUP_INTRO), Reply(copy.ASK_URL)]
        return [Reply(copy.INVITE_ONLY)]

    def welcome(self, user: User) -> Reply:
        tenant = self.hub.tenant(user.telegram_id)
        if tenant is None:
            return Reply(copy.HELP)
        s = tenant.settings
        interval = int(s.reminder_interval.total_seconds() // 60)
        return Reply(
            copy.WELCOME.format(
                digest=fmt_time(s.digest_time),
                tz=s.tz,
                window=int(s.reminder_window.total_seconds() // 3600),
                interval=f"{interval // 60} h" if interval % 60 == 0 else f"{interval} min",
                quiet=fmt_quiet(user.quiet),
            )
        )

    # --- answers to the current step ------------------------------------------

    async def text(self, user: User, text: str) -> list[Reply]:
        step = user.step
        if step is None:
            return [Reply(copy.HELP)]
        if step == "url":
            return await self._url(user, text)
        if step in TOKEN_STEPS:
            return await self._token(user, text)
        if step in _KIND_STEPS["tz"]:
            return await self._tz(user, resolve_timezone(text))
        if step in _KIND_STEPS["dt"]:
            return await self._digest(user, parse_clock(text))
        if step in _KIND_STEPS["qh"]:
            return await self._quiet(user, parse_quiet(text))
        return self.prompt(user)

    async def choice(self, user: User, kind: str, value: str) -> list[Reply]:
        """A tapped option button (``su:<kind>:<value>``) counts as typing that value."""
        if kind not in _KIND_STEPS or user.step not in _KIND_STEPS[kind]:
            return self.prompt(user)
        if kind == "tz":
            return await self._tz(user, resolve_timezone(value))
        if kind == "dt":
            return await self._digest(user, parse_clock(value))
        return await self._quiet(user, parse_quiet(value))

    async def _url(self, user: User, text: str) -> list[Reply]:
        base = normalize_canvas_url(text)
        if base is None:
            return [Reply(copy.URL_INVALID)]
        if not await self.hub.host_check(urlsplit(base).hostname or ""):
            return [Reply(copy.URL_UNREACHABLE)]
        self.registry.update_user(user.telegram_id, canvas_base_url=base, step="token")
        updated = self.registry.get_user(user.telegram_id)
        assert updated is not None  # noqa: S101
        return [self._token_prompt(updated, edit=False)]

    async def _token(self, user: User, text: str) -> list[Reply]:
        if user.canvas_base_url is None:
            self.registry.update_user(user.telegram_id, step="url")
            return [Reply(copy.ASK_URL)]
        token = text.strip()
        if not looks_like_token(token):
            return [Reply(copy.TOKEN_FORMAT)]
        result = await self.hub.verify(user.canvas_base_url, token)
        if result.problem is not None:
            host = urlsplit(user.canvas_base_url).hostname or user.canvas_base_url
            return [Reply(copy.TOKEN_PROBLEMS[result.problem].format(host=host))]
        sealed = self.hub.box.seal(token)
        if user.step == "edit_token":
            self.registry.update_user(user.telegram_id, token_sealed=sealed, step=None)
            await self._refresh(user.telegram_id)
            return [Reply(copy.TOKEN_SAVED)]
        self.registry.update_user(
            user.telegram_id, token_sealed=sealed, suggested_tz=result.time_zone, step="tz"
        )
        return [
            Reply(copy.TOKEN_SAVED),
            Reply(copy.ASK_TZ, tz_keyboard(result.time_zone)),
        ]

    async def _tz(self, user: User, zone: str | None) -> list[Reply]:
        if zone is None:
            return [Reply(copy.TZ_UNKNOWN)]
        ZoneInfo(zone)  # resolve_timezone only returns real zones
        if user.step == "edit_tz":
            self.registry.update_user(user.telegram_id, tz=zone, step=None)
            return await self._saved(user.telegram_id)
        self.registry.update_user(user.telegram_id, tz=zone, step="digest")
        return [Reply(copy.ASK_DIGEST, digest_keyboard())]

    async def _digest(self, user: User, at: time | None) -> list[Reply]:
        if at is None:
            return [Reply(copy.CLOCK_INVALID)]
        if user.step == "edit_digest":
            quiet = quiet_window(user.quiet)
            if quiet is not None and _inside(at, quiet[0], quiet[1]):
                return [Reply(copy.DIGEST_IN_QUIET.format(quiet=fmt_quiet(user.quiet)))]
            self.registry.update_user(user.telegram_id, digest_time=at, step=None)
            return await self._saved(user.telegram_id)
        # During sign-up quiet hours come next, and are checked against this time there.
        self.registry.update_user(user.telegram_id, digest_time=at, step="quiet")
        return [Reply(copy.ASK_QUIET, quiet_keyboard())]

    async def _quiet(self, user: User, quiet: tuple[time, time] | str | None) -> list[Reply]:
        if quiet is None:
            return [Reply(copy.QUIET_INVALID)]
        digest = user.digest_time or time(8, 0)
        if quiet == "off":
            value = "off"
        else:
            assert isinstance(quiet, tuple)  # noqa: S101
            if _inside(digest, quiet[0], quiet[1]):
                return [Reply(copy.QUIET_COVERS_DIGEST.format(digest=fmt_time(digest)))]
            value = _quiet_text(*quiet)
        if user.step == "edit_quiet":
            self.registry.update_user(user.telegram_id, quiet=value, step=None)
            return await self._saved(user.telegram_id)
        self.registry.update_user(user.telegram_id, quiet=value, status="active", step=None)
        await self._refresh(user.telegram_id)
        done = self.registry.get_user(user.telegram_id)
        assert done is not None and done.tz is not None  # noqa: S101
        return [
            Reply(copy.ALL_SET.format(digest=fmt_time(digest), tz=done.tz, quiet=fmt_quiet(value)))
        ]

    async def _refresh(self, telegram_id: int) -> None:
        """Rebuild the user's tenant and run its first tick (sync, maybe a message) soon."""
        tenant = await self.hub.refresh(telegram_id)
        if tenant is not None:
            task = asyncio.create_task(tenant.tick())
            self._background.add(task)
            task.add_done_callback(self._background.discard)

    async def _saved(self, telegram_id: int) -> list[Reply]:
        await self._refresh(telegram_id)
        user = self.registry.get_user(telegram_id)
        assert user is not None  # noqa: S101
        return [Reply(copy.SAVED), *self.settings(user)]

    # --- /settings, /cancel, /disconnect ---------------------------------------

    def settings(self, user: User) -> list[Reply]:
        if user.status != "active":
            return [Reply(copy.FINISH_SIGNUP_FIRST), *self.prompt(user)]
        text = copy.SETTINGS.format(
            host=urlsplit(user.canvas_base_url or "").hostname or "?",
            tz=user.tz,
            digest=fmt_time(user.digest_time or time(8, 0)),
            quiet=fmt_quiet(user.quiet),
        )
        return [Reply(text, settings_keyboard())]

    def begin_edit(self, user: User, what: str) -> list[Reply]:
        steps = {"tz": "edit_tz", "dt": "edit_digest", "qh": "edit_quiet", "tok": "edit_token"}
        if user.status != "active" or what not in steps:
            return self.prompt(user)
        self.registry.update_user(user.telegram_id, step=steps[what])
        updated = self.registry.get_user(user.telegram_id)
        assert updated is not None  # noqa: S101
        return self.prompt(updated)

    def cancel(self, user: User) -> list[Reply]:
        if user.status == "active" and user.step is not None:
            self.registry.update_user(user.telegram_id, step=None)
            return [Reply(copy.CANCELLED)]
        if user.status != "active":
            return self.prompt(user)
        return [Reply(copy.NOTHING_TO_CANCEL)]

    def disconnect_prompt(self) -> list[Reply]:
        keyboard = (
            (
                Button(copy.BTN_DISCONNECT_YES, "bye:yes"),
                Button(copy.BTN_DISCONNECT_NO, "bye:no"),
            ),
        )
        return [Reply(copy.DISCONNECT_CONFIRM, keyboard)]

    async def disconnect(self, user: User, confirmed: bool) -> list[Reply]:
        if not confirmed:
            return [Reply(copy.DISCONNECT_KEPT)]
        await self.hub.remove(user.telegram_id)
        return [Reply(copy.DISCONNECTED)]

    # --- owner commands ------------------------------------------------------

    def invite(self, user: User, bot_username: str | None) -> list[Reply]:
        if not user.is_owner:
            return [Reply(copy.OWNER_ONLY)]
        if not bot_username:
            return [Reply(copy.INVITE_NO_USERNAME)]
        code = self.registry.create_invite(self.hub.clock())
        return [Reply(copy.INVITE_LINK.format(link=f"https://t.me/{bot_username}?start={code}"))]

    def users(self, user: User) -> list[Reply]:
        if not user.is_owner:
            return [Reply(copy.OWNER_ONLY)]
        now = self.hub.clock()
        zone = ZoneInfo(user.tz or "UTC")
        everyone = self.registry.all_users()
        lines = [copy.USERS_HEADER.format(count=len(everyone), max=self.hub.max_users)]
        for n, other in enumerate(everyone, start=1):
            tenant = self.hub.tenant(other.telegram_id)
            if other.status != "active" or tenant is None:
                state = copy.USERS_STATE_SETUP
            else:
                failed = tenant.store.get_time(AUTH_FAILED_SINCE)
                synced = tenant.store.get_time(LAST_SUCCESSFUL_SYNC_AT)
                if failed is not None:
                    state = copy.USERS_STATE_AUTH.format(when=format_due(failed, now, zone))
                elif synced is not None:
                    state = copy.USERS_STATE_OK.format(when=format_due(synced, now, zone))
                else:
                    state = copy.USERS_STATE_NEVER
            lines.append(
                copy.USERS_LINE.format(
                    n=n,
                    name=other.display_name or "?",
                    you=copy.USERS_YOU if other.telegram_id == user.telegram_id else "",
                    host=urlsplit(other.canvas_base_url or "").hostname or "—",
                    state=state,
                )
            )
        return [Reply("\n".join(lines))]

    async def remove(self, user: User, arg: str | None) -> list[Reply]:
        if not user.is_owner:
            return [Reply(copy.OWNER_ONLY)]
        everyone = self.registry.all_users()
        if arg is None or not arg.strip().isdigit() or not 1 <= int(arg) <= len(everyone):
            return [Reply(copy.REMOVE_USAGE)]
        target = everyone[int(arg) - 1]
        if target.telegram_id == user.telegram_id:
            return [Reply(copy.REMOVE_SELF)]
        with contextlib.suppress(NotifyError):
            notifier = self.hub.notifier_factory(target.telegram_id)
            await notifier.send(RenderedMessage(copy.REMOVED_BY_OWNER))
        await self.hub.remove(target.telegram_id)
        return [Reply(copy.REMOVED.format(name=target.display_name or "?"))]
