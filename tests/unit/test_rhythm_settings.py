"""Per-user reminder rhythm: storage, the /settings menu, copy and the running bot."""

from datetime import timedelta
from pathlib import Path

from canvas_tracker.domain.models import Cycle, Send, SendKind
from canvas_tracker.hub.registry import open_registry
from canvas_tracker.hub.signup import (
    INTERVAL_CHOICES,
    LOOKAHEAD_CHOICES,
    WINDOW_CHOICES,
    parse_rhythm,
)
from canvas_tracker.hub.tenant import user_settings
from canvas_tracker.render import copy
from canvas_tracker.render.alerts import render_send
from canvas_tracker.render.format import format_span
from canvas_tracker.render.views import StatusInfo, render_status
from canvas_tracker.sources.planner import WINDOW_AHEAD
from canvas_tracker.store.db import connect, migrate
from canvas_tracker.store.repo import Store
from tests.factories import NOW, make_item, make_settings, make_snapshot
from tests.hub_helpers import GOOD_TOKEN, HubEnv, build_hub, sign_up
from tests.integration.sim_env import ScenarioItem

H = timedelta(hours=1)


def texts(replies: list) -> list[str]:  # type: ignore[type-arg]
    return [r.text for r in replies]


def buttons(reply) -> list[tuple[str, str | None]]:  # type: ignore[no-untyped-def]
    return [(b.label, b.callback_data) for row in reply.keyboard for b in row]


# --- storage -------------------------------------------------------------------------


def test_cycles_remember_their_interval(tmp_path: Path) -> None:
    conn = connect(tmp_path / "u.db")
    migrate(conn)
    store = Store(conn)
    store.open_cycle(NOW, 2 * H)
    assert store.snapshot().cycle == Cycle(anchor=NOW, interval=2 * H)
    store.open_cycle(NOW + H, H, now=NOW + timedelta(minutes=10))  # a restart, in the future
    assert store.snapshot().cycle == Cycle(anchor=NOW + H, interval=H)
    closed = conn.execute("SELECT closed_at_utc FROM cycles WHERE id = 1").fetchone()[0]
    assert closed.startswith("2026-10-20T16:10")  # closed when it was replaced, not later


def test_a_cycle_from_before_the_update_gets_the_bot_default(tmp_path: Path) -> None:
    conn = connect(tmp_path / "u.db")
    migrate(conn)
    conn.execute("INSERT INTO cycles (anchor_utc) VALUES ('2026-10-20T16:00:00.000000Z')")
    store = Store(conn)
    assert store.snapshot().cycle == Cycle(anchor=NOW)
    store.fill_cycle_interval(2 * H)
    assert store.snapshot().cycle == Cycle(anchor=NOW, interval=2 * H)
    store.fill_cycle_interval(3 * H)  # only fills a missing value
    assert store.snapshot().cycle == Cycle(anchor=NOW, interval=2 * H)


def test_registry_rhythm_defaults_to_null_and_is_updatable(tmp_path: Path) -> None:
    reg = open_registry(tmp_path / "registry.db")
    reg.create_user(5, "Ana", now=NOW)
    user = reg.get_user(5)
    assert user is not None
    assert (
        user.reminder_interval_minutes,
        user.reminder_window_hours,
        user.digest_lookahead_days,
    ) == (None, None, None)
    reg.update_user(5, reminder_interval_minutes=0, reminder_window_hours=48)
    user = reg.get_user(5)
    assert user is not None
    assert (user.reminder_interval_minutes, user.reminder_window_hours) == (0, 48)


def test_user_settings_fall_back_to_the_bot_wide_rhythm(tmp_path: Path) -> None:
    reg = open_registry(tmp_path / "registry.db")
    reg.create_user(5, "Ana", now=NOW)
    reg.update_user(5, tz="America/Chicago", canvas_base_url="https://c.example.edu")
    user = reg.get_user(5)
    assert user is not None
    shared = {
        "reminder_interval": 3 * H,
        "reminder_window": 36 * H,
        "digest_lookahead": timedelta(days=10),
    }
    s = user_settings(user, shared)
    assert (s.reminder_interval, s.reminder_window, s.digest_lookahead) == (
        3 * H,
        36 * H,
        timedelta(days=10),
    )
    reg.update_user(
        5, reminder_interval_minutes=0, reminder_window_hours=12, digest_lookahead_days=21
    )
    user = reg.get_user(5)
    assert user is not None
    s = user_settings(user, shared)
    assert (s.reminder_interval, s.reminder_window, s.digest_lookahead) == (
        None,
        12 * H,
        timedelta(days=21),
    )


def test_impossible_stored_values_fall_back_to_the_default(tmp_path: Path) -> None:
    reg = open_registry(tmp_path / "registry.db")
    reg.create_user(5, "Ana", now=NOW)
    reg.update_user(
        5,
        tz="UTC",
        canvas_base_url="https://c.example.edu",
        reminder_interval_minutes=5,
        reminder_window_hours=0,
        digest_lookahead_days=-3,
    )
    user = reg.get_user(5)
    assert user is not None
    s = user_settings(user, {})
    assert (s.reminder_interval, s.reminder_window, s.digest_lookahead) == (
        2 * H,
        24 * H,
        timedelta(days=14),
    )


def test_choices_stay_inside_what_the_bot_supports() -> None:
    assert min(INTERVAL_CHOICES) * H >= timedelta(minutes=30)  # MIN_REMINDER_INTERVAL
    assert timedelta(days=max(LOOKAHEAD_CHOICES)) <= WINDOW_AHEAD  # Canvas is read 21 days ahead
    assert parse_rhythm("ri", "off") == 0
    assert parse_rhythm("ri", "60") == 60 and parse_rhythm("ri", "45") is None
    assert parse_rhythm("rw", "48") == 48 and parse_rhythm("rw", "-1") is None
    assert parse_rhythm("la", "21") == 21 and parse_rhythm("la", "60") is None
    assert parse_rhythm("zz", "1") is None
    assert all(parse_rhythm("rw", str(h)) == h for h in WINDOW_CHOICES)


# --- copy ------------------------------------------------------------------------------


def test_spans_read_naturally() -> None:
    assert format_span(H) == "1 hour"
    assert format_span(2 * H) == "2 hours"
    assert format_span(timedelta(minutes=90)) == "90 minutes"
    assert format_span(48 * H) == "48 hours"
    assert format_span(timedelta(days=14)) == "14 days"


def test_reminder_header_names_the_users_window() -> None:
    item = make_item(due_in=5 * H)
    send = Send("rem:2026-10-20T16:00Z:0", SendKind.REMINDER, (item.ref,))
    [msg] = render_send(send, make_snapshot([item]), NOW, make_settings(reminder_window=48 * H))
    assert msg.text.startswith("⏰ Due within 48 hours: 1 not submitted")


def test_status_says_when_repeating_reminders_are_off() -> None:
    info = StatusInfo(
        last_successful_sync_at=NOW,
        auth_failed_since=None,
        next_digest_at=NOW + 20 * H,
        next_slot_at=None,
        pause_until=None,
        version="x",
    )
    text = render_status(info, NOW, make_settings(reminder_interval=None)).text
    assert f"Next reminder: {copy.STATUS_SLOT_OFF}" in text
    assert copy.STATUS_REMINDERS_OFF in text
    on = render_status(info, NOW, make_settings()).text
    assert copy.STATUS_REMINDERS_ON in on and copy.STATUS_NO_SLOT in on


# --- /settings → ⏰ Reminders ------------------------------------------------------------


async def test_the_reminders_menu_shows_and_changes_the_rhythm(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    [settings] = env.signup.settings(user)
    assert "Reminders: every 2 hours, for work due within 24 hours" in settings.text
    assert "Morning list covers: the next 14 days" in settings.text
    assert ("⏰ Reminders", "set:rem") in buttons(settings)

    [menu] = env.signup.begin_edit(user, "rem")
    assert menu.text.startswith("⏰ Reminders\nRepeat: every 2 hours")
    options = buttons(menu)
    assert ("✓ Every 2 h", "su:ri:120") in options and ("Every 1 h", "su:ri:60") in options
    assert ("No repeats", "su:ri:off") in options
    assert ("✓ Within 24 h", "su:rw:24") in options and ("✓ 14-day list", "su:la:14") in options
    assert all(len((data or "").encode()) <= 64 for _label, data in options)

    [saved] = await env.signup.choice(user, "ri", "60")
    assert saved.text.startswith(f"{copy.SAVED}\n\n⏰ Reminders\nRepeat: every 1 hour")
    assert ("✓ Every 1 h", "su:ri:60") in buttons(saved)
    tenant = env.hub.tenant(1)
    assert tenant is not None and tenant.settings.reminder_interval == H

    user = env.hub.registry.get_user(1)
    assert user is not None
    await env.signup.choice(user, "rw", "48")
    await env.signup.choice(user, "la", "7")
    [off] = await env.signup.choice(user, "ri", "off")
    assert "Repeat: no repeats" in off.text and ("✓ No repeats", "su:ri:off") in buttons(off)
    tenant = env.hub.tenant(1)
    assert tenant is not None
    s = tenant.settings
    assert (s.reminder_interval, s.reminder_window, s.digest_lookahead) == (
        None,
        48 * H,
        timedelta(days=7),
    )
    user = env.hub.registry.get_user(1)
    assert user is not None
    [settings] = env.signup.settings(user)
    assert f"Reminders: {copy.RHYTHM_SHORT_OFF}" in settings.text
    assert copy.RHYTHM_OFF in env.signup.welcome(user).text


async def test_unknown_rhythm_values_change_nothing(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    for kind, value in (("ri", "1"), ("ri", "30"), ("rw", "1000"), ("la", "60"), ("la", "x")):
        [reply] = await env.signup.choice(user, kind, value)
        assert reply.text.startswith("⏰ Reminders")
    user = env.hub.registry.get_user(1)
    assert user is not None
    assert user.reminder_interval_minutes is None and user.reminder_window_hours is None
    assert user.digest_lookahead_days is None


async def test_rhythm_buttons_do_nothing_during_sign_up(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await env.signup.start(1, "Owner", None)
    user = env.hub.registry.get_user(1)
    assert user is not None
    replies = await env.signup.choice(user, "ri", "60")
    assert texts(replies) == [copy.ASK_URL]
    user = env.hub.registry.get_user(1)
    assert user is not None and user.reminder_interval_minutes is None


async def test_opening_the_menu_leaves_a_half_finished_edit(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    env.signup.begin_edit(user, "tz")
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step == "edit_tz"
    env.signup.begin_edit(user, "rem")
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step is None


async def test_sign_up_texts_use_the_real_rhythm(tmp_path: Path) -> None:
    """Regression: the intro and welcome hard-coded "every 2 hours / within 24 hours"."""
    env = build_hub(tmp_path)
    env.hub.shared = {"reminder_interval": 3 * H, "reminder_window": 12 * H}
    replies = await env.signup.start(1, "Owner", None)
    assert "a reminder every 3 hours for anything due within 12 hours" in replies[0].text
    for answer in ("school.instructure.com", GOOD_TOKEN):
        user = env.hub.registry.get_user(1)
        assert user is not None
        await env.signup.text(user, answer)
    for kind, value in (("tz", "America/Chicago"), ("dt", "07:00")):
        user = env.hub.registry.get_user(1)
        assert user is not None
        await env.signup.choice(user, kind, value)
    user = env.hub.registry.get_user(1)
    assert user is not None
    [done] = await env.signup.choice(user, "qh", "off")
    assert "When something is due within 12 hours, you get a reminder every 3 hours" in done.text
    assert "/settings and tap ⏰ Reminders" in done.text
    user = env.hub.registry.get_user(1)
    assert user is not None
    welcome = env.signup.welcome(user).text
    assert "every 3 hours" in welcome and "within 12 hours" in welcome


# --- the running bot -------------------------------------------------------------------


def _due_in(hours: float) -> list[dict]:  # type: ignore[type-arg]
    item = ScenarioItem(31, "Lab report", lambda _t: NOW + timedelta(hours=hours))
    data = item.planner_json(NOW)
    assert data is not None
    return [data]


def _reminders(env: HubEnv, telegram_id: int) -> list[str]:
    return [m.text for m in env.notifiers[telegram_id].sent if m.text.startswith("⏰")]


async def test_changing_the_interval_mid_cycle_never_repeats_a_reminder(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    env.canvas.items = {GOOD_TOKEN: _due_in(9)}
    await sign_up(env, 1)
    await env.hub.tick_all()
    assert len(_reminders(env, 1)) == 1  # 11:00 Chicago: the cycle opens

    env.clock.now = NOW + 2 * H
    await env.hub.tick_all()
    assert len(_reminders(env, 1)) == 2  # 13:00

    env.clock.now = NOW + 2 * H + timedelta(minutes=10)
    user = env.hub.registry.get_user(1)
    assert user is not None
    await env.signup.choice(user, "ri", "60")  # rebuilds the tenant and ticks at once
    await env.hub.tick_all()
    assert len(_reminders(env, 1)) == 2  # the 13:00 reminder is not sent again

    env.clock.now = NOW + 3 * H
    await env.hub.tick_all()
    assert len(_reminders(env, 1)) == 3  # 14:00, an hour after the last one

    env.clock.now = NOW + 3 * H + timedelta(minutes=30)
    await env.hub.tick_all()
    env.clock.now = NOW + 4 * H
    await env.hub.tick_all()
    assert len(_reminders(env, 1)) == 4  # 15:00

    user = env.hub.registry.get_user(1)
    assert user is not None
    await env.signup.choice(user, "ri", "off")
    for minutes in (60, 120, 180):
        env.clock.now = NOW + 4 * H + timedelta(minutes=minutes)
        await env.hub.tick_all()
    assert len(_reminders(env, 1)) == 4  # off: no more repeats


async def test_starting_a_tenant_records_the_default_on_an_old_open_cycle(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await env.hub.tick_all()
    tenant = env.hub.tenant(1)
    assert tenant is not None
    tenant.store.conn.execute("UPDATE cycles SET closed_at_utc = 'x' WHERE closed_at_utc IS NULL")
    tenant.store.conn.execute(
        "INSERT INTO cycles (anchor_utc) VALUES ('2026-10-20T16:00:00.000000Z')"
    )
    rebuilt = await env.hub.refresh(1)
    assert rebuilt is not None
    assert rebuilt.store.snapshot().cycle == Cycle(anchor=NOW, interval=2 * H)
