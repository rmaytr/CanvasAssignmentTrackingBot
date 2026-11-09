"""The sign-up conversation, /settings, /disconnect and the owner's commands.

Telegram-free: every function takes a user and what they sent, updates the
registry or hub, and returns the replies to send. ``handlers.py`` wires it up.
"""

from __future__ import annotations

import contextlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from canvas_tracker import __version__
from canvas_tracker.bot.pairing import ALPHABET, CODE_LENGTH, PairingResult
from canvas_tracker.domain.models import MIN_REMINDER_INTERVAL, Settings
from canvas_tracker.hub.email import EmailSetup
from canvas_tracker.hub.hub import Hub
from canvas_tracker.hub.monitor import HealthReport, disk_label
from canvas_tracker.hub.parsing import (
    contains_canvas_token,
    contains_feed_url,
    looks_like_token,
    normalize_canvas_url,
    normalize_feed_url,
    parse_clock,
    parse_quiet,
    quiet_window,
    resolve_timezone,
)
from canvas_tracker.hub.registry import OWNER_KEY, User
from canvas_tracker.hub.tenant import bot_defaults, user_settings
from canvas_tracker.notify.base import NotifyError
from canvas_tracker.render import copy
from canvas_tracker.render.format import escape, format_due, format_left, format_span
from canvas_tracker.render.message import Button, RenderedMessage
from canvas_tracker.render.views import email_label, rhythm_sentence, rhythm_short
from canvas_tracker.store.repo import AUTH_FAILED_SINCE, LAST_SUCCESSFUL_SYNC_AT

log = logging.getLogger(__name__)

Keyboard = tuple[tuple[Button, ...], ...]
TOKEN_STEPS = frozenset({"token", "edit_token"})
FEED_STEPS = frozenset({"feed", "edit_feed"})
SECRET_STEPS = TOKEN_STEPS | FEED_STEPS  # what's typed at these steps never stays in the chat
URL_STEPS = frozenset({"url", "edit_url"})
FEEDBACK_MAX_CHARS = 3000  # leaves room for the header within Telegram's 4096
LATEST_DIGEST = time(20, 0)  # leaves a 4 h same-day window for a late morning list
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
# The reminder rhythm a user can pick in /settings → ⏰ Reminders (su:ri / su:rw / su:la).
INTERVAL_CHOICES = (1, 2, 3, 4)  # hours between repeating reminders; "off" is stored as 0
WINDOW_CHOICES = (12, 24, 48)  # hours ahead that count as urgent
LOOKAHEAD_CHOICES = (7, 14, 21)  # days the morning list covers (Canvas is read 21 days ahead)
_RHYTHM_FIELDS = {
    "ri": "reminder_interval_minutes",
    "rw": "reminder_window_hours",
    "la": "digest_lookahead_days",
}
assert timedelta(hours=min(INTERVAL_CHOICES)) >= MIN_REMINDER_INTERVAL  # noqa: S101


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
        (Button(copy.BTN_SET_QUIET, "set:qh"), Button(copy.BTN_SET_REMINDERS, "set:rem")),
        (Button(copy.BTN_SET_TOKEN, "set:tok"), Button(copy.BTN_SET_FEED, "set:feed")),
        (Button(copy.BTN_SET_URL, "set:url"), Button(copy.BTN_SET_EMAIL, "set:em")),
    )


def _option(label: str, data: str, chosen: bool) -> Button:
    return Button(copy.BTN_CHOSEN.format(label=label) if chosen else label, data)


def reminders_keyboard(s: Settings) -> Keyboard:
    interval = s.reminder_interval
    every = [
        _option(
            copy.BTN_INTERVAL.format(hours=h), f"su:ri:{h * 60}", interval == timedelta(hours=h)
        )
        for h in INTERVAL_CHOICES
    ]
    every.append(_option(copy.BTN_INTERVAL_OFF, "su:ri:off", interval is None))
    window = tuple(
        _option(
            copy.BTN_WINDOW.format(hours=h), f"su:rw:{h}", s.reminder_window == timedelta(hours=h)
        )
        for h in WINDOW_CHOICES
    )
    lookahead = tuple(
        _option(
            copy.BTN_LOOKAHEAD.format(days=d), f"su:la:{d}", s.digest_lookahead == timedelta(days=d)
        )
        for d in LOOKAHEAD_CHOICES
    )
    return (*_rows(every, 3), window, lookahead)


def reminders_menu(s: Settings) -> Reply:
    repeat = (
        copy.REMINDERS_REPEAT_OFF
        if s.reminder_interval is None
        else copy.REMINDERS_REPEAT_ON.format(interval=format_span(s.reminder_interval))
    )
    text = copy.REMINDERS_MENU.format(
        interval=repeat,
        window=format_span(s.reminder_window),
        lookahead=format_span(s.digest_lookahead),
    )
    return Reply(text, reminders_keyboard(s))


def parse_rhythm(kind: str, value: str) -> int | None:
    """The registry value for a tapped rhythm option, or None if it isn't one we offer."""
    if kind == "ri":
        if value == "off":
            return 0
        allowed = {h * 60 for h in INTERVAL_CHOICES}
    elif kind == "rw":
        allowed = set(WINDOW_CHOICES)
    elif kind == "la":
        allowed = set(LOOKAHEAD_CHOICES)
    else:
        return None
    return int(value) if value.isdigit() and int(value) in allowed else None


_PAIRING_REPLIES = {
    PairingResult.WRONG: copy.PAIR_WRONG,
    PairingResult.EXPIRED: copy.PAIR_EXPIRED,
    PairingResult.LOCKED: copy.PAIR_LOCKED,
}


def _pairing_shaped(arg: str) -> bool:
    value = arg.strip().upper()
    return len(value) == CODE_LENGTH and all(c in ALPHABET for c in value)


class Signup:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.registry = hub.registry
        self.email = EmailSetup(hub)

    # --- prompts -------------------------------------------------------------

    def is_owner(self, user: User) -> bool:
        return user.telegram_id == self.hub.owner_id()

    def _token_prompt(self, user: User, edit: bool) -> Reply:
        new_site = edit and user.pending_base_url is not None
        if new_site:
            text = copy.ASK_TOKEN_NEW_SITE
        elif edit:
            text = copy.ASK_TOKEN_SWITCH if user.feed_mode else copy.ASK_TOKEN_EDIT
        else:
            text = copy.ASK_TOKEN
        return Reply(text, self._token_rows(user, edit))

    @staticmethod
    def _token_rows(user: User, edit: bool) -> tuple[tuple[Button, ...], ...]:
        """The token step's buttons: open Canvas's settings, or use the feed instead."""
        new_site = edit and user.pending_base_url is not None
        base = (user.pending_base_url if new_site else user.canvas_base_url) or ""
        rows: list[tuple[Button, ...]] = []
        if base:
            rows.append((Button(copy.BTN_OPEN_SETTINGS, url=f"{base}/profile/settings"),))
        rows.append((Button(copy.BTN_USE_FEED, "su:mode:feed"),))
        return tuple(rows)

    def _feed_prompt(self, user: User, edit: bool) -> Reply:
        new_site = edit and user.pending_base_url is not None
        base = (user.pending_base_url if new_site else user.canvas_base_url) or ""
        if new_site:
            text = copy.ASK_FEED_NEW_SITE
        elif edit:
            text = copy.ASK_FEED_EDIT if user.feed_mode else copy.ASK_FEED_SWITCH
        else:
            text = copy.ASK_FEED
        rows: list[tuple[Button, ...]] = []
        if base:
            rows.append((Button(copy.BTN_OPEN_CALENDAR, url=f"{base}/calendar"),))
        rows.append((Button(copy.BTN_USE_TOKEN, "su:mode:token"),))
        return Reply(text, tuple(rows))

    def prompt(self, user: User) -> list[Reply]:
        """Ask again for whatever the user's current step needs."""
        step = user.step
        if step == "url":
            return [Reply(copy.ASK_URL)]
        if step == "edit_url":
            return [Reply(copy.ASK_URL_EDIT)]
        if step in TOKEN_STEPS:
            return [self._token_prompt(user, edit=step == "edit_token")]
        if step in FEED_STEPS:
            return [self._feed_prompt(user, edit=step == "edit_feed")]
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
                if user.step is not None:  # leave any half-finished settings change
                    self.registry.update_user(telegram_id, step=None, pending_base_url=None)
                return [self.welcome(user)]
            self.registry.update_user(telegram_id, step="url")
            self.registry.touch(telegram_id, self.hub.clock())
            return [Reply(copy.ASK_URL)]
        now = self.hub.clock()
        owner = self.hub.owner_id()
        if owner is None and self.hub.pairing is not None and arg and _pairing_shaped(arg):
            # Only code-shaped attempts count, so random /start args can't burn the code.
            result = self.hub.pairing.check(arg)
            if result is PairingResult.OK:
                self.registry.set_state(OWNER_KEY, str(telegram_id))
                self.registry.create_user(telegram_id, name, now=now, is_owner=True)
                return [Reply(copy.PAIRED_OWNER), self.intro(), Reply(copy.ASK_URL)]
            return [Reply(_PAIRING_REPLIES[result])]
        if owner == telegram_id:
            self.registry.create_user(telegram_id, name, now=now, is_owner=True)
            return [self.intro(), Reply(copy.ASK_URL)]
        if arg:
            await self.hub.prune_signups()  # stalled sign-ups don't hold a slot
            if self.registry.count_users() >= self.hub.max_users:
                return [Reply(copy.BOT_FULL)]
            if self.registry.redeem_invite(arg, telegram_id, now):
                self.registry.create_user(telegram_id, name, now=now)
                return [self.intro(), Reply(copy.ASK_URL)]
        return [Reply(copy.INVITE_ONLY)]

    def intro(self) -> Reply:
        """The sign-up welcome, with the bot's default rhythm (everyone starts on it)."""
        s = bot_defaults(self.hub.shared)
        interval = s.reminder_interval or timedelta(hours=2)  # the bot default is never off
        return Reply(
            copy.SIGNUP_INTRO.format(
                interval=format_span(interval), window=format_span(s.reminder_window)
            )
        )

    def welcome(self, user: User) -> Reply:
        tenant = self.hub.tenant(user.telegram_id)
        if tenant is None:
            return Reply(copy.ACCOUNT_PROBLEM)
        s = tenant.settings
        return Reply(
            copy.WELCOME.format(
                digest=fmt_time(s.digest_time),
                tz=s.tz,
                rhythm=rhythm_sentence(s),
                quiet=fmt_quiet(user.quiet),
            )
        )

    def _effective(self, user: User) -> Settings:
        """The settings this (active) user's reminders run with."""
        return user_settings(user, self.hub.shared)

    # --- answers to the current step ------------------------------------------

    def _seen(self, user: User) -> None:
        if user.status == "onboarding":
            self.registry.touch(user.telegram_id, self.hub.clock())

    def token_wait(self, user: User) -> timedelta | None:
        """How long until this user may have another token checked (None: right away)."""
        return self.hub.token_limiter.wait(user.telegram_id, self.hub.clock())

    async def text(self, user: User, text: str) -> list[Reply]:
        self._seen(user)
        step = user.step
        if step is None:
            return [Reply(copy.HELP)]
        if contains_feed_url(text) and step in URL_STEPS | SECRET_STEPS:
            return await self._feed(user, text)  # a feed link names its Canvas site too
        if step in URL_STEPS:
            return await self._url(user, text)
        if step in TOKEN_STEPS:
            return await self._token(user, text)
        if step in FEED_STEPS:
            if contains_canvas_token(text):  # a token pasted here after all: just use it
                return await self._token(user, text)
            return [Reply(copy.FEED_INVALID)]
        if step in _KIND_STEPS["tz"]:
            return await self._tz(user, resolve_timezone(text))
        if step in _KIND_STEPS["dt"]:
            return await self._digest(user, parse_clock(text))
        if step in _KIND_STEPS["qh"]:
            return await self._quiet(user, parse_quiet(text))
        return self.prompt(user)

    async def choice(self, user: User, kind: str, value: str) -> list[Reply]:
        """A tapped option button (``su:<kind>:<value>``) counts as typing that value."""
        self._seen(user)
        if kind in _RHYTHM_FIELDS:
            return await self._rhythm(user, kind, value)
        if kind == "mode":
            return self._switch_method(user, value)
        if kind not in _KIND_STEPS or user.step not in _KIND_STEPS[kind]:
            return self.prompt(user)
        if kind == "tz":
            return await self._tz(user, resolve_timezone(value))
        if kind == "dt":
            return await self._digest(user, parse_clock(value))
        return await self._quiet(user, parse_quiet(value))

    def _switch_method(self, user: User, value: str) -> list[Reply]:
        """🔑/📅 at the token or feed step: ask for the other kind of secret instead."""
        if user.step not in SECRET_STEPS or value not in ("token", "feed"):
            return self.prompt(user)
        editing = user.step in ("edit_token", "edit_feed")
        step = f"edit_{value}" if editing else value
        self.registry.update_user(user.telegram_id, step=step)
        updated = self.registry.get_user(user.telegram_id)
        assert updated is not None  # noqa: S101
        return self.prompt(updated)

    async def _url(self, user: User, text: str) -> list[Reply]:
        base = normalize_canvas_url(text)
        if base is None:
            return [Reply(copy.URL_INVALID)]
        if not await self.hub.host_guard(urlsplit(base).hostname or ""):
            return [Reply(copy.URL_UNREACHABLE)]
        if user.step == "edit_url":  # switch only once a token (or feed) for the new site works
            step = "edit_feed" if user.feed_mode else "edit_token"
            self.registry.update_user(user.telegram_id, pending_base_url=base, step=step)
            updated = self.registry.get_user(user.telegram_id)
            assert updated is not None  # noqa: S101
            if user.feed_mode:
                return [self._feed_prompt(updated, edit=True)]
            return [self._token_prompt(updated, edit=True)]
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
        editing = user.step in ("edit_token", "edit_feed")
        base = (user.pending_base_url if editing else None) or user.canvas_base_url
        wait = self.hub.token_limiter.hit(user.telegram_id, self.hub.clock())
        if wait is not None:
            minutes = max(1, math.ceil(wait.total_seconds() / 60))
            return [Reply(copy.TOKEN_TOO_MANY.format(minutes=minutes))]
        result = await self.hub.verify(base, token)
        if result.problem is not None:
            host = urlsplit(base).hostname or base
            fix = copy.FIX_ADDRESS_SETTINGS if editing else copy.FIX_ADDRESS_SIGNUP
            text = copy.TOKEN_PROBLEMS[result.problem].format(host=host, fix=fix)
            # the way out (a fresh token, or the feed when tokens are restricted) one tap away
            return [Reply(text, self._token_rows(user, editing))]
        sealed = self.hub.box.seal(token)
        if editing:  # a feed link, if there was one, is forgotten once the token works
            self.registry.update_user(
                user.telegram_id,
                token_sealed=sealed,
                mode="token",
                feed_sealed=None,
                canvas_base_url=base,
                pending_base_url=None,
                step=None,
            )
            await self._refresh(user.telegram_id)
            return [Reply(copy.TOKEN_SAVED)]
        self.registry.update_user(
            user.telegram_id,
            token_sealed=sealed,
            mode="token",
            feed_sealed=None,
            suggested_tz=result.time_zone,
            step="tz",
        )
        return [
            Reply(copy.TOKEN_SAVED),
            Reply(copy.ASK_TZ, tz_keyboard(result.time_zone)),
        ]

    async def _feed(self, user: User, text: str) -> list[Reply]:
        """A pasted calendar feed link: checked with Canvas, then stored encrypted. The
        link names its own Canvas site, which replaces the address typed before."""
        url = normalize_feed_url(text)
        if url is None:
            return [Reply(copy.FEED_INVALID)]
        wait = self.hub.token_limiter.hit(user.telegram_id, self.hub.clock())
        if wait is not None:
            minutes = max(1, math.ceil(wait.total_seconds() / 60))
            return [Reply(copy.FEED_TOO_MANY.format(minutes=minutes))]
        result = await self.hub.verify_feed(url)
        host = urlsplit(url).hostname or ""
        if result.problem is not None:
            problem = result.problem if result.problem in copy.FEED_PROBLEMS else "not_feed"
            return [Reply(copy.FEED_PROBLEMS[problem].format(host=host))]
        sealed = self.hub.box.seal(url)
        base = f"https://{host}"
        if user.status == "active":  # the token, if there was one, is forgotten
            self.registry.update_user(
                user.telegram_id,
                feed_sealed=sealed,
                mode="feed",
                token_sealed=None,
                canvas_base_url=base,
                pending_base_url=None,
                step=None,
            )
            await self._refresh(user.telegram_id)
            return [Reply(copy.FEED_SAVED)]
        self.registry.update_user(
            user.telegram_id,
            feed_sealed=sealed,
            mode="feed",
            token_sealed=None,
            canvas_base_url=base,
            suggested_tz=result.time_zone,
            step="tz",
        )
        return [Reply(copy.FEED_SAVED), Reply(copy.ASK_TZ, tz_keyboard(result.time_zone))]

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
        if at > LATEST_DIGEST:
            return [Reply(copy.DIGEST_TOO_LATE)]
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
        text = copy.ALL_SET.format(
            digest=fmt_time(digest),
            tz=done.tz,
            rhythm=rhythm_sentence(self._effective(done)),
            quiet=fmt_quiet(value),
        )
        if done.feed_mode:
            text = f"{text}\n\n{copy.FEED_ALL_SET}"
        return [Reply(text)]

    async def _rhythm(self, user: User, kind: str, value: str) -> list[Reply]:
        """A tapped reminder-rhythm option. Works from any menu while active, since each
        button names one exact value; the change applies from the very next tick."""
        if user.status != "active":
            return self.prompt(user)
        number = parse_rhythm(kind, value)
        if number is None:
            return [reminders_menu(self._effective(user))]
        self.registry.update_user(user.telegram_id, **{_RHYTHM_FIELDS[kind]: number})
        await self._refresh(user.telegram_id)
        updated = self.registry.get_user(user.telegram_id)
        assert updated is not None  # noqa: S101
        menu = reminders_menu(self._effective(updated))
        return [Reply(f"{copy.SAVED}\n\n{menu.text}", menu.keyboard)]

    async def _refresh(self, telegram_id: int) -> None:
        """Rebuild the user's tenant; its first tick (sync, maybe a message) starts right away."""
        await self.hub.refresh(telegram_id)

    async def _saved(self, telegram_id: int) -> list[Reply]:
        await self._refresh(telegram_id)
        user = self.registry.get_user(telegram_id)
        assert user is not None  # noqa: S101
        return [Reply(copy.SAVED), *self.settings(user)]

    # --- /settings, /cancel, /disconnect ---------------------------------------

    def settings(self, user: User) -> list[Reply]:
        if user.status != "active":
            return [Reply(copy.FINISH_SIGNUP_FIRST), *self.prompt(user)]
        effective = self._effective(user)
        text = copy.SETTINGS.format(
            host=urlsplit(user.canvas_base_url or "").hostname or "?",
            connection=copy.CONNECTION_FEED if user.feed_mode else copy.CONNECTION_TOKEN,
            tz=user.tz,
            digest=fmt_time(user.digest_time or time(8, 0)),
            quiet=fmt_quiet(user.quiet),
            reminders=rhythm_short(effective),
            lookahead=format_span(effective.digest_lookahead),
            email=email_label(
                self.email.address(user), available=self.email.available, masked=False
            ),
        )
        return [Reply(text, settings_keyboard())]

    async def email_command(self, user: User, arg: str | None) -> list[Reply]:
        if user.status != "active":
            return [Reply(copy.FINISH_SIGNUP_FIRST), *self.prompt(user)]
        return [Reply(text) for text in await self.email.command(user, arg)]

    def begin_edit(self, user: User, what: str) -> list[Reply]:
        steps = {
            "tz": "edit_tz",
            "dt": "edit_digest",
            "qh": "edit_quiet",
            "tok": "edit_token",
            "feed": "edit_feed",
            "url": "edit_url",
        }
        if user.status == "active" and what in ("rem", "em"):
            if user.step is not None:  # leave any half-finished settings change
                self.registry.update_user(user.telegram_id, step=None, pending_base_url=None)
            if what == "em":  # an address needs typing, so this explains /email
                return [Reply(self.email.status(user))]
            return [reminders_menu(self._effective(user))]
        if user.status != "active" or what not in steps:
            return self.prompt(user)
        self.registry.update_user(user.telegram_id, step=steps[what], pending_base_url=None)
        updated = self.registry.get_user(user.telegram_id)
        assert updated is not None  # noqa: S101
        return self.prompt(updated)

    def cancel(self, user: User) -> list[Reply]:
        if user.status == "active" and user.step is not None:
            self.registry.update_user(user.telegram_id, step=None, pending_base_url=None)
            return [Reply(copy.CANCELLED)]
        if user.status != "active":
            return self.prompt(user)
        return [Reply(copy.NOTHING_TO_CANCEL)]

    def disconnect_prompt(self, user: User) -> list[Reply]:
        keyboard = (
            (
                Button(copy.BTN_DISCONNECT_YES, "bye:yes"),
                Button(copy.BTN_DISCONNECT_NO, "bye:no"),
            ),
        )
        return [
            Reply(
                copy.DISCONNECT_CONFIRM_FEED if user.feed_mode else copy.DISCONNECT_CONFIRM,
                keyboard,
            )
        ]

    async def disconnect(self, user: User, confirmed: bool) -> list[Reply]:
        if not confirmed:
            return [Reply(copy.DISCONNECT_KEPT)]
        await self.hub.remove(user.telegram_id)
        return [Reply(copy.DISCONNECTED_FEED if user.feed_mode else copy.DISCONNECTED)]

    # --- /feedback ----------------------------------------------------------

    async def feedback(self, user: User, text: str, username: str | None = None) -> list[Reply]:
        """Pass a note on to the owner over Telegram: the sender's name, Telegram ID and
        the note itself, never anything from their Canvas. Five per user per hour; a note
        that couldn't be delivered doesn't count."""
        body = text.strip()
        if not body:
            return [Reply(copy.FEEDBACK_USAGE)]
        if contains_canvas_token(body):
            return [Reply(copy.FEEDBACK_HAS_TOKEN)]
        if contains_feed_url(body):
            return [Reply(copy.FEEDBACK_HAS_FEED)]
        if len(body) > FEEDBACK_MAX_CHARS:
            return [Reply(copy.FEEDBACK_TOO_LONG.format(limit=FEEDBACK_MAX_CHARS))]
        if self.is_owner(user) or user.is_owner:
            return [Reply(copy.FEEDBACK_OWNER)]
        owner = self.hub.owner_id()
        if owner is None:
            return [Reply(copy.FEEDBACK_FAILED)]
        now = self.hub.clock()
        wait = self.hub.feedback_limiter.wait(user.telegram_id, now)
        if wait is not None:
            minutes = max(1, math.ceil(wait.total_seconds() / 60))
            return [Reply(copy.FEEDBACK_TOO_MANY.format(minutes=minutes))]
        note = copy.FEEDBACK_TO_OWNER.format(
            name=escape(user.display_name or "?"),
            telegram_id=user.telegram_id,
            username=copy.FEEDBACK_USERNAME.format(username=escape(username)) if username else "",
            signup=copy.FEEDBACK_SIGNING_UP if user.status != "active" else "",
            text=escape(body),
        )
        try:
            await self.hub.notifier_factory(owner).send(RenderedMessage(note))
        except NotifyError:
            log.warning("feedback could not be delivered to the owner")
            return [Reply(copy.FEEDBACK_FAILED)]
        self.hub.feedback_limiter.hit(user.telegram_id, now)
        return [Reply(copy.FEEDBACK_SENT)]

    # --- owner commands ------------------------------------------------------

    def invite(self, user: User, bot_username: str | None) -> list[Reply]:
        if not self.is_owner(user):
            return [Reply(copy.OWNER_ONLY)]
        if not bot_username:
            return [Reply(copy.INVITE_NO_USERNAME)]
        code = self.registry.create_invite(self.hub.clock())
        return [Reply(copy.INVITE_LINK.format(link=f"https://t.me/{bot_username}?start={code}"))]

    def users(self, user: User) -> list[Reply]:
        if not self.is_owner(user):
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
                    rejected = (
                        copy.USERS_STATE_FEED_REJECTED if other.feed_mode else copy.USERS_STATE_AUTH
                    )
                    state = rejected.format(when=format_due(failed, now, zone))
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
                    mode=copy.USERS_MODE_FEED if other.feed_mode else copy.USERS_MODE_TOKEN,
                    state=state,
                    email=copy.USERS_EMAIL_ON
                    if self.email.available and other.email_sealed is not None
                    else copy.USERS_EMAIL_OFF,
                )
            )
        return [Reply("\n".join(lines))]

    def health(self, user: User) -> list[Reply]:
        """/health: how the server is doing, in counts. Nobody's Canvas data is in it."""
        if not self.is_owner(user):
            return [Reply(copy.OWNER_ONLY)]
        return [Reply(health_text(self.hub.health(), self.hub.clock(), user, self.hub.max_users))]

    async def remove(self, user: User, arg: str | None) -> list[Reply]:
        if not self.is_owner(user):
            return [Reply(copy.OWNER_ONLY)]
        everyone = self.registry.all_users()
        if arg is None or not arg.strip().isdigit() or not 1 <= int(arg) <= len(everyone):
            return [Reply(copy.REMOVE_USAGE)]
        target = everyone[int(arg) - 1]
        if target.telegram_id == user.telegram_id:
            return [Reply(copy.REMOVE_SELF)]
        # Positions shift when someone leaves, so the button names the person by ID.
        name = target.display_name or "?"
        host = urlsplit(target.canvas_base_url or "").hostname or "—"
        keyboard = (
            (
                Button(copy.BTN_REMOVE_YES.format(name=name)[:40], f"rm:{target.telegram_id}"),
                Button(copy.BTN_CANCEL, "rm:no"),
            ),
        )
        return [Reply(copy.REMOVE_CONFIRM.format(name=name, host=host), keyboard)]

    async def remove_confirmed(self, user: User, value: str) -> list[Reply]:
        if not self.is_owner(user):
            return [Reply(copy.OWNER_ONLY)]
        if not value.isdigit():
            return [Reply(copy.CANCELLED)]
        target = self.registry.get_user(int(value))
        if target is None:
            return [Reply(copy.REMOVE_GONE)]
        if target.telegram_id == user.telegram_id:
            return [Reply(copy.REMOVE_SELF)]
        with contextlib.suppress(NotifyError):
            notifier = self.hub.notifier_factory(target.telegram_id)
            text = copy.REMOVED_BY_OWNER_FEED if target.feed_mode else copy.REMOVED_BY_OWNER
            await notifier.send(RenderedMessage(text))
        await self.hub.remove(target.telegram_id)
        return [Reply(copy.REMOVED.format(name=target.display_name or "?"))]


def health_text(report: HealthReport, now: datetime, viewer: User, max_users: int) -> str:
    zone = ZoneInfo(viewer.tz or "UTC")
    last = report.last_tick
    if last is None:
        last_tick = copy.HEALTH_NEVER
    else:
        when = format_due(last, now, zone)
        last_tick = copy.HEALTH_LAST_TICK.format(when=when, ago=format_left(now - last))
    if not report.email_configured:
        email = copy.HEALTH_EMAIL_OFF
    elif report.email_failures > 0:
        email = copy.HEALTH_EMAIL_FAILING.format(count=report.email_failures)
    else:
        email = copy.HEALTH_EMAIL_OK
    if report.sync_problems == 0:
        sync = copy.HEALTH_SYNC_NONE
    else:
        sync = copy.HEALTH_SYNC.format(
            count=report.sync_problems,
            auth=report.auth_problems,
            other=report.sync_problems - report.auth_problems,
        )
    text = copy.HEALTH.format(
        version=__version__,
        uptime=format_left(now - report.started_at),
        active=report.users_active,
        onboarding=report.users_onboarding,
        max=max_users,
        last_tick=last_tick,
        disk=disk_label(report.disk),
        email=email,
        sync=sync,
        alerts=report.open_alerts,
    )
    if report.users_broken:
        text += copy.HEALTH_BROKEN.format(count=report.users_broken)
    if report.stuck:
        text += copy.HEALTH_STUCK.format(count=report.stuck)
    return text
