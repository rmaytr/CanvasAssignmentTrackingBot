"""What the per-user Telegram handlers need: one user's store, settings and sync."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from canvas_tracker.domain.models import Settings
from canvas_tracker.store.repo import Store

if TYPE_CHECKING:
    from canvas_tracker.runtime.sync import SyncService


@dataclass
class BotDeps:
    store: Store
    settings: Settings
    clock: Callable[[], datetime]
    sync: SyncService
    hidden_courses: frozenset[str] = frozenset()
