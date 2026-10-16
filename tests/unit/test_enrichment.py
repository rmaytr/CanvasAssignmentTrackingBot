import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx

from canvas_tracker.sources.canvas_client import CanvasClient
from canvas_tracker.sources.enrichment import fetch_enrichment, map_assignment_groups, map_course

BASE = "https://canvas.example.edu"
GROUPS = json.loads(
    (Path(__file__).parents[1] / "fixtures/canvas/assignment_groups.handmade.json").read_text()
)


def test_map_course() -> None:
    raw = {
        "id": 1,
        "course_code": "CS 101",
        "name": "Intro",
        "apply_assignment_group_weights": True,
    }
    course = map_course(raw)
    assert (course.id, course.code, course.name, course.apply_group_weights) == (
        1,
        "CS 101",
        "Intro",
        True,
    )


def test_groups_totals_exclude_omitted_and_unpublished() -> None:
    groups, details, total = map_assignment_groups(1, GROUPS)
    assert [(g.id, g.group_weight, g.total_points) for g in groups] == [
        (9, 40.0, 40.0),
        (10, 60.0, 100.0),
    ]
    assert total == 140.0
    assert details[11].lock_at == datetime(2026, 10, 23, 3, 59, tzinfo=UTC)
    assert details[71].submission_types == ("on_paper",)
    assert details[72].points_possible is None and details[13].omit_from_final_grade is True


def test_course_with_only_zero_points_totals_zero() -> None:
    raw = [
        {"id": 1, "name": "X", "group_weight": 0, "assignments": [{"id": 5, "points_possible": 0}]}
    ]
    groups, details, total = map_assignment_groups(3, raw)
    assert total == 0.0 and groups[0].total_points == 0.0 and 5 in details


@respx.mock
async def test_fetch_enrichment_builds_courses_with_totals() -> None:
    respx.get(f"{BASE}/api/v1/courses").respond(
        200,
        json=[
            {
                "id": 1,
                "course_code": "CS 101",
                "name": "Intro",
                "apply_assignment_group_weights": False,
            }
        ],
    )
    route = respx.get(f"{BASE}/api/v1/courses/1/assignment_groups").respond(200, json=GROUPS)
    result = await fetch_enrichment(CanvasClient(BASE, lambda: "t"))
    assert [(c.code, c.total_points) for c in result.courses] == [("CS 101", 140.0)]
    assert {g.id for g in result.groups} == {9, 10}
    assert set(result.details) == {11, 12, 13, 14, 71, 72}
    assert route.calls.last.request.url.params.get_list("include[]") == ["assignments"]


@pytest.mark.parametrize("weight", [None, "x"])
def test_bad_group_weight_is_zero(weight: object) -> None:
    groups, _details, _total = map_assignment_groups(
        1, [{"id": 2, "name": "G", "group_weight": weight, "assignments": []}]
    )
    assert groups[0].group_weight == 0.0
