"""Shared pieces for rendering Canvas items: labels, titles, links, buttons."""

from __future__ import annotations

from datetime import datetime

from canvas_tracker.domain.models import STALE_AFTER, Item, Settings, Snapshot
from canvas_tracker.render import copy
from canvas_tracker.render.format import clock, escape, format_due, safe_link

TITLE_MAX = 200


def course_label(item: Item, snap: Snapshot) -> str:
    course = snap.courses.get(item.course_id) if item.course_id is not None else None
    return course.code if course is not None and course.code else item.course_name


def clean_title(title: str) -> str:
    flat = " ".join(title.split())
    return flat if len(flat) <= TITLE_MAX else flat[: TITLE_MAX - 1] + "…"


def link_for(item: Item, canvas_host: str) -> str | None:
    return safe_link(item.html_url, canvas_host)


def title_html(item: Item, canvas_host: str) -> str:
    """The escaped title, wrapped in a link only when the URL is on the Canvas host."""
    title = escape(clean_title(item.title))
    url = link_for(item, canvas_host)
    return title if url is None else f'<a href="{escape(url)}">{title}</a>'


def heading(item: Item, snap: Snapshot, canvas_host: str) -> str:
    course = course_label(item, snap)
    title = title_html(item, canvas_host)
    return f"{escape(course)} · {title}" if course else title


def plain_heading(item: Item, snap: Snapshot) -> str:
    course = course_label(item, snap)
    title = escape(clean_title(item.title))
    return f"{escape(course)} · {title}" if course else title


def default_stale(snap: Snapshot, now: datetime) -> bool:
    """Stale when Canvas hasn't been reached for longer than a normal sync gap."""
    last = snap.last_successful_sync_at
    return last is None or now - last > STALE_AFTER


def stale_banner(snap: Snapshot, settings: Settings) -> str:
    last = snap.last_successful_sync_at
    if last is None:
        return copy.STALE_NEVER
    return copy.STALE_BANNER.format(since=clock(last, settings.zone))


def stale_note(snap: Snapshot, now: datetime, settings: Settings) -> str:
    last = snap.last_successful_sync_at
    if last is None:
        return copy.STALE_NOTE_NEVER
    return copy.STALE_NOTE.format(since=format_due(last, now, settings.zone))
