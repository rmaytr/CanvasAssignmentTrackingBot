"""Email versions of the morning list and the 2-hour deadline heads-up.

The body uses the same small HTML subset as Telegram (b, i, a); the mailer turns it
into a plain-text part and an HTML part. Telegram buttons have no email equivalent,
so links to Canvas stay inline.
"""

from __future__ import annotations

from datetime import datetime

from canvas_tracker.domain.models import Send, SendKind, Settings, Snapshot
from canvas_tracker.render import copy
from canvas_tracker.render.digest import render_digest
from canvas_tracker.render.format import clean_subject, clock, format_due, format_left
from canvas_tracker.render.items import clean_title, default_stale, heading, stale_note
from canvas_tracker.render.message import RenderedMessage


def _with_footer(body: str) -> str:
    return f"{body}\n\n—\n{copy.EMAIL_FOOTER}"


def render_email(
    send: Send, snap: Snapshot, now: datetime, settings: Settings, stale: bool | None = None
) -> RenderedMessage | None:
    """One email for an email send, or None if there's nothing left to say."""
    if stale is None:
        stale = default_stale(snap, now)
    zone = settings.zone
    if send.kind is SendKind.EMAIL_DIGEST:
        parts = render_digest(snap, now, settings, stale=stale)
        local = now.astimezone(zone)
        subject = copy.EMAIL_DIGEST_SUBJECT.format(date=f"{local:%a %b} {local.day}")
        body = _with_footer("\n\n".join(p.text for p in parts))
        return RenderedMessage(body, subject=clean_subject(subject))
    if send.kind is not SendKind.EMAIL_DEADLINE:
        raise ValueError(f"not an email send: {send.kind}")

    by_ref = {item.ref: item for item in snap.items}
    items = [by_ref[r] for r in send.item_refs if r in by_ref and by_ref[r].due_at is not None]
    if not items:
        return None
    due = items[0].due_at
    assert due is not None  # noqa: S101 - filtered above
    if len(items) == 1:
        subject = copy.EMAIL_DEADLINE_SUBJECT_ONE.format(
            time=clock(due, zone), title=clean_title(items[0].title)
        )
    else:
        subject = copy.EMAIL_DEADLINE_SUBJECT_MANY.format(count=len(items), time=clock(due, zone))
    when, left = format_due(due, now, zone), format_left(due - now)
    lines = [copy.EMAIL_DEADLINE_HEADER.format(when=when, left=left)]
    lines += [f"• {heading(item, snap, settings.canvas_host)}" for item in items]
    if stale:
        lines += ["", stale_note(snap, now, settings)]
    return RenderedMessage(_with_footer("\n".join(lines)), subject=clean_subject(subject))
