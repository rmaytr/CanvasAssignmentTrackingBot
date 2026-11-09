"""Track 4: owner alerts, /health and the hourly summary log line."""

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from canvas_tracker import __version__
from canvas_tracker.domain.models import SendKind
from canvas_tracker.hub.monitor import (
    ALERT_REPEAT,
    ALERTS_STATE_KEY,
    DISK_CHECK_EVERY,
    EMAIL_FAILURES_TO_ALERT,
    STUCK_AFTER,
    SYNC_FAILING_AFTER,
    AlertState,
    Monitor,
    Watched,
    decide,
    disk_label,
    disk_low,
    failing_since,
)
from canvas_tracker.hub.registry import HUB_LAST_TICK_AT
from canvas_tracker.notify.base import FakeNotifier, NotifyError
from canvas_tracker.render import copy
from canvas_tracker.render.format import format_bytes
from canvas_tracker.render.message import RenderedMessage
from canvas_tracker.store.repo import (
    AUTH_FAILED_SINCE,
    LAST_SUCCESSFUL_SYNC_AT,
    LAST_SYNC_ERROR,
    LAST_TICK_AT,
)
from tests.factories import NOW
from tests.hub_helpers import GOOD_TOKEN, FakeDisk, HubEnv, build_hub, sign_up
from tests.unit.test_loop import build as build_runtime

H = timedelta(hours=1)
MB = 1024 * 1024
GB = 1024 * MB


async def settled(env: HubEnv) -> None:
    """Let the first ticks that sign-up started finish."""
    for tenant in list(env.hub.tenants.values()):
        if tenant.running is not None:
            await tenant.running


async def two_users(tmp_path: Path, **kw: object) -> HubEnv:
    env = build_hub(tmp_path, **kw)  # type: ignore[arg-type]
    await sign_up(env, 1, name="Owner")
    await sign_up(env, 2, name="Mia <3")
    await settled(env)
    return env


def failing(env: HubEnv, telegram_id: int, error: str = "CanvasUnavailable") -> None:
    store = env.hub.tenants[telegram_id].store
    store.set_state(LAST_SYNC_ERROR, error)


def owner_texts(env: HubEnv) -> list[str]:
    return [m.text for m in env.notifiers[1].sent]


# --- pure rules ----------------------------------------------------------------------


def test_decide_alerts_once_per_day_and_resolves_once() -> None:
    action, state = decide(NOW, True, AlertState())
    assert action == "alert" and state == AlertState(NOW, active=True)
    assert decide(NOW + H, True, state) == (None, state)  # still failing: quiet
    action, repeat = decide(NOW + ALERT_REPEAT, True, state)
    assert action == "alert" and repeat.alerted_at == NOW + ALERT_REPEAT  # a day later
    action, resolved = decide(NOW + 2 * H, False, state)
    assert action == "resolved" and resolved == AlertState(NOW, active=False)
    assert decide(NOW + 3 * H, False, resolved) == (None, resolved)
    # it flaps back within 24 h of the last alert: no second alert yet
    assert decide(NOW + 4 * H, True, resolved) == (None, resolved)
    assert decide(NOW + ALERT_REPEAT, True, resolved)[0] == "alert"


def test_failing_since_ignores_auth_and_uses_the_last_good_sync() -> None:
    ok = Watched(1, "A", last_ok=NOW - 7 * H)
    assert failing_since(ok, None) is None  # no error
    broken = Watched(1, "A", last_ok=NOW - 7 * H, last_error="CanvasUnavailable")
    assert failing_since(broken, NOW) == NOW - 7 * H
    never = Watched(1, "A", last_error="CanvasUnavailable")
    assert failing_since(never, NOW - H) == NOW - H
    auth = Watched(1, "A", last_ok=NOW - 9 * H, last_error="CanvasAuthError", auth_failed=True)
    assert failing_since(auth, NOW) is None


def test_disk_is_low_under_200_mb_or_5_percent() -> None:
    assert not disk_low(FakeDisk(total=100 * GB, free=50 * GB))
    assert disk_low(FakeDisk(total=100 * GB, free=4 * GB))  # 4 %
    assert disk_low(FakeDisk(total=1 * GB, free=150 * MB))  # 150 MB
    assert not disk_low(FakeDisk(total=0, free=0))  # nonsense from the OS: no alert
    assert disk_label(None) == copy.HEALTH_UNKNOWN
    assert disk_label(FakeDisk(total=20 * GB, free=5 * GB)) == "5.0 GB free of 20 GB (25%)"
    assert disk_label(FakeDisk(total=20 * GB, free=100 * MB)).endswith(copy.HEALTH_DISK_LOW)


def test_format_bytes() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(512 * 1024) == "512 KB"
    assert format_bytes(150 * MB) == "150 MB"
    assert format_bytes(int(1.5 * GB)) == "1.5 GB"
    assert format_bytes(20 * GB) == "20 GB"
    assert format_bytes(3 * 1024 * GB) == "3.0 TB"


def test_disk_is_read_at_most_every_ten_minutes(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    monitor = env.hub.monitor
    reading = monitor.disk()
    assert reading is not None and (reading.total, reading.free) == (env.disk.total, env.disk.free)
    assert env.disk.calls == 1
    env.clock.now = NOW + DISK_CHECK_EVERY - timedelta(seconds=1)
    monitor.disk()
    assert env.disk.calls == 1
    env.clock.now = NOW + DISK_CHECK_EVERY
    monitor.disk()
    assert env.disk.calls == 2
    monitor.disk(fresh=True)  # /health always reads it
    assert env.disk.calls == 3
    env.disk.fail = True
    assert monitor.disk(fresh=True) is None


# --- alerts through a real hub -------------------------------------------------------


async def test_sync_failing_for_six_hours_alerts_the_owner_once(tmp_path: Path) -> None:
    env = await two_users(tmp_path)
    store = env.hub.tenants[2].store
    failing(env, 2)
    store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - SYNC_FAILING_AFTER + timedelta(minutes=1))
    assert await env.hub.watch() == []  # not six hours yet
    env.clock.now = NOW + timedelta(minutes=1)
    [alert] = await env.hub.watch()
    assert alert == owner_texts(env)[-1]
    assert "Mia &lt;3 (Telegram ID 2)" in alert and "6 h" in alert
    assert copy.MONITOR_REASON_UNREACHABLE in alert
    for secret in (GOOD_TOKEN, "school.instructure.com"):
        assert secret not in alert
    env.clock.now = NOW + 5 * H
    assert await env.hub.watch() == []  # at most once per 24 h
    store.set_state(LAST_SYNC_ERROR, None)
    store.set_time(LAST_SUCCESSFUL_SYNC_AT, env.clock.now)
    assert await env.hub.watch() == [
        copy.MONITOR_SYNC_RESOLVED.format(name="Mia &lt;3", telegram_id=2)
    ]
    assert await env.hub.watch() == []


async def test_user_who_never_synced_alerts_six_hours_after_first_seen(tmp_path: Path) -> None:
    env = await two_users(tmp_path)
    store = env.hub.tenants[2].store
    store.conn.execute("DELETE FROM state WHERE key = ?", (LAST_SUCCESSFUL_SYNC_AT,))
    failing(env, 2, "CanvasHostRefused")
    assert await env.hub.watch() == []
    env.clock.now = NOW + SYNC_FAILING_AFTER
    [alert] = await env.hub.watch()
    assert copy.MONITOR_REASON_HOST in alert


async def test_rejected_token_never_alerts_the_owner(tmp_path: Path) -> None:
    env = await two_users(tmp_path)
    store = env.hub.tenants[2].store
    failing(env, 2, "CanvasAuthError")
    store.set_time(AUTH_FAILED_SINCE, NOW - 10 * H)
    store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - 10 * H)
    assert await env.hub.watch() == []
    report = env.hub.health()
    assert (report.sync_problems, report.auth_problems) == (1, 1)


async def test_alert_state_survives_a_restart(tmp_path: Path) -> None:
    env = await two_users(tmp_path)
    failing(env, 2)
    env.hub.tenants[2].store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - 7 * H)
    assert len(await env.hub.watch()) == 1
    saved = json.loads(env.hub.registry.get_state(ALERTS_STATE_KEY) or "{}")
    assert saved["sync:2"]["active"] is True
    restarted = Monitor(clock=env.clock, registry=env.hub.registry, data_dir=tmp_path)
    env.hub.monitor = restarted
    assert await env.hub.watch() == []  # the owner already knows
    env.hub.registry.set_state(ALERTS_STATE_KEY, "not json")
    assert Monitor(clock=env.clock, registry=env.hub.registry, data_dir=tmp_path).open_alerts == 0


async def test_undelivered_alert_is_tried_again(tmp_path: Path) -> None:
    env = await two_users(tmp_path)
    env.notifiers[1].fail_times = 1
    failing(env, 2)
    env.hub.tenants[2].store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - 7 * H)
    assert await env.hub.watch() == []
    assert len(await env.hub.watch()) == 1


async def test_no_owner_yet_means_no_alerts_until_there_is_one(tmp_path: Path) -> None:
    env = build_hub(tmp_path, owner=None, disk=FakeDisk(total=10 * GB, free=10 * MB))
    assert await env.hub.watch() == []
    env.hub.owner_env_id = 1
    [alert] = await env.hub.watch()
    assert alert.startswith("⚠️ The data volume is nearly full: 10 MB free of 10 GB")


async def test_removed_user_leaves_no_alert_behind(tmp_path: Path) -> None:
    env = await two_users(tmp_path)
    failing(env, 2)
    env.hub.tenants[2].store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - 7 * H)
    assert len(await env.hub.watch()) == 1
    await env.hub.remove(2)
    assert await env.hub.watch() == []  # no "resolved" for someone who left
    assert env.hub.monitor.open_alerts == 0


async def test_tenant_rebuilt_mid_check_keeps_its_alert(tmp_path: Path) -> None:
    env = await two_users(tmp_path)
    failing(env, 2)
    env.hub.tenants[2].store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - 7 * H)
    assert len(await env.hub.watch()) == 1
    tenant = env.hub.tenants.pop(2)  # as during /settings: the old tenant is closing
    assert await env.hub.watch() == []
    assert env.hub.monitor.open_alerts == 1
    env.hub.tenants[2] = tenant
    assert await env.hub.watch() == []  # no repeat of the same alert


async def test_email_failures_in_a_row_alert_and_recover(tmp_path: Path) -> None:
    env = await two_users(tmp_path, email=True)
    factory = env.hub.mailer_factory
    assert factory is not None
    mailer = factory(lambda: "mia@school.edu")
    env.outbox.fail = True
    for _ in range(EMAIL_FAILURES_TO_ALERT):
        with pytest.raises(NotifyError):
            await mailer.send(RenderedMessage("hi", subject="hi"))
    [alert] = await env.hub.watch()
    assert alert == copy.MONITOR_EMAIL_FAILING.format(count=EMAIL_FAILURES_TO_ALERT)
    assert "mia@school.edu" not in alert
    assert env.hub.health().email_failures == EMAIL_FAILURES_TO_ALERT
    env.outbox.fail = False
    await mailer.send(RenderedMessage("hi", subject="hi"))
    assert await env.hub.watch() == [copy.MONITOR_EMAIL_RESOLVED]


async def test_confirmation_code_failures_count_too(tmp_path: Path) -> None:
    env = await two_users(tmp_path, email=True)
    env.outbox.fail = True
    user = env.hub.registry.get_user(2)
    assert user is not None
    await env.signup.email_command(user, "mia@school.edu")
    assert env.hub.monitor.email_failures == 1


async def test_low_disk_alerts_and_recovers(tmp_path: Path) -> None:
    disk = FakeDisk(total=10 * GB, free=100 * MB)
    env = await two_users(tmp_path, disk=disk)
    [alert] = await env.hub.watch()
    assert "100 MB free of 10 GB" in alert
    disk.free = 5 * GB
    assert await env.hub.watch() == []  # the cached reading is still "low": no flip yet
    env.clock.now = NOW + DISK_CHECK_EVERY
    assert await env.hub.watch() == [
        copy.MONITOR_DISK_RESOLVED.format(free="5.0 GB", total="10 GB")
    ]


async def test_failed_disk_check_keeps_the_disk_alert_open(tmp_path: Path) -> None:
    disk = FakeDisk(total=10 * GB, free=100 * MB)
    env = await two_users(tmp_path, disk=disk)
    assert len(await env.hub.watch()) == 1
    disk.fail = True
    env.clock.now = NOW + DISK_CHECK_EVERY
    assert await env.hub.watch() == []  # unknown is not "resolved"
    assert env.hub.monitor.open_alerts == 1


async def test_tick_running_over_ten_minutes_alerts(tmp_path: Path) -> None:
    env = await two_users(tmp_path)
    tenant = env.hub.tenants[2]
    hang = asyncio.Event()

    async def stuck() -> None:
        await hang.wait()

    tenant._task = asyncio.create_task(stuck())
    tenant.tick_started_at = NOW
    env.clock.now = NOW + STUCK_AFTER - timedelta(seconds=1)
    assert await env.hub.watch() == []
    env.clock.now = NOW + STUCK_AFTER
    [alert] = await env.hub.watch()
    assert "Mia &lt;3 (Telegram ID 2)" in alert and "10 min" in alert
    assert env.hub.health().stuck == 1
    hang.set()
    await tenant._task
    assert await env.hub.watch() == [
        copy.MONITOR_STUCK_RESOLVED.format(name="Mia &lt;3", telegram_id=2)
    ]


async def test_monitoring_failure_never_costs_a_user_their_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = await two_users(tmp_path)

    async def broken(*_a: object, **_k: object) -> list[str]:
        raise RuntimeError("monitor bug")

    monkeypatch.setattr(env.hub.monitor, "check", broken)
    env.clock.now = NOW + timedelta(minutes=5)
    await env.hub.tick_all(wait_s=5)
    assert env.hub.registry.get_time(HUB_LAST_TICK_AT) == env.clock.now
    for telegram_id in (1, 2):
        assert env.hub.tenants[telegram_id].store.get_time(LAST_TICK_AT) == env.clock.now


async def test_tick_all_runs_the_monitor(tmp_path: Path) -> None:
    disk = FakeDisk(total=10 * GB, free=100 * MB)
    env = await two_users(tmp_path, disk=disk)
    await env.hub.tick_all(wait_s=5)
    assert owner_texts(env)[-1].startswith("⚠️ The data volume is nearly full")
    assert all(not m.text.startswith("⚠️ The data") for m in env.notifiers[2].sent)


# --- counts and the hourly summary ---------------------------------------------------


async def test_runtime_reports_every_send_and_survives_a_broken_report() -> None:
    reports: list[tuple[SendKind, bool]] = []
    runtime, _store, _sync, _notifier, clock = build_runtime(notifier=FakeNotifier(fail_times=1))
    runtime.on_send = lambda kind, ok: reports.append((kind, ok))
    await runtime.tick()
    assert reports == [(SendKind.REMINDER, False)]
    clock.now = NOW + timedelta(minutes=3)
    await runtime.tick()
    assert reports[-1] == (SendKind.REMINDER, True)

    def explode(_kind: SendKind, _ok: bool) -> None:
        raise RuntimeError("bug")

    runtime2, store2, _s, notifier2, _c = build_runtime()
    runtime2.on_send = explode
    await runtime2.tick()
    assert len(notifier2.sent) == 1
    assert store2.conn.execute("SELECT status FROM notifications").fetchone()[0] == "sent"


async def test_hourly_summary_has_counts_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = await two_users(tmp_path)
    monitor = env.hub.monitor
    monitor.record_send(SendKind.DIGEST, True)
    monitor.record_send(SendKind.DIGEST, True)
    monitor.record_send(SendKind.REMINDER, False)
    failing(env, 2)
    await env.signup.start(3, "Signing Up", env.hub.registry.create_invite(NOW))
    caplog.set_level(logging.INFO, logger="canvas_tracker.hub.monitor")
    await env.hub.watch()
    assert not [r for r in caplog.records if r.getMessage() == "hourly summary"]
    env.clock.now = NOW + H
    await env.hub.watch()
    [record] = [r for r in caplog.records if r.getMessage() == "hourly summary"]
    fields = vars(record)
    assert fields["users_active"] == 2 and fields["users_signing_up"] == 1
    assert fields["sends"] == {"digest": 2} and fields["send_failures"] == {"reminder": 1}
    assert fields["sync_problems"] == 1 and fields["period_minutes"] == 60
    assert fields["disk_free_mb"] == 50 * 1024
    flat = json.dumps({k: fields[k] for k in fields if k not in ("args", "msg")}, default=str)
    for private in ("Mia", "Owner", "Signing Up", "school.instructure.com", GOOD_TOKEN):
        assert private not in flat
    # the counters start again
    env.clock.now = NOW + 2 * H
    await env.hub.watch()
    last = [r for r in caplog.records if r.getMessage() == "hourly summary"][-1]
    assert vars(last)["sends"] == {}


# --- /health -------------------------------------------------------------------------


async def test_health_for_the_owner_only(tmp_path: Path) -> None:
    env = await two_users(tmp_path, email=True)
    await env.signup.start(3, "Signing Up", env.hub.registry.create_invite(NOW))
    failing(env, 2)
    await env.hub.tick_all(wait_s=5)  # the hub's heartbeat; Mia's sync clears her error
    failing(env, 2)
    env.clock.now = NOW + 3 * H + timedelta(minutes=5)
    owner = env.hub.registry.get_user(1)
    friend = env.hub.registry.get_user(2)
    assert owner is not None and friend is not None
    [reply] = env.signup.health(owner)
    lines = reply.text.split("\n")
    assert lines[0] == "🩺 Health"
    assert f"Version: {__version__}" in lines
    assert "Up for: 3 h 5 m" in lines
    assert "Users: 2 active, 1 signing up (max 25)" in lines
    assert "Last check: today 11:00 AM (3 h 5 m ago)" in lines  # NOW in Chicago
    assert "Disk: 50 GB free of 100 GB (50%)" in lines
    assert "Email: set up" in lines
    assert "Sync problems: 1 (0 token rejected, 1 can't sync)" in lines
    assert "Open alerts: 0" in lines
    assert "Mia" not in reply.text
    assert env.signup.health(friend)[0].text == copy.OWNER_ONLY


async def test_health_mentions_broken_and_missing_things(tmp_path: Path) -> None:
    env = await two_users(tmp_path, disk=FakeDisk(fail=True))
    env.hub.broken = {9}
    owner = env.hub.registry.get_user(1)
    assert owner is not None
    text = env.signup.health(owner)[0].text
    assert "Last check: " + copy.HEALTH_NEVER in text
    assert "Disk: " + copy.HEALTH_UNKNOWN in text
    assert "Email: " + copy.HEALTH_EMAIL_OFF in text
    assert "Sync problems: none" in text
    assert text.endswith(copy.HEALTH_BROKEN.format(count=1))


def test_help_lists_health_for_the_owner() -> None:
    assert "/health" in copy.HELP_OWNER
    assert "/health" not in copy.HELP
