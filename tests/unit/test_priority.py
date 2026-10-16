from datetime import timedelta

import pytest

from canvas_tracker.domain.models import AssignmentGroup, Course, ItemType
from canvas_tracker.domain.priority import Tier, grade_share, score
from tests.factories import NOW, make_item


def course_with_share(share: float, points: float = 10.0) -> Course:
    """An unweighted course in which an item worth ``points`` is ``share`` of the grade."""
    return Course(id=1, code="C", name="C", total_points=points / share)


def test_urgent_quiz_example() -> None:  # the PRD's own explanation example
    item = make_item(
        type=ItemType.QUIZ, due_in=timedelta(hours=5, minutes=20), points_possible=12.0
    )
    course = Course(id=1, code="C", name="C", total_points=100.0)  # 12 of 100 pts = 12% share
    s = score(item, NOW, course, None)
    assert (s.urgency, s.importance, s.effort, s.tier) == (45, 28, 10, Tier.URGENT)
    assert s.total == 83 and s.grade_share == pytest.approx(0.12)


@pytest.mark.parametrize(
    ("hours", "u"), [(24, 45), (24.01, 35), (48, 35), (72, 25), (168, 12), (169, 4)]
)
def test_urgency_edges(hours: float, u: int) -> None:
    s = score(make_item(due_in=timedelta(hours=hours)), NOW, None, None)
    assert s.urgency == u


def test_overdue_accepting_urgency_is_50() -> None:
    s = score(make_item(due_in=timedelta(hours=-3)), NOW, None, None)
    assert s.urgency == 50 and s.tier is Tier.URGENT


@pytest.mark.parametrize(
    ("points", "i"), [(15, 35), (14.9, 28), (8, 28), (4, 20), (1.5, 12), (1.4, 6), (0.1, 6)]
)
def test_importance_edges(points: float, i: int) -> None:  # out of 100 course points
    item = make_item(due_in=timedelta(days=10), points_possible=points)
    course = Course(id=1, code="C", name="C", total_points=100.0)
    assert score(item, NOW, course, None).importance == i


def test_zero_points_importance_is_2() -> None:
    item = make_item(points_possible=0.0, due_in=timedelta(days=10))
    assert score(item, NOW, course_with_share(0.5), None).importance == 2


def test_unknown_share_importance_depends_on_points() -> None:
    graded = make_item(due_in=timedelta(days=10))
    ungraded = make_item(due_in=timedelta(days=10), points_possible=None)
    assert score(graded, NOW, None, None).importance == 6
    assert score(ungraded, NOW, None, None).importance == 2


def test_keyword_bonus_caps_at_35() -> None:
    item = make_item(title="Final project", due_in=timedelta(days=10))
    assert score(item, NOW, course_with_share(0.20), None).importance == 35
    small = make_item(title="Midterm review", due_in=timedelta(days=10))
    assert score(small, NOW, course_with_share(0.05), None).importance == 25


def test_slack_nonpositive_gives_15() -> None:
    essay = make_item(title="Essay 2", due_in=timedelta(hours=8))  # 6 h effort -> slack -1
    s = score(essay, NOW, None, None)
    assert s.effort_hours == 6 and s.effort == 15


@pytest.mark.parametrize(
    ("hours", "e"), [(3, 15), (25, 10), (27, 10), (28, 5), (75, 5), (76, 0)]
)  # homework: 2 h effort -> slack = hours - 3
def test_effort_edges(hours: float, e: int) -> None:
    assert score(make_item(due_in=timedelta(hours=hours)), NOW, None, None).effort == e


@pytest.mark.parametrize(
    ("title", "item_type", "hours"),
    [
        ("Final exam", ItemType.QUIZ, 8),
        ("Research paper", ItemType.ASSIGNMENT, 6),
        ("Lab 3", ItemType.ASSIGNMENT, 3),
        ("Weekly check-in", ItemType.QUIZ, 1),
        ("Reading response", ItemType.ASSIGNMENT, 1),
        ("Reply to peers", ItemType.DISCUSSION, 1),
        ("Problem set 4", ItemType.ASSIGNMENT, 2),
        ("Peer review: Essay 2", ItemType.PEER_REVIEW, 1),
    ],
)
def test_effort_hours(title: str, item_type: ItemType, hours: float) -> None:
    item = make_item(title=title, type=item_type, due_in=timedelta(days=10))
    assert score(item, NOW, None, None).effort_hours == hours


def test_high_by_weight_within_72h() -> None:
    s = score(make_item(due_in=timedelta(hours=60)), NOW, course_with_share(0.09), None)
    assert s.tier is Tier.HIGH


def test_high_by_weight_within_week() -> None:
    s = score(make_item(due_in=timedelta(days=6)), NOW, course_with_share(0.11), None)
    assert s.tier is Tier.HIGH


def test_high_by_tight_slack() -> None:
    essay = make_item(title="Essay", due_in=timedelta(hours=30))  # slack 21 h
    assert score(essay, NOW, None, None).tier is Tier.HIGH


def test_medium_example() -> None:
    s = score(make_item(due_in=timedelta(days=6)), NOW, course_with_share(0.05), None)
    assert (s.urgency, s.importance, s.effort, s.tier) == (12, 20, 0, Tier.MEDIUM)


def test_low_example() -> None:
    item = make_item(due_in=timedelta(days=10), points_possible=0.0)
    s = score(item, NOW, course_with_share(0.5), None)
    assert (s.total, s.tier) == (6, Tier.LOW)


def test_done_item_is_not_urgent_tier() -> None:
    s = score(make_item(due_in=timedelta(hours=5), submitted=True), NOW, None, None)
    assert s.tier is not Tier.URGENT


def test_weighted_share() -> None:
    course = Course(id=1, code="C", name="C", apply_group_weights=True, total_points=500)
    group = AssignmentGroup(id=9, course_id=1, name="HW", group_weight=40, total_points=100)
    item = make_item(assignment_group_id=9)
    assert grade_share(item, course, group) == pytest.approx(0.04)


def test_zero_totals_give_none() -> None:  # Review Focus 2
    item = make_item()
    unweighted = Course(id=1, code="C", name="C", total_points=0)
    weighted = Course(id=1, code="C", name="C", apply_group_weights=True, total_points=0)
    empty_group = AssignmentGroup(id=9, course_id=1, name="HW", group_weight=40, total_points=0)
    zero_weight = AssignmentGroup(id=9, course_id=1, name="HW", group_weight=0, total_points=0)
    assert grade_share(item, unweighted, None) is None
    assert grade_share(item, weighted, empty_group) is None
    assert grade_share(item, weighted, zero_weight) is None
    assert grade_share(item, weighted, None) is None
    assert grade_share(make_item(points_possible=None), unweighted, None) is None


def test_omitted_from_final_grade_is_zero_share() -> None:
    item = make_item(omit_from_final_grade=True)
    assert grade_share(item, course_with_share(0.5), None) == 0.0
