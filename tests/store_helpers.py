from __future__ import annotations

from pathlib import Path

from canvas_tracker.store.db import connect, migrate
from canvas_tracker.store.repo import Store


def new_store(path: Path | str = ":memory:") -> Store:
    conn = connect(path)
    migrate(conn)
    return Store(conn)
