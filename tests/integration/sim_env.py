"""A fake Canvas (respx) plus the real Runtime, SyncService, client and store."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import respx

from canvas_tracker.domain.models import Settings
from canvas_tracker.notify.base import FakeNotifier
from canvas_tracker.runtime.loop import Runtime
from canvas_tracker.runtime.sync import SyncService
from canvas_tracker.sources.canvas_client import CanvasClient
from canvas_tracker.sources.planner import PLANNER_PATH
from canvas_tracker.store.db import connect, migrate
from canvas_tracker.store.repo import Store

BASE = "https://canvas.example.edu"
NY = ZoneInfo("America/New_York")


def ny(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=NY).astimezone(UTC)


@dataclass
class ScenarioItem:
    plannable_id: int
    title: str
    due: Callable[[datetime], datetime]
    posted_at: datetime | None = None
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    submission_types: tuple[str, ...] = ("online_upload",)

    def planner_json(self, now: datetime) -> dict[str, Any] | None:
        if self.posted_at is not None and now < self.posted_at:
            return None
        submitted = self.submitted_at is not None and now >= self.submitted_at
        graded = self.graded_at is not None and now >= self.graded_at
        return {
            "plannable_id": self.plannable_id,
            "plannable_type": "assignment",
            "plannable_date": self.due(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "course_id": 1,
            "context_name": "Course 1",
            "html_url": f"/courses/1/assignments/{self.plannable_id}",
            "planner_override": None,
            "submissions": {
                "submitted": submitted,
                "excused": False,
                "graded": graded,
                "late": False,
                "missing": False,
                "redo_request": False,
            },
            "plannable": {"id": self.plannable_id, "title": self.title, "points_possible": 10.0},
        }


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@dataclass
class SimEnv:
    clock: Clock
    store: Store
    runtime: Runtime
    notifier: FakeNotifier
    router: respx.MockRouter
    items: list[ScenarioItem] = field(default_factory=list)


def build_env(
    tmp_path: Path,
    items: list[ScenarioItem],
    settings: Settings,
    start: datetime,
    token: str = "1234~simulationtokenvalue0000000",
) -> SimEnv:
    clock = Clock(start)
    conn = connect(tmp_path / "bot.db")
    migrate(conn)
    store = Store(conn)
    router = respx.MockRouter(assert_all_called=False, base_url=BASE)

    def planner(_request: httpx.Request) -> httpx.Response:
        rows = [row for item in items if (row := item.planner_json(clock.now)) is not None]
        return httpx.Response(200, json=rows)

    router.get(PLANNER_PATH, name="planner").mock(side_effect=planner)
    router.get("/api/v1/courses").respond(
        200, json=[{"id": 1, "course_code": "SIM 101", "name": "Simulation"}]
    )
    router.get("/api/v1/courses/1/assignment_groups").mock(
        side_effect=lambda _r: httpx.Response(
            200,
            json=[
                {
                    "id": 9,
                    "name": "All",
                    "group_weight": 0,
                    "assignments": [
                        {
                            "id": i.plannable_id,
                            "points_possible": 10.0,
                            "submission_types": list(i.submission_types),
                            "omit_from_final_grade": False,
                            "lock_at": None,
                        }
                        for i in items
                    ],
                }
            ],
        )
    )
    client = CanvasClient(
        BASE, lambda: token, transport=httpx.MockTransport(router.handler), sleep=AsyncMock()
    )
    notifier = FakeNotifier()
    runtime = Runtime(
        store=store,
        sync=SyncService(client, store, BASE),
        notifier=notifier,
        settings=settings,
        clock=clock,
        can_send=lambda: True,
        token=lambda: token,
    )
    return SimEnv(clock, store, runtime, notifier, router, items)
