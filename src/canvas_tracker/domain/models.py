"""Core value types shared by the pure domain/planning code and the I/O layers.

All datetimes are timezone-aware UTC. Local time only appears when rendering,
using ``Settings.zone``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Fixed rule constants (PRD §7.4-7.5).
SLOT_GRACE = timedelta(minutes=30)
DIGEST_FOLD = timedelta(minutes=15)
OVERNIGHT_LEAD = timedelta(minutes=30)
OVERDUE_NOTICE_GRACE = timedelta(hours=2)
SNOOZE_END_GRACE = timedelta(minutes=30)
SNOOZE_LENGTH = timedelta(hours=2)
SNOOZE_MIN_LEFT = timedelta(minutes=30)
OVERDUE_SECTION_MAX = timedelta(days=7)
STALE_AFTER = timedelta(minutes=30)
UNDO_WINDOW = timedelta(minutes=10)
FRESHNESS = timedelta(minutes=5)
MIN_REMINDER_INTERVAL = timedelta(minutes=30)


def _check_utc(obj: object) -> None:
    for f in fields(obj):  # type: ignore[arg-type]
        value = getattr(obj, f.name)
        if isinstance(value, datetime) and (
            value.tzinfo is None or value.utcoffset() != timedelta(0)
        ):
            raise ValueError(f"{f.name} must be timezone-aware UTC")


class ItemType(StrEnum):
    ASSIGNMENT = "assignment"
    QUIZ = "quiz"
    DISCUSSION = "discussion_topic"
    SUB_ASSIGNMENT = "sub_assignment"
    PEER_REVIEW = "peer_review"
    PAGE = "wiki_page"
    NOTE = "planner_note"
    EVENT = "calendar_event"
    OTHER = "other"


@dataclass(frozen=True, slots=True, kw_only=True)
class Item:
    # Canvas-owned
    plannable_type: str
    plannable_id: int
    title: str
    type: ItemType
    course_id: int | None = None
    course_name: str = ""
    assignment_id: int | None = None
    due_at: datetime | None = None
    lock_at: datetime | None = None
    html_url: str | None = None
    points_possible: float | None = None
    submission_types: tuple[str, ...] = ()
    assignment_group_id: int | None = None
    omit_from_final_grade: bool = False
    submitted: bool = False
    excused: bool = False
    graded: bool = False
    late: bool = False
    missing: bool = False
    redo_request: bool = False
    marked_complete: bool | None = None  # None: no override; False: explicitly un-marked
    # Bot-owned
    db_id: int | None = None
    bot_done_at: datetime | None = None
    bot_done_due_at: datetime | None = None
    snoozed_until: datetime | None = None
    stop_reminders: bool = False
    done_seen_at: datetime | None = None
    gone_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_utc(self)

    @property
    def ref(self) -> str:
        return f"{self.plannable_type}-{self.plannable_id}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Course:
    id: int
    code: str
    name: str
    apply_group_weights: bool = False
    total_points: float = 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignmentGroup:
    id: int
    course_id: int
    name: str
    group_weight: float
    total_points: float


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignmentDetail:
    assignment_id: int
    points_possible: float | None
    submission_types: tuple[str, ...]
    assignment_group_id: int | None
    omit_from_final_grade: bool
    lock_at: datetime | None

    def __post_init__(self) -> None:
        _check_utc(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class Enrichment:
    courses: tuple[Course, ...]
    groups: tuple[AssignmentGroup, ...]
    details: Mapping[int, AssignmentDetail]


@dataclass(frozen=True, slots=True, kw_only=True)
class Cycle:
    anchor: datetime

    def __post_init__(self) -> None:
        _check_utc(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    tz: str
    digest_time: time = time(8, 0)
    digest_grace_until: time = time(12, 0)
    digest_lookahead: timedelta = timedelta(days=14)
    reminder_window: timedelta = timedelta(hours=24)
    reminder_interval: timedelta = timedelta(minutes=120)
    quiet_start: time | None = time(0, 0)
    quiet_end: time | None = time(8, 0)
    overdue_reminders: bool = False
    overdue_reminder_max: timedelta = timedelta(hours=48)
    canvas_host: str = ""

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone: {self.tz!r}") from exc
        if self.reminder_interval < MIN_REMINDER_INTERVAL:
            raise ValueError("reminder_interval must be at least 30 minutes")

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


@dataclass(frozen=True, slots=True, kw_only=True)
class Snapshot:
    items: tuple[Item, ...]
    courses: Mapping[int, Course]
    groups: Mapping[int, AssignmentGroup]
    sent_keys: frozenset[str]
    last_reminded_at: Mapping[str, datetime]
    cycle: Cycle | None
    pause_until: datetime | None
    last_successful_sync_at: datetime | None
    auth_failed_since: datetime | None


class SendKind(StrEnum):
    DIGEST = "digest"
    REMINDER = "reminder"
    NEW_URGENT = "new_urgent"
    SNOOZE_END = "snooze_end"
    OVERNIGHT = "overnight"
    OVERDUE = "overdue"
    AUTH_ALERT = "auth_alert"


REMINDER_KINDS = frozenset(
    {SendKind.DIGEST, SendKind.REMINDER, SendKind.NEW_URGENT, SendKind.SNOOZE_END}
)


@dataclass(frozen=True, slots=True)
class Send:
    key: str
    kind: SendKind
    item_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    sends: tuple[Send, ...] = ()
    open_cycle_at: datetime | None = None
    close_cycle: bool = False
