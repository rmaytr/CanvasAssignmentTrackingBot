"""Courses, assignment groups and per-assignment details for prioritization (PRD §7.1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from canvas_tracker.domain.models import AssignmentDetail, AssignmentGroup, Course, Enrichment
from canvas_tracker.sources.canvas_client import CanvasClient
from canvas_tracker.sources.planner import parse_time


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _id(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def map_course(raw: Mapping[str, Any]) -> Course | None:
    course_id = _id(raw.get("id"))
    if course_id is None:
        return None
    return Course(
        id=course_id,
        code=str(raw.get("course_code") or ""),
        name=str(raw.get("name") or ""),
        apply_group_weights=raw.get("apply_assignment_group_weights") is True,
    )


def _counts(assignment: Mapping[str, Any]) -> float:
    """Points that count toward the final grade (0 for omitted or unpublished work)."""
    points = _float(assignment.get("points_possible"))
    if points <= 0 or assignment.get("omit_from_final_grade") is True:
        return 0.0
    if assignment.get("workflow_state", "published") != "published":
        return 0.0
    return points


def map_assignment_groups(
    course_id: int, raw_groups: Sequence[Mapping[str, Any]]
) -> tuple[list[AssignmentGroup], dict[int, AssignmentDetail], float]:
    groups: list[AssignmentGroup] = []
    details: dict[int, AssignmentDetail] = {}
    course_total = 0.0
    for raw in raw_groups:
        group_id = _id(raw.get("id"))
        if group_id is None:
            continue  # one malformed entry must not break enrichment
        assignments = [
            a for a in raw.get("assignments") or [] if isinstance(a, Mapping) and _id(a.get("id"))
        ]
        total = sum(_counts(a) for a in assignments)
        course_total += total
        groups.append(
            AssignmentGroup(
                id=group_id,
                course_id=course_id,
                name=str(raw.get("name") or ""),
                group_weight=_float(raw.get("group_weight")),
                total_points=total,
            )
        )
        for a in assignments:
            points = a.get("points_possible")
            assignment_id = int(a["id"])
            details[assignment_id] = AssignmentDetail(
                assignment_id=assignment_id,
                points_possible=None if points is None else _float(points),
                submission_types=tuple(str(t) for t in a.get("submission_types") or ()),
                assignment_group_id=group_id,
                omit_from_final_grade=a.get("omit_from_final_grade") is True,
                lock_at=parse_time(a.get("lock_at")),
            )
    return groups, details, course_total


async def fetch_enrichment(client: CanvasClient) -> Enrichment:
    raw_courses = await client.get_all(
        "/api/v1/courses", {"enrollment_state": "active", "per_page": "100"}
    )
    courses: list[Course] = []
    groups: list[AssignmentGroup] = []
    details: dict[int, AssignmentDetail] = {}
    for raw in raw_courses:
        course = map_course(raw) if isinstance(raw, Mapping) else None
        if course is None:
            continue
        raw_groups = await client.get_all(
            f"/api/v1/courses/{course.id}/assignment_groups",
            {"include[]": ["assignments"], "per_page": "100"},
        )
        course_groups, course_details, total = map_assignment_groups(
            course.id, [g for g in raw_groups if isinstance(g, Mapping)]
        )
        courses.append(
            Course(
                id=course.id,
                code=course.code,
                name=course.name,
                apply_group_weights=course.apply_group_weights,
                total_points=total,
            )
        )
        groups.extend(course_groups)
        details.update(course_details)
    return Enrichment(courses=tuple(courses), groups=tuple(groups), details=details)
