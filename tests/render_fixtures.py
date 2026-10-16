"""A digest snapshot modelled on the PRD §7.4 example (Tue 2026-10-20 08:00, New York)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from canvas_tracker.domain.models import Course, ItemType, Snapshot
from tests.factories import make_item, make_snapshot

NY = ZoneInfo("America/New_York")
HOST = "canvas.example.edu"


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NY).astimezone(UTC)


DIGEST_NOW = ny(20, 8, 0)
COURSES = {
    n: Course(id=n, code=code, name=code, total_points=100.0)
    for n, code in enumerate(["CS 101", "MATH 221", "ENG 105", "PHYS 150", "HIST 110"], start=1)
}


def prd_digest_snapshot() -> Snapshot:
    items = [
        make_item(
            db_id=1,
            course_id=1,
            title="Homework 4: Recursion",
            due_at=ny(20, 23, 59),
            points_possible=6.0,
            html_url=f"https://{HOST}/courses/1/assignments/11",
        ),
        make_item(
            db_id=2,
            course_id=2,
            title="Quiz 7",
            type=ItemType.QUIZ,
            plannable_type="quiz",
            due_at=ny(20, 14, 0),
            points_possible=2.0,
            html_url=f"https://{HOST}/courses/2/quizzes/21",
        ),
        make_item(
            db_id=3,
            course_id=3,
            title="Peer review: Essay 2",
            type=ItemType.PEER_REVIEW,
            plannable_type="assessment_request",
            due_at=ny(20, 23, 59),
            points_possible=None,
            submission_types=(),
        ),
        make_item(
            db_id=4, course_id=4, title="Lab report 3", due_at=ny(22, 23, 59), points_possible=8.0
        ),
        make_item(
            db_id=5, course_id=5, title="Reading 6", due_at=ny(23, 23, 59), points_possible=1.0
        ),
        make_item(
            db_id=6, course_id=1, title="Homework 5", due_at=ny(24, 23, 59), points_possible=2.0
        ),
        make_item(
            db_id=7,
            course_id=2,
            title="Quiz 8",
            type=ItemType.QUIZ,
            plannable_type="quiz",
            due_at=ny(25, 12, 0),
            points_possible=2.0,
        ),
        make_item(
            db_id=8, course_id=3, title="Draft outline", due_at=ny(26, 23, 59), points_possible=3.0
        ),
        make_item(
            db_id=9,
            course_id=5,
            title="Reading response 5",
            due_at=ny(18, 23, 59),
            lock_at=ny(23, 23, 59),
            points_possible=1.0,
        ),
        make_item(
            db_id=10,
            course_id=1,
            title="Done one",
            due_at=ny(19, 23, 59),
            submitted=True,
            done_seen_at=ny(19, 15, 0),
        ),
        make_item(
            db_id=11,
            course_id=2,
            title="Done two",
            due_at=ny(19, 23, 59),
            bot_done_at=ny(19, 20, 0),
            bot_done_due_at=ny(19, 23, 59),
        ),
    ]
    return make_snapshot(items, courses=COURSES, last_successful_sync_at=ny(20, 7, 58))
