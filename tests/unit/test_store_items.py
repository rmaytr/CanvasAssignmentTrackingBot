from datetime import timedelta

import pytest

from canvas_tracker.domain.models import (
    AssignmentDetail,
    AssignmentGroup,
    Course,
    Cycle,
    Enrichment,
    Item,
    SendKind,
)
from canvas_tracker.store.repo import PAUSE_UNTIL, Store
from tests.factories import NOW, make_item
from tests.store_helpers import new_store


@pytest.fixture
def store() -> Store:
    return new_store()


def only(store: Store) -> Item:
    [item] = store.snapshot().items
    return item


def test_upsert_round_trips_canvas_fields(store: Store) -> None:
    item = make_item(
        plannable_id=5, title="HW", marked_complete=False, submission_types=("on_paper",)
    )
    store.upsert_items([item], NOW)
    got = only(store)
    assert (got.ref, got.title, got.due_at, got.marked_complete) == (
        item.ref,
        "HW",
        item.due_at,
        False,
    )
    assert got.db_id is not None


def test_upsert_keeps_bot_fields_when_due_unchanged(store: Store) -> None:
    item = make_item(plannable_id=5)
    store.upsert_items([item], NOW)
    db_id = only(store).db_id
    assert db_id is not None
    store.set_bot_done(db_id, NOW)
    store.upsert_items([item], NOW + timedelta(minutes=10))
    got = only(store)
    assert got.bot_done_at == NOW and got.bot_done_due_at == item.due_at


def test_extension_clears_bot_snooze_and_stop(store: Store) -> None:
    item = make_item(plannable_id=5)
    store.upsert_items([item], NOW)
    db_id = only(store).db_id
    assert db_id is not None
    store.set_bot_done(db_id, NOW)
    store.snooze(db_id, NOW + timedelta(hours=2))
    store.set_stop(db_id)
    assert item.due_at is not None
    from dataclasses import replace

    store.upsert_items([replace(item, due_at=item.due_at + timedelta(days=2))], NOW)
    got = only(store)
    assert (got.bot_done_at, got.snoozed_until, got.stop_reminders) == (None, None, False)


def test_done_seen_at_tracks_transitions(store: Store) -> None:
    from dataclasses import replace

    item = make_item(plannable_id=5)
    store.upsert_items([item], NOW)
    assert only(store).done_seen_at is None
    store.upsert_items([replace(item, submitted=True)], NOW + timedelta(hours=1))
    assert only(store).done_seen_at == NOW + timedelta(hours=1)
    store.upsert_items([replace(item, submitted=True)], NOW + timedelta(hours=2))
    assert only(store).done_seen_at == NOW + timedelta(hours=1)
    store.upsert_items([replace(item, submitted=True, redo_request=True)], NOW + timedelta(hours=3))
    assert only(store).done_seen_at is None


def test_duplicate_in_one_batch_leaves_one_row(store: Store) -> None:
    item = make_item(plannable_id=5)
    store.upsert_items([item, item], NOW)
    assert len(store.snapshot().items) == 1


def test_mark_gone_only_inside_window_and_cleared_when_seen(store: Store) -> None:
    inside = make_item(plannable_id=1, due_in=timedelta(days=1))
    outside = make_item(plannable_id=2, due_in=timedelta(days=40))
    store.upsert_items([inside, outside], NOW)
    store.mark_gone((NOW - timedelta(days=28), NOW + timedelta(days=21)), set(), NOW)
    by_ref = {i.ref: i for i in store.snapshot().items}
    assert by_ref[inside.ref].gone_at == NOW and by_ref[outside.ref].gone_at is None
    store.upsert_items([inside], NOW + timedelta(minutes=10))
    by_ref = {i.ref: i for i in store.snapshot().items}
    assert by_ref[inside.ref].gone_at is None


def test_enrichment_fills_details_and_needs_enrichment_flips(store: Store) -> None:
    item = make_item(plannable_id=5, assignment_id=55, points_possible=None, submission_types=())
    store.upsert_items([item], NOW)
    assert store.needs_enrichment() is True
    lock = NOW + timedelta(days=3)
    store.apply_enrichment(
        Enrichment(
            courses=(Course(id=1, code="CS 101", name="Intro", total_points=100.0),),
            groups=(
                AssignmentGroup(id=9, course_id=1, name="HW", group_weight=40, total_points=50),
            ),
            details={
                55: AssignmentDetail(
                    assignment_id=55,
                    points_possible=10.0,
                    submission_types=("online_upload",),
                    assignment_group_id=9,
                    omit_from_final_grade=False,
                    lock_at=lock,
                )
            },
        )
    )
    assert store.needs_enrichment() is False
    got = only(store)
    assert (got.points_possible, got.lock_at, got.assignment_group_id) == (10.0, lock, 9)
    snap = store.snapshot()
    assert snap.courses[1].code == "CS 101" and snap.groups[9].group_weight == 40
    # a later planner sync must not wipe enrichment-owned fields
    store.upsert_items([item], NOW + timedelta(minutes=10))
    assert only(store).lock_at == lock and only(store).submission_types == ("online_upload",)


def test_snapshot_hides_courses_and_tracks_last_reminded(store: Store) -> None:
    store.apply_enrichment(
        Enrichment(courses=(Course(id=2, code="PE 100", name="Gym"),), groups=(), details={})
    )
    keep = make_item(plannable_id=1, course_id=1)
    hidden = make_item(plannable_id=2, course_id=2)
    store.upsert_items([keep, hidden], NOW)
    for minutes, key, kind in [
        (0, "rem:a:0", SendKind.REMINDER),
        (120, "rem:a:1", SendKind.REMINDER),
        (130, "overdue:x", SendKind.OVERDUE),
    ]:
        t = NOW + timedelta(minutes=minutes)
        assert store.claim(key, kind, [keep.ref], t)
        store.mark_sent(key, t, None)
    snap = store.snapshot(hidden_courses=frozenset({"PE 100"}))
    assert [i.ref for i in snap.items] == [keep.ref]
    assert snap.last_reminded_at == {keep.ref: NOW + timedelta(minutes=120)}
    assert snap.sent_keys == {"rem:a:0", "rem:a:1", "overdue:x"}
    by_id = store.snapshot(hidden_courses=frozenset({"1"}))
    assert [i.ref for i in by_id.items] == [hidden.ref]


def test_cycles_and_pause_in_snapshot(store: Store) -> None:
    store.open_cycle(NOW)
    assert store.snapshot().cycle == Cycle(anchor=NOW)
    store.close_cycle(NOW + timedelta(hours=3))
    assert store.snapshot().cycle is None
    store.set_time(PAUSE_UNTIL, NOW + timedelta(hours=1))
    assert store.snapshot().pause_until == NOW + timedelta(hours=1)


def test_clear_user_flags(store: Store) -> None:
    store.upsert_items([make_item(plannable_id=5)], NOW)
    db_id = only(store).db_id
    assert db_id is not None
    store.set_bot_done(db_id, NOW)
    store.set_stop(db_id)
    store.clear_user_flags(db_id)
    got = only(store)
    assert (got.bot_done_at, got.stop_reminders) == (None, False)
    assert store.get_item(db_id) == got
    assert store.get_item(999) is None


def test_purge_removes_old_items_and_notifications(store: Store) -> None:
    old = make_item(plannable_id=1, due_in=timedelta(days=-31))
    recent = make_item(plannable_id=2, due_in=timedelta(days=-29))
    store.upsert_items([old, recent], NOW)
    for key, age in [("old", 61), ("new", 59)]:
        t = NOW - timedelta(days=age)
        store.claim(key, SendKind.REMINDER, [], t)
        store.mark_sent(key, t, None)
    store.purge(NOW, item_retention=timedelta(days=30))
    assert [i.ref for i in store.snapshot().items] == [recent.ref]
    assert store.snapshot().sent_keys == {"new"}


def test_enrichment_marks_unmatched_items_as_attempted(store: Store) -> None:  # review I3
    store.upsert_items([make_item(plannable_id=5, assignment_id=999)], NOW)
    assert store.needs_enrichment()
    store.apply_enrichment(Enrichment(courses=(), groups=(), details={}))
    assert store.needs_enrichment() is False
