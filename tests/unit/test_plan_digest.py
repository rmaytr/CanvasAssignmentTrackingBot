from datetime import UTC, datetime, timedelta

from canvas_tracker.domain.models import SendKind
from canvas_tracker.planning.digest import plan_digest
from tests.factories import make_item, make_settings, make_snapshot

S = make_settings()  # America/New_York, digest 08:00, grace until 12:00
OCT20_0800 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def test_not_before_digest_time() -> None:
    assert plan_digest(OCT20_0800 - timedelta(seconds=1), make_snapshot(), S) is None


def test_due_at_digest_time() -> None:
    send = plan_digest(OCT20_0800, make_snapshot(), S)
    assert send is not None
    assert (send.key, send.kind) == ("digest:2026-10-20", SendKind.DIGEST)


def test_grace_window_ends_at_noon_local() -> None:
    assert plan_digest(datetime(2026, 10, 20, 15, 59, tzinfo=UTC), make_snapshot(), S) is not None
    assert plan_digest(datetime(2026, 10, 20, 16, 0, tzinfo=UTC), make_snapshot(), S) is None


def test_not_resent_once_sent() -> None:
    snap = make_snapshot(sent_keys=frozenset({"digest:2026-10-20"}))
    assert plan_digest(OCT20_0800, snap, S) is None


def test_item_refs_list_only_urgent_items() -> None:
    urgent = make_item(plannable_id=101, due_at=OCT20_0800 + timedelta(hours=5))
    later = make_item(plannable_id=102, due_at=OCT20_0800 + timedelta(days=3))
    send = plan_digest(OCT20_0800, make_snapshot([later, urgent]), S)
    assert send is not None and send.item_refs == ("assignment-101",)


def test_fall_back_day_first_due_instant() -> None:
    assert plan_digest(datetime(2026, 11, 1, 12, 59, tzinfo=UTC), make_snapshot(), S) is None
    send = plan_digest(datetime(2026, 11, 1, 13, 0, tzinfo=UTC), make_snapshot(), S)
    assert send is not None and send.key == "digest:2026-11-01"
