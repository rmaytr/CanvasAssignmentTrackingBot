"""SQLite connection and schema migrations."""

from __future__ import annotations

import re
import sqlite3
from importlib.resources import files
from pathlib import Path

_MIGRATION_RE = re.compile(r"^(\d{4})_.+\.sql$")


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database in WAL mode with explicit transactions (autocommit otherwise)."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


STORE_MIGRATIONS = "canvas_tracker.store.migrations"


def _migrations(package: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for entry in files(package).iterdir():
        match = _MIGRATION_RE.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


def migrate(conn: sqlite3.Connection, package: str = STORE_MIGRATIONS) -> int:
    """Apply pending migrations, each in its own transaction; return the schema version."""
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, sql in _migrations(package):
        if number <= version:
            continue
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        version = number
    return version
