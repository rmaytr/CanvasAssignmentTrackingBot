from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canvas_tracker.domain.models import SendKind
from canvas_tracker.store.db import connect, migrate
from canvas_tracker.store.repo import LAST_TICK_AT, Store
from tests.factories import NOW


@pytest.fixture
def store(tmp_path: Path) -> Store:
    conn = connect(tmp_path / "bot.db")
    migrate(conn)
    return Store(conn)


def test_migrate_is_idempotent_and_uses_wal(tmp_path: Path) -> None:
    conn = connect(tmp_path / "bot.db")
    assert migrate(conn) == 2
    assert migrate(conn) == 2
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"items", "courses", "assignment_groups", "cycles", "notifications", "state"} <= tables


def test_claim_sequence(store: Store) -> None:
    k = "rem:2026-10-20T16:00Z:0"
    assert store.claim(k, SendKind.REMINDER, ["assignment-1"], NOW) is True
    assert store.claim(k, SendKind.REMINDER, ["assignment-1"], NOW + timedelta(minutes=1)) is False
    assert store.claim(k, SendKind.REMINDER, ["assignment-1"], NOW + timedelta(minutes=3)) is True
    store.mark_sent(k, NOW + timedelta(minutes=3), message_id=42)
    assert store.claim(k, SendKind.REMINDER, ["assignment-1"], NOW + timedelta(hours=1)) is False


def test_failed_send_can_be_reclaimed_after_two_minutes(store: Store) -> None:
    k = "digest:2026-10-20"
    assert store.claim(k, SendKind.DIGEST, [], NOW)
    store.mark_failed(k, "NetworkError")
    assert store.claim(k, SendKind.DIGEST, [], NOW + timedelta(minutes=1)) is False
    assert store.claim(k, SendKind.DIGEST, [], NOW + timedelta(minutes=3)) is True


def test_time_state_round_trips_and_deletes(store: Store) -> None:
    t = datetime(2026, 10, 20, 16, 0, 0, 123456, tzinfo=UTC)
    store.set_time(LAST_TICK_AT, t)
    got = store.get_time(LAST_TICK_AT)
    assert got == t and got is not None and got.utcoffset() == timedelta(0)
    store.set_time(LAST_TICK_AT, None)
    assert store.get_time(LAST_TICK_AT) is None
    store.set_state("x", "1")
    assert store.get_state("x") == "1"


def test_set_time_rejects_naive(store: Store) -> None:
    with pytest.raises(ValueError):
        store.set_time(LAST_TICK_AT, datetime(2026, 10, 20, 16, 0))  # noqa: DTZ001


def test_parts_sent_survive_a_failed_attempt(store: Store) -> None:  # review I5
    k = "rem:2026-10-20T16:00Z:0"
    assert store.claim(k, SendKind.REMINDER, [], NOW)
    assert store.parts_sent(k) == 0
    store.mark_part_sent(k, 1)
    store.mark_failed(k, "NetworkError")
    assert store.claim(k, SendKind.REMINDER, [], NOW + timedelta(minutes=3))
    assert store.parts_sent(k) == 1
