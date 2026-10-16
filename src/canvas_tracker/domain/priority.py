"""Transparent 100-point priority score and tiers (PRD §7.3).

Score = urgency (0-50) + importance (0-35) + effort pressure (0-15). Every
threshold lives in ``PriorityConfig`` so it can be tuned on real use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import AssignmentGroup, Course, Item, ItemType
from canvas_tracker.domain.status import hours_left, is_overdue_accepting


class Tier(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class PriorityConfig:
    overdue_urgency: int = 50
    # (max hours left, points); first match wins, else ``far_urgency``
    urgency_steps: tuple[tuple[float, int], ...] = ((24, 45), (48, 35), (72, 25), (168, 12))
    far_urgency: int = 4
    # (min share of final grade, points); first match wins
    importance_steps: tuple[tuple[float, int], ...] = (
        (0.15, 35),
        (0.08, 28),
        (0.04, 20),
        (0.015, 12),
    )
    tiny_share_importance: int = 6
    ungraded_importance: int = 2
    keyword_bonus: int = 5
    importance_cap: int = 35
    effort_factor: float = 1.5
    # (max slack hours, points); first match wins, else 0
    effort_steps: tuple[tuple[float, int], ...] = ((0, 15), (24, 10), (72, 5))
    high_total: int = 55
    high_share_72h: float = 0.08
    high_share_week: float = 0.10
    high_slack_hours: float = 24
    medium_total: int = 30


DEFAULT_PRIORITY = PriorityConfig()

_BONUS_RE = re.compile(r"\b(exam|midterm|final|project)\b", re.IGNORECASE)
_EXAM_RE = re.compile(r"\b(exam|midterm|final)\b", re.IGNORECASE)
_ESSAY_RE = re.compile(r"\b(essay|project|paper)\b", re.IGNORECASE)
_LAB_RE = re.compile(r"\blab\b", re.IGNORECASE)
_READING_RE = re.compile(r"\breading\b", re.IGNORECASE)
_ONE_HOUR_TYPES = frozenset(
    {ItemType.QUIZ, ItemType.DISCUSSION, ItemType.PEER_REVIEW, ItemType.PAGE}
)


@dataclass(frozen=True, slots=True)
class Score:
    urgency: int
    importance: int
    effort: int
    tier: Tier
    grade_share: float | None
    effort_hours: float

    @property
    def total(self) -> int:
        return self.urgency + self.importance + self.effort


def grade_share(item: Item, course: Course | None, group: AssignmentGroup | None) -> float | None:
    """Estimated fraction of the final grade, or ``None`` when it can't be known."""
    if item.omit_from_final_grade or item.points_possible == 0:
        return 0.0
    if item.points_possible is None or course is None:
        return None
    if course.apply_group_weights:
        if group is None or group.total_points <= 0 or group.group_weight <= 0:
            return None
        return group.group_weight / 100 * item.points_possible / group.total_points
    if course.total_points <= 0:
        return None
    return item.points_possible / course.total_points


def effort_hours(item: Item) -> float:
    """Default effort estimate in hours, from title keywords and item type."""
    title = item.title
    if item.type is ItemType.PEER_REVIEW:
        return 1  # reviewing someone's essay is not writing one
    if _EXAM_RE.search(title):
        return 8
    if _ESSAY_RE.search(title):
        return 6
    if _LAB_RE.search(title):
        return 3
    if item.type in _ONE_HOUR_TYPES or _READING_RE.search(title):
        return 1
    return 2


def _step(value: float, steps: tuple[tuple[float, int], ...], default: int) -> int:
    for limit, points in steps:
        if value <= limit:
            return points
    return default


def _importance(item: Item, share: float | None, cfg: PriorityConfig) -> int:
    if share is None:
        base = (
            cfg.tiny_share_importance
            if (item.points_possible or 0) > 0
            else cfg.ungraded_importance
        )
    elif share <= 0:
        base = cfg.ungraded_importance
    else:
        base = next(
            (p for floor, p in cfg.importance_steps if share >= floor), cfg.tiny_share_importance
        )
    if _BONUS_RE.search(item.title):
        base += cfg.keyword_bonus
    return min(base, cfg.importance_cap)


def score(
    item: Item,
    now: datetime,
    course: Course | None,
    group: AssignmentGroup | None,
    config: PriorityConfig = DEFAULT_PRIORITY,
) -> Score:
    left = hours_left(item, now)
    overdue = is_overdue_accepting(item, now)
    if overdue:
        urgency = config.overdue_urgency
    elif left is None or left <= 0:
        urgency = config.far_urgency
    else:
        urgency = _step(left, config.urgency_steps, config.far_urgency)

    share = grade_share(item, course, group)
    importance = _importance(item, share, config)

    hours = effort_hours(item)
    slack = None if left is None else left - config.effort_factor * hours
    effort = 0 if slack is None else _step(slack, config.effort_steps, 0)

    total = urgency + importance + effort
    if not is_done(item) and ((left is not None and 0 < left <= 24) or overdue):
        tier = Tier.URGENT
    elif (
        total >= config.high_total
        or (
            left is not None and left <= 72 and share is not None and share >= config.high_share_72h
        )
        or (
            left is not None
            and left <= 168
            and share is not None
            and share >= config.high_share_week
        )
        or (slack is not None and slack < config.high_slack_hours)
    ):
        tier = Tier.HIGH
    elif total >= config.medium_total:
        tier = Tier.MEDIUM
    else:
        tier = Tier.LOW
    return Score(urgency, importance, effort, tier, share, hours)
