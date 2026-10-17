"""Repository over the SQLite schema: state, send claims, items, courses, cycles."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import (
    REMINDER_KINDS,
    AssignmentGroup,
    Course,
    Cycle,
    Enrichment,
    Item,
    ItemType,
    SendKind,
    Snapshot,
)

# State keys
OWNER_ID = "owner_telegram_id"
PAUSE_UNTIL = "pause_until"
LAST_SUCCESSFUL_SYNC_AT = "last_successful_sync_at"
LAST_SYNC_ATTEMPT_AT = "last_sync_attempt_at"
LAST_SYNC_ERROR = "last_sync_error"
PLANNER_ETAG = "planner_etag"
AUTH_FAILED_SINCE = "auth_failed_since"
LAST_TICK_AT = "last_tick_at"
LAST_ENRICHMENT_AT = "last_enrichment_at"
LAST_PURGE_AT = "last_purge_at"

CLAIM_STALE_AFTER = timedelta(minutes=2)
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

# Columns a planner sync owns. Enrichment owns lock_at, submission_types,
# assignment_group_id and omit_from_final_grade; the bot owns the rest.
_PLANNER_COLUMNS = (
    "title",
    "type",
    "course_id",
    "course_name",
    "assignment_id",
    "due_at",
    "html_url",
    "submitted",
    "excused",
    "graded",
    "late",
    "missing",
    "redo_request",
    "marked_complete",
)
_INSERT_COLUMNS = (
    "plannable_type",
    "plannable_id",
    *_PLANNER_COLUMNS,
    "lock_at",
    "points_possible",
    "submission_types",
    "assignment_group_id",
    "omit_from_final_grade",
    "done_seen_at",
)
_TIME_FIELDS = (
    "due_at",
    "lock_at",
    "bot_done_at",
    "bot_done_due_at",
    "snoozed_until",
    "done_seen_at",
    "gone_at",
)
_BOOL_FIELDS = (
    "omit_from_final_grade",
    "submitted",
    "excused",
    "graded",
    "late",
    "missing",
    "redo_request",
    "stop_reminders",
)


def to_db(value: datetime | None) -> str | None:
    """Fixed-width UTC text, so SQL string comparisons order correctly."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be timezone-aware UTC")
    return value.strftime(_TS_FORMAT)


def from_db(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.strptime(value, _TS_FORMAT).replace(tzinfo=UTC)


def _item_from_row(row: sqlite3.Row) -> Item:
    data: dict[str, Any] = {
        "db_id": row["id"],
        "plannable_type": row["plannable_type"],
        "plannable_id": row["plannable_id"],
        "title": row["title"],
        "type": ItemType(row["type"]),
        "course_id": row["course_id"],
        "course_name": row["course_name"],
        "assignment_id": row["assignment_id"],
        "html_url": row["html_url"],
        "points_possible": row["points_possible"],
        "submission_types": tuple(json.loads(row["submission_types"])),
        "assignment_group_id": row["assignment_group_id"],
        "marked_complete": None if row["marked_complete"] is None else bool(row["marked_complete"]),
    }
    for name in _TIME_FIELDS:
        data[name] = from_db(row[name])
    for name in _BOOL_FIELDS:
        data[name] = bool(row[name])
    return Item(**data)


def _db_value(item: Item, column: str) -> Any:
    value = getattr(item, column)
    if isinstance(value, datetime):
        return to_db(value)
    if isinstance(value, ItemType):
        return value.value
    if isinstance(value, tuple):
        return json.dumps(list(value))
    if isinstance(value, bool):
        return int(value)
    return value


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _transaction(self) -> _Tx:
        return _Tx(self.conn)

    # --- state ------------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_state(self, key: str, value: str | None) -> None:
        if value is None:
            self.conn.execute("DELETE FROM state WHERE key = ?", (key,))
        else:
            self.conn.execute(
                "INSERT INTO state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_time(self, key: str) -> datetime | None:
        return from_db(self.get_state(key))

    def set_time(self, key: str, value: datetime | None) -> None:
        self.set_state(key, to_db(value))

    # --- send claims (PRD §9.3) ---------------------------------------------

    def claim(self, key: str, kind: SendKind, item_refs: Sequence[str], now: datetime) -> bool:
        """Reserve ``key`` for sending. False if it was sent, or is being sent right now."""
        cursor = self.conn.execute(
            "INSERT INTO notifications (key, kind, status, item_refs, claimed_at) "
            "VALUES (?, ?, 'pending', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET status = 'pending', claimed_at = excluded.claimed_at, "
            "item_refs = excluded.item_refs, error = NULL "
            "WHERE notifications.status IN ('pending', 'failed') AND notifications.claimed_at < ?",
            (
                key,
                kind.value,
                json.dumps(list(item_refs)),
                to_db(now),
                to_db(now - CLAIM_STALE_AFTER),
            ),
        )
        return cursor.rowcount == 1

    def mark_sent(self, key: str, now: datetime, message_id: int | None) -> None:
        self.conn.execute(
            "UPDATE notifications SET status = 'sent', sent_at = ?, message_id = ?, error = NULL "
            "WHERE key = ?",
            (to_db(now), message_id, key),
        )

    def mark_failed(self, key: str, error: str) -> None:
        self.conn.execute(
            "UPDATE notifications SET status = 'failed', error = ? WHERE key = ?", (error, key)
        )

    # --- items ---------------------------------------------------------------

    def upsert_items(self, items: Sequence[Item], now: datetime) -> None:
        """Merge a planner sync. Only planner-owned columns change; bot fields survive
        unless the due date moved (an extension re-opens the item, PRD §7.2)."""
        latest = {item.ref: item for item in items}
        with self._transaction():
            for incoming in latest.values():
                row = self.conn.execute(
                    "SELECT * FROM items WHERE plannable_type = ? AND plannable_id = ?",
                    (incoming.plannable_type, incoming.plannable_id),
                ).fetchone()
                if row is None:
                    self._insert(replace(incoming, done_seen_at=now if is_done(incoming) else None))
                else:
                    self._update(_item_from_row(row), incoming, now)

    def _insert(self, item: Item) -> None:
        columns = ", ".join(_INSERT_COLUMNS)
        marks = ", ".join("?" for _ in _INSERT_COLUMNS)
        self.conn.execute(
            f"INSERT INTO items ({columns}) VALUES ({marks})",  # noqa: S608 - fixed columns
            [_db_value(item, c) for c in _INSERT_COLUMNS],
        )

    def _update(self, existing: Item, incoming: Item, now: datetime) -> None:
        changes: dict[str, Any] = {c: getattr(incoming, c) for c in _PLANNER_COLUMNS}
        if incoming.points_possible is not None:
            changes["points_possible"] = incoming.points_possible
        changes["gone_at"] = None
        if existing.due_at != incoming.due_at:
            changes |= {
                "bot_done_at": None,
                "bot_done_due_at": None,
                "snoozed_until": None,
                "stop_reminders": False,
            }
        merged = replace(existing, **changes)
        if not is_done(merged):
            changes["done_seen_at"] = None
        elif not is_done(existing) or existing.done_seen_at is None:
            changes["done_seen_at"] = now
        merged = replace(existing, **changes)
        assignments = ", ".join(f"{c} = ?" for c in changes)
        self.conn.execute(
            f"UPDATE items SET {assignments} WHERE id = ?",  # noqa: S608 - fixed columns
            [*(_db_value(merged, c) for c in changes), existing.db_id],
        )

    def mark_gone(
        self, window: tuple[datetime, datetime], seen_refs: set[str], now: datetime
    ) -> None:
        """Items inside the synced window that Canvas no longer returns are gone."""
        rows = self.conn.execute(
            "SELECT id, plannable_type, plannable_id FROM items "
            "WHERE gone_at IS NULL AND due_at >= ? AND due_at <= ?",
            (to_db(window[0]), to_db(window[1])),
        ).fetchall()
        gone = [
            (to_db(now), r["id"])
            for r in rows
            if f"{r['plannable_type']}-{r['plannable_id']}" not in seen_refs
        ]
        self.conn.executemany("UPDATE items SET gone_at = ? WHERE id = ?", gone)

    def apply_enrichment(self, enrichment: Enrichment) -> None:
        with self._transaction():
            self.conn.execute("DELETE FROM courses")
            self.conn.executemany(
                "INSERT INTO courses (id, code, name, apply_group_weights, total_points) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (c.id, c.code, c.name, int(c.apply_group_weights), c.total_points)
                    for c in enrichment.courses
                ],
            )
            self.conn.execute("DELETE FROM assignment_groups")
            self.conn.executemany(
                "INSERT INTO assignment_groups (id, course_id, name, group_weight, total_points) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (g.id, g.course_id, g.name, g.group_weight, g.total_points)
                    for g in enrichment.groups
                ],
            )
            self.conn.executemany(
                "UPDATE items SET points_possible = COALESCE(?, points_possible), "
                "submission_types = ?, assignment_group_id = ?, omit_from_final_grade = ?, "
                "lock_at = ?, enriched = 1 WHERE assignment_id = ?",
                [
                    (
                        d.points_possible,
                        json.dumps(list(d.submission_types)),
                        d.assignment_group_id,
                        int(d.omit_from_final_grade),
                        to_db(d.lock_at),
                        d.assignment_id,
                    )
                    for d in enrichment.details.values()
                ],
            )
            # Items whose assignment isn't in any active course (e.g. last term's work)
            # count as attempted, so they don't retrigger enrichment on every sync.
            self.conn.execute("UPDATE items SET enriched = 1 WHERE assignment_id IS NOT NULL")

    def needs_enrichment(self) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM items WHERE assignment_id IS NOT NULL AND enriched = 0 LIMIT 1"
        ).fetchone()
        return row is not None

    def get_item(self, db_id: int) -> Item | None:
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (db_id,)).fetchone()
        return None if row is None else _item_from_row(row)

    def set_bot_done(self, db_id: int, now: datetime) -> None:
        self.conn.execute(
            "UPDATE items SET bot_done_at = ?, bot_done_due_at = due_at WHERE id = ?",
            (to_db(now), db_id),
        )

    def clear_user_flags(self, db_id: int) -> None:
        self.conn.execute(
            "UPDATE items SET bot_done_at = NULL, bot_done_due_at = NULL, stop_reminders = 0 "
            "WHERE id = ?",
            (db_id,),
        )

    def snooze(self, db_id: int, until: datetime) -> None:
        self.conn.execute("UPDATE items SET snoozed_until = ? WHERE id = ?", (to_db(until), db_id))

    def set_stop(self, db_id: int) -> None:
        self.conn.execute("UPDATE items SET stop_reminders = 1 WHERE id = ?", (db_id,))

    # --- cycles --------------------------------------------------------------

    def open_cycle(self, anchor: datetime) -> None:
        with self._transaction():
            self.conn.execute(
                "UPDATE cycles SET closed_at_utc = ? WHERE closed_at_utc IS NULL", (to_db(anchor),)
            )
            self.conn.execute("INSERT INTO cycles (anchor_utc) VALUES (?)", (to_db(anchor),))

    def close_cycle(self, now: datetime) -> None:
        self.conn.execute(
            "UPDATE cycles SET closed_at_utc = ? WHERE closed_at_utc IS NULL", (to_db(now),)
        )

    # --- snapshot ------------------------------------------------------------

    def snapshot(self, hidden_courses: frozenset[str] = frozenset()) -> Snapshot:
        courses = {
            r["id"]: Course(
                id=r["id"],
                code=r["code"],
                name=r["name"],
                apply_group_weights=bool(r["apply_group_weights"]),
                total_points=r["total_points"],
            )
            for r in self.conn.execute("SELECT * FROM courses")
        }
        groups = {
            r["id"]: AssignmentGroup(
                id=r["id"],
                course_id=r["course_id"],
                name=r["name"],
                group_weight=r["group_weight"],
                total_points=r["total_points"],
            )
            for r in self.conn.execute("SELECT * FROM assignment_groups")
        }

        def visible(item: Item) -> bool:
            if item.course_id is None:
                return True
            course = courses.get(item.course_id)
            code = course.code if course is not None else None
            return str(item.course_id) not in hidden_courses and code not in hidden_courses

        items = tuple(
            item
            for item in (
                _item_from_row(r) for r in self.conn.execute("SELECT * FROM items ORDER BY id")
            )
            if visible(item)
        )
        sent_keys: set[str] = set()
        last_reminded: dict[str, datetime] = {}
        reminder_kinds = {k.value for k in REMINDER_KINDS}
        for r in self.conn.execute(
            "SELECT key, kind, item_refs, sent_at FROM notifications WHERE status = 'sent'"
        ):
            sent_keys.add(r["key"])
            sent_at = from_db(r["sent_at"])
            if r["kind"] in reminder_kinds and sent_at is not None:
                for ref in json.loads(r["item_refs"]):
                    if ref not in last_reminded or sent_at > last_reminded[ref]:
                        last_reminded[ref] = sent_at
        row = self.conn.execute(
            "SELECT anchor_utc FROM cycles WHERE closed_at_utc IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        anchor = from_db(row["anchor_utc"]) if row is not None else None
        return Snapshot(
            items=items,
            courses=courses,
            groups=groups,
            sent_keys=frozenset(sent_keys),
            last_reminded_at=last_reminded,
            cycle=Cycle(anchor=anchor) if anchor is not None else None,
            pause_until=self.get_time(PAUSE_UNTIL),
            last_successful_sync_at=self.get_time(LAST_SUCCESSFUL_SYNC_AT),
            auth_failed_since=self.get_time(AUTH_FAILED_SINCE),
        )

    def purge(
        self,
        now: datetime,
        item_retention: timedelta,
        notification_retention: timedelta = timedelta(days=60),
    ) -> None:
        cutoff = to_db(now - notification_retention)
        with self._transaction():
            self.conn.execute("DELETE FROM items WHERE due_at < ?", (to_db(now - item_retention),))
            self.conn.execute(
                "DELETE FROM notifications WHERE COALESCE(sent_at, claimed_at) < ?", (cutoff,)
            )
            self.conn.execute("DELETE FROM cycles WHERE closed_at_utc < ?", (cutoff,))


class _Tx:
    """BEGIN/COMMIT around a block on an autocommit connection; ROLLBACK on error."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> None:
        self.conn.execute("BEGIN")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.conn.execute("ROLLBACK" if exc_type is not None else "COMMIT")
