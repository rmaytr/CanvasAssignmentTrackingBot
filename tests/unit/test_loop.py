import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from canvas_tracker.domain.models import Item
from canvas_tracker.notify.base import FakeNotifier
from canvas_tracker.runtime.loop import Runtime
from canvas_tracker.runtime.sync import SyncOutcome
from canvas_tracker.store.repo import (
    AUTH_FAILED_SINCE,
    LAST_SUCCESSFUL_SYNC_AT,
    LAST_SYNC_ATTEMPT_AT,
    LAST_TICK_AT,
    Store,
)
from tests.factories import NOW, make_item, make_settings
from tests.store_helpers import new_store


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeSync:
    def __init__(self, store: Store, items: Callable[[datetime], list[Item]]) -> None:
        self.store = store
        self.items = items
        self.calls: list[datetime] = []
        self.outcome = SyncOutcome.OK

    async def sync(self, now: datetime) -> SyncOutcome:
        self.calls.append(now)
        self.store.set_time(LAST_SYNC_ATTEMPT_AT, now)
        if self.outcome is SyncOutcome.AUTH_FAILED:
            if self.store.get_time(AUTH_FAILED_SINCE) is None:
                self.store.set_time(AUTH_FAILED_SINCE, now)
            return self.outcome
        if self.outcome is SyncOutcome.UNAVAILABLE:
            return self.outcome
        self.store.upsert_items(self.items(now), now)
        self.store.set_time(LAST_SUCCESSFUL_SYNC_AT, now)
        self.store.set_time(AUTH_FAILED_SINCE, None)
        return self.outcome

    async def enrich(self, now: datetime) -> SyncOutcome:
        return SyncOutcome.OK


ITEM = make_item(plannable_id=1, due_in=timedelta(hours=10))


def build(
    items: Callable[[datetime], list[Item]] = lambda _t: [ITEM],
    notifier: FakeNotifier | None = None,
    paired: bool = True,
    token: Callable[[], str] = lambda: "tok",
) -> tuple[Runtime, Store, FakeSync, FakeNotifier, Clock]:
    store = new_store()
    clock = Clock()
    fake_sync = FakeSync(store, items)
    fake_notifier = notifier or FakeNotifier()
    runtime = Runtime(
        store=store,
        sync=fake_sync,
        notifier=fake_notifier,
        settings=make_settings(),
        clock=clock,
        can_send=lambda: paired,
        token=token,
    )
    return runtime, store, fake_sync, fake_notifier, clock


async def test_first_tick_opens_cycle_and_sends_one_reminder() -> None:
    runtime, store, _sync, notifier, clock = build()
    await runtime.tick()
    assert len(notifier.sent) == 1 and notifier.sent[0].text.startswith("⏰")
    snap = store.snapshot()
    assert snap.cycle is not None and snap.cycle.anchor == NOW
    assert store.get_time(LAST_TICK_AT) == NOW
    clock.now = NOW + timedelta(seconds=60)
    await runtime.tick()
    assert len(notifier.sent) == 1


async def test_stale_data_is_resynced_before_sending() -> None:
    submitted_from = NOW

    def items(now: datetime) -> list[Item]:
        return [replace(ITEM, submitted=now >= submitted_from)]

    runtime, store, fake_sync, notifier, _clock = build(items)
    store.upsert_items([ITEM], NOW - timedelta(minutes=6))
    store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - timedelta(minutes=6))
    store.set_time(LAST_SYNC_ATTEMPT_AT, NOW - timedelta(minutes=6))  # cadence says not due yet
    await runtime.tick()
    assert fake_sync.calls == [NOW]
    assert notifier.sent == []


async def test_failed_send_is_retried_on_a_later_tick() -> None:
    runtime, store, _sync, notifier, clock = build(notifier=FakeNotifier(fail_times=1))
    await runtime.tick()
    status = store.conn.execute("SELECT status FROM notifications").fetchone()[0]
    assert status == "failed" and notifier.sent == []
    clock.now = NOW + timedelta(minutes=3)
    await runtime.tick()
    assert len(notifier.sent) == 1
    assert store.conn.execute("SELECT status FROM notifications").fetchone()[0] == "sent"


async def test_unpaired_bot_claims_nothing() -> None:
    runtime, store, _sync, notifier, _clock = build(paired=False)
    await runtime.tick()
    assert store.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0
    assert notifier.sent == []


async def test_auth_failure_waits_six_hours_or_a_new_token() -> None:
    token = {"value": "old"}
    runtime, _store, fake_sync, _notifier, clock = build(token=lambda: token["value"])
    fake_sync.outcome = SyncOutcome.AUTH_FAILED
    await runtime.tick()
    assert fake_sync.calls == [NOW]
    clock.now = NOW + timedelta(hours=5, minutes=59)
    await runtime.tick()
    assert len(fake_sync.calls) == 1
    clock.now = NOW + timedelta(hours=6)
    await runtime.tick()
    assert len(fake_sync.calls) == 2
    token["value"] = "new"
    clock.now = NOW + timedelta(hours=6, minutes=11)
    await runtime.tick()
    assert len(fake_sync.calls) == 3


async def test_run_forever_survives_a_failing_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, *_ = build()
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "tick", flaky)
    task = asyncio.create_task(runtime.run_forever(interval_s=0))
    for _ in range(50):
        await asyncio.sleep(0)
        if calls >= 3:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls >= 3


async def test_a_crashing_sync_never_blocks_sending() -> None:  # review I1
    runtime, store, fake_sync, notifier, _clock = build()

    async def crash(now: datetime) -> SyncOutcome:
        raise RuntimeError("boom")

    fake_sync.sync = crash  # type: ignore[method-assign]
    store.upsert_items([ITEM], NOW - timedelta(minutes=30))
    store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - timedelta(minutes=30))
    await runtime.tick()
    assert len(notifier.sent) == 1
    assert store.get_time(LAST_TICK_AT) == NOW


async def test_enrichment_only_after_a_successful_sync() -> None:  # review I3
    runtime, _store, fake_sync, _notifier, _clock = build()
    enriched: list[datetime] = []

    async def enrich(now: datetime) -> SyncOutcome:
        enriched.append(now)
        return SyncOutcome.OK

    fake_sync.enrich = enrich  # type: ignore[method-assign]
    fake_sync.outcome = SyncOutcome.UNAVAILABLE
    await runtime.tick()
    assert enriched == []


async def test_nags_from_stale_data_carry_a_stale_note() -> None:  # review I4
    runtime, store, fake_sync, notifier, _clock = build()
    store.upsert_items([ITEM], NOW - timedelta(minutes=30))
    store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - timedelta(minutes=30))
    fake_sync.outcome = SyncOutcome.UNAVAILABLE
    await runtime.tick()
    assert len(notifier.sent) == 1 and "⚠️ Based on Canvas data from" in notifier.sent[0].text


async def test_fresh_nags_have_no_stale_note() -> None:
    runtime, _store, _fake_sync, notifier, _clock = build()
    await runtime.tick()
    assert "Based on Canvas data" not in notifier.sent[0].text


class FailSecondPartOnce:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.calls = 0

    async def send(self, msg: object) -> int | None:
        from canvas_tracker.notify.base import NotifyError

        self.calls += 1
        if self.calls == 2:
            raise NotifyError("NetworkError")
        self.sent.append(getattr(msg, "text", ""))
        return self.calls


async def test_retry_resumes_after_the_last_part_sent() -> None:  # review I5
    items = [
        make_item(plannable_id=i, title=f"Task {i}", due_in=timedelta(hours=1, minutes=i))
        for i in range(1, 41)
    ]
    notifier = FailSecondPartOnce()
    runtime, store, _sync, _fake, clock = build(lambda _t: items)
    runtime.notifier = notifier
    await runtime.tick()
    assert len(notifier.sent) == 1
    clock.now = NOW + timedelta(minutes=3)
    await runtime.tick()
    assert len(notifier.sent) == 2
    assert notifier.sent[0] != notifier.sent[1]
    assert store.conn.execute("SELECT status FROM notifications").fetchone()[0] == "sent"


def test_ticks_align_to_one_second_past_each_minute() -> None:  # review Minor 1 (re-graded)
    from canvas_tracker.runtime.loop import next_tick_delay

    assert next_tick_delay(datetime(2026, 10, 20, 16, 0, 30, tzinfo=NOW.tzinfo)) == 31.0
    assert next_tick_delay(datetime(2026, 10, 20, 16, 0, 59, 500000, tzinfo=NOW.tzinfo)) == 1.5
    assert next_tick_delay(datetime(2026, 10, 20, 16, 0, 1, tzinfo=NOW.tzinfo)) == 60.0
