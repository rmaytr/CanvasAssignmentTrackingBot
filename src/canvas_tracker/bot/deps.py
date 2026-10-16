"""What the Telegram handlers need, bundled so handlers can be built per process."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from canvas_tracker.bot.pairing import PairingCode
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
    pairing: PairingCode
    env_owner_id: int | None
    hidden_courses: frozenset[str]
