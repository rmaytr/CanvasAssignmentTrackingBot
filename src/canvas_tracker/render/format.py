"""Formatting helpers: escaping, safe links, human time text, message splitting.

All local times use the zone passed in, never the host's local time zone.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

TELEGRAM_LIMIT = 4096
_TAG_RE = re.compile(r"<[^>]+>")


def escape(text: str) -> str:
    return html.escape(text, quote=True)


def safe_link(url: str | None, canvas_host: str) -> str | None:
    """Return ``url`` only if it is HTTPS on the configured Canvas host."""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() != canvas_host.lower():
        return None
    return url


def clock(instant: datetime, tz: ZoneInfo) -> str:
    local = instant.astimezone(tz)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def format_due(due: datetime, now: datetime, tz: ZoneInfo) -> str:
    """Human due time relative to ``now``: today / tomorrow / weekday / month day."""
    local_due = due.astimezone(tz)
    days = (local_due.date() - now.astimezone(tz).date()).days
    if days == 0:
        day = "today"
    elif days == 1:
        day = "tomorrow"
    elif days == -1:
        day = "yesterday"
    elif -6 <= days <= 6:
        day = local_due.strftime("%a")
    else:
        day = f"{local_due.strftime('%b')} {local_due.day}"
    return f"{day} {clock(due, tz)}"


def format_left(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    hours, mins = divmod(minutes, 60)
    if hours >= 48:
        days, rest = divmod(hours, 24)
        return f"{days} d {rest} h"
    if hours == 0:
        return f"{mins} m"
    return f"{hours} h {mins} m"


def _cut_plain(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
            amp = text.rfind("&", max(0, cut - 8), cut)
            if amp > 0 and ";" not in text[amp:cut]:
                cut = amp  # don't split an HTML entity
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def split_blocks(blocks: Sequence[str], limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Join blocks with newlines into parts of at most ``limit`` characters.

    Blocks are never split, except one that is longer than the limit by
    itself: its tags are dropped and its text is cut at whitespace.
    """
    pieces: list[str] = []
    for block in blocks:
        if len(block) <= limit:
            pieces.append(block)
        else:
            pieces.extend(_cut_plain(_TAG_RE.sub("", block), limit))
    parts: list[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else f"{current}\n{piece}"
        if len(candidate) <= limit:
            current = candidate
        else:
            parts.append(current)
            current = piece
    if current:
        parts.append(current)
    return parts
