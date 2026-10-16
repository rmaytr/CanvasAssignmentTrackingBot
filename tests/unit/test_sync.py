import json
from datetime import timedelta
from pathlib import Path

import pytest
import respx

from canvas_tracker.runtime.sync import (
    SyncOutcome,
    SyncService,
    enrichment_due,
    sync_due,
)
from canvas_tracker.sources.canvas_client import CanvasClient
from canvas_tracker.sources.planner import PLANNER_PATH
from canvas_tracker.store.repo import (
    AUTH_FAILED_SINCE,
    LAST_ENRICHMENT_AT,
    LAST_SUCCESSFUL_SYNC_AT,
    LAST_SYNC_ATTEMPT_AT,
    LAST_SYNC_ERROR,
    PLANNER_ETAG,
    Store,
)
from tests.factories import NOW
from tests.store_helpers import new_store

BASE = "https://canvas.example.edu"
FIXTURES = Path(__file__).parents[1] / "fixtures/canvas"
PLANNER = json.loads((FIXTURES / "planner_items.handmade.json").read_text())
GROUPS = json.loads((FIXTURES / "assignment_groups.handmade.json").read_text())


@pytest.fixture
def store() -> Store:
    return new_store()


def service(store: Store) -> SyncService:
    from unittest.mock import AsyncMock

    return SyncService(CanvasClient(BASE, lambda: "t", sleep=AsyncMock()), store, BASE)


@pytest.mark.parametrize(
    ("minutes_ago", "quiet", "expected"),
    [(9, False, False), (10, False, True), (29, True, False), (30, True, True)],
)
def test_sync_due(minutes_ago: int, quiet: bool, expected: bool) -> None:
    assert sync_due(NOW, NOW - timedelta(minutes=minutes_ago), quiet) is expected


def test_sync_due_first_time() -> None:
    assert sync_due(NOW, None, quiet=True) is True


def test_enrichment_due() -> None:
    assert enrichment_due(NOW, NOW - timedelta(hours=12), needs_enrichment=False)
    assert not enrichment_due(NOW, NOW - timedelta(hours=11), needs_enrichment=False)
    assert enrichment_due(NOW, NOW - timedelta(minutes=1), needs_enrichment=True)
    assert enrichment_due(NOW, None, needs_enrichment=False)


@respx.mock
async def test_ok_sync_writes_items_and_state(store: Store) -> None:
    respx.get(f"{BASE}{PLANNER_PATH}").respond(200, json=PLANNER, headers={"ETag": 'W/"1"'})
    assert await service(store).sync(NOW) is SyncOutcome.OK
    assert len(store.snapshot().items) == 6
    assert store.get_time(LAST_SUCCESSFUL_SYNC_AT) == NOW == store.get_time(LAST_SYNC_ATTEMPT_AT)
    assert store.get_state(PLANNER_ETAG) == 'W/"1"'


@respx.mock
async def test_304_only_marks_success(store: Store) -> None:
    route = respx.get(f"{BASE}{PLANNER_PATH}")
    route.respond(200, json=PLANNER, headers={"ETag": 'W/"1"'})
    svc = service(store)
    await svc.sync(NOW)
    route.respond(304)
    later = NOW + timedelta(minutes=10)
    assert await svc.sync(later) is SyncOutcome.NOT_MODIFIED
    assert route.calls.last.request.headers["If-None-Match"] == 'W/"1"'
    assert store.get_time(LAST_SUCCESSFUL_SYNC_AT) == later
    assert len(store.snapshot().items) == 6


@respx.mock
async def test_401_sets_auth_failed_once_and_ok_clears_it(store: Store) -> None:
    route = respx.get(f"{BASE}{PLANNER_PATH}")
    route.respond(401)
    svc = service(store)
    assert await svc.sync(NOW) is SyncOutcome.AUTH_FAILED
    assert await svc.sync(NOW + timedelta(minutes=10)) is SyncOutcome.AUTH_FAILED
    assert store.get_time(AUTH_FAILED_SINCE) == NOW
    assert store.get_state(LAST_SYNC_ERROR) == "CanvasAuthError"
    route.respond(200, json=[])
    assert await svc.sync(NOW + timedelta(minutes=20)) is SyncOutcome.OK
    assert store.get_time(AUTH_FAILED_SINCE) is None and store.get_state(LAST_SYNC_ERROR) is None


@respx.mock
async def test_unavailable_keeps_items(store: Store) -> None:
    route = respx.get(f"{BASE}{PLANNER_PATH}")
    route.respond(200, json=PLANNER)
    svc = service(store)
    await svc.sync(NOW)
    route.respond(503)
    assert await svc.sync(NOW + timedelta(minutes=10)) is SyncOutcome.UNAVAILABLE
    assert store.get_state(LAST_SYNC_ERROR) == "CanvasUnavailable"
    assert len(store.snapshot().items) == 6
    assert store.get_time(LAST_SUCCESSFUL_SYNC_AT) == NOW


@respx.mock
async def test_missing_item_is_marked_gone(store: Store) -> None:
    route = respx.get(f"{BASE}{PLANNER_PATH}")
    route.respond(200, json=PLANNER)
    svc = service(store)
    await svc.sync(NOW)
    route.respond(200, json=[r for r in PLANNER if r["plannable_id"] != 11])
    await svc.sync(NOW + timedelta(minutes=10))
    gone = {i.ref: i.gone_at for i in store.snapshot().items}
    assert gone["assignment-11"] == NOW + timedelta(minutes=10)
    assert gone["quiz-21"] is None


@respx.mock
async def test_enrich_applies_details(store: Store) -> None:
    respx.get(f"{BASE}{PLANNER_PATH}").respond(200, json=PLANNER)
    respx.get(f"{BASE}/api/v1/courses").respond(
        200, json=[{"id": 1, "course_code": "CS 101", "name": "Intro"}]
    )
    respx.get(f"{BASE}/api/v1/courses/1/assignment_groups").respond(200, json=GROUPS)
    svc = service(store)
    await svc.sync(NOW)
    assert store.needs_enrichment()
    assert await svc.enrich(NOW) is SyncOutcome.OK
    assert store.get_time(LAST_ENRICHMENT_AT) == NOW
    item = next(i for i in store.snapshot().items if i.ref == "assignment-11")
    assert item.lock_at is not None and item.assignment_group_id == 9
