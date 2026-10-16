"""Repository over the SQLite schema: state, send claims, items, cycles."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from canvas_tracker.domain.models import SendKind

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


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- state ------------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

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
        """Reserve ``key`` for sending. False if it was sent or is being sent right now."""
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
