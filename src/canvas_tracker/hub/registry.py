"""Who the bot's users are, their settings, and one-time invites (friends mode)."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from canvas_tracker.store.db import connect, migrate
from canvas_tracker.store.repo import from_db, to_db

REGISTRY_MIGRATIONS = "canvas_tracker.hub.migrations"
INVITE_LIFETIME = timedelta(days=7)
OWNER_KEY = "owner_telegram_id"
HUB_LAST_TICK_AT = "last_tick_at"

Status = Literal["onboarding", "active"]
_UPDATABLE = frozenset(
    {
        "status",
        "step",
        "display_name",
        "is_owner",
        "canvas_base_url",
        "token_sealed",
        "tz",
        "suggested_tz",
        "digest_time",
        "quiet",
    }
)


@dataclass(frozen=True, slots=True)
class User:
    telegram_id: int
    status: Status
    step: str | None
    display_name: str
    is_owner: bool
    canvas_base_url: str | None
    token_sealed: bytes | None
    tz: str | None
    suggested_tz: str | None
    digest_time: time | None
    quiet: str
    created_at: datetime


def _user(row: sqlite3.Row) -> User:
    created = from_db(row["created_at"])
    assert created is not None  # noqa: S101 - NOT NULL column
    return User(
        telegram_id=row["telegram_id"],
        status=row["status"],
        step=row["step"],
        display_name=row["display_name"],
        is_owner=bool(row["is_owner"]),
        canvas_base_url=row["canvas_base_url"],
        token_sealed=row["token_sealed"],
        tz=row["tz"],
        suggested_tz=row["suggested_tz"],
        digest_time=time.fromisoformat(row["digest_time"]) if row["digest_time"] else None,
        quiet=row["quiet"],
        created_at=created,
    )


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class Registry:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- users ---------------------------------------------------------------

    def create_user(
        self, telegram_id: int, name: str, *, now: datetime, is_owner: bool = False
    ) -> User:
        self.conn.execute(
            "INSERT INTO users (telegram_id, status, step, display_name, is_owner, created_at) "
            "VALUES (?, 'onboarding', 'url', ?, ?, ?)",
            (telegram_id, name[:64], int(is_owner), to_db(now)),
        )
        user = self.get_user(telegram_id)
        assert user is not None  # noqa: S101
        return user

    def get_user(self, telegram_id: int) -> User | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return None if row is None else _user(row)

    def all_users(self) -> list[User]:
        return [_user(r) for r in self.conn.execute("SELECT * FROM users ORDER BY created_at")]

    def active_users(self) -> list[User]:
        return [u for u in self.all_users() if u.status == "active"]

    def count_users(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def update_user(self, telegram_id: int, /, **fields: Any) -> None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"unknown user fields: {sorted(unknown)}")
        values = {
            k: (
                v.strftime("%H:%M") if isinstance(v, time) else int(v) if isinstance(v, bool) else v
            )
            for k, v in fields.items()
        }
        assignments = ", ".join(f"{k} = ?" for k in values)
        self.conn.execute(
            f"UPDATE users SET {assignments} WHERE telegram_id = ?",  # noqa: S608 - checked keys
            [*values.values(), telegram_id],
        )

    def delete_user(self, telegram_id: int) -> None:
        self.conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))

    # --- invites -------------------------------------------------------------

    def create_invite(self, now: datetime) -> str:
        code = secrets.token_urlsafe(12)  # 16 characters, 96 random bits
        self.conn.execute(
            "INSERT INTO invites (code_hash, created_at, expires_at) VALUES (?, ?, ?)",
            (_hash(code), to_db(now), to_db(now + INVITE_LIFETIME)),
        )
        return code

    def redeem_invite(self, code: str, telegram_id: int, now: datetime) -> bool:
        """Use ``code`` up. True only for the first redemption before it expires."""
        cursor = self.conn.execute(
            "UPDATE invites SET used_by = ?, used_at = ? "
            "WHERE code_hash = ? AND used_by IS NULL AND expires_at > ?",
            (telegram_id, to_db(now), _hash(code.strip()), to_db(now)),
        )
        return cursor.rowcount == 1

    # --- state ---------------------------------------------------------------

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

    def set_time(self, key: str, value: datetime) -> None:
        self.set_state(key, to_db(value))


def open_registry(path: Path | str) -> Registry:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    migrate(conn, REGISTRY_MIGRATIONS)
    return Registry(conn)
