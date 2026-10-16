"""Every user-facing string, in one place so it can be translated later.

Templates use ``str.format`` fields. Values from Canvas are escaped before
they are substituted.
"""

from __future__ import annotations

# Buttons
BTN_DONE = "✅ Done"
BTN_SNOOZE = "💤 2h"
BTN_OPEN = "🔗 Open"
BTN_STOP = "🔕 Stop"
BTN_UNDO = "↩️ Undo"

# Digest
DIGEST_HEADER = "☀️ Good morning! {date}"
DIGEST_COUNTS = "{urgent} urgent · {high} high · {later} later this week (synced {synced})"
STALE_BANNER = "⚠️ Couldn't reach Canvas since {since}, so this list may be out of date."
STALE_NEVER = "⚠️ Haven't reached Canvas yet, so this list may be incomplete."
NOTHING_DUE = "Nothing due in the next {days} days 🎉 (synced {synced})"
TIER_URGENT = "🔴 URGENT"
TIER_HIGH = "🟠 HIGH"
TIER_REST = "🟡 MEDIUM / ⚪ LOW: {count} items, next: {next} → /week"
SECTION_OVERDUE = "⚠️ OVERDUE"
SECTION_EVENTS = "📅 Events today"
DONE_YESTERDAY = "✅ Done yesterday: {count}"
OVERDUE_LINE = "• {heading}: was due {when}{accepted}"
OVERDUE_ACCEPTED = ", still accepted until {until}"

# Item explanation fragments
EXPLAIN_DUE = "due {when} (in {left})"
EXPLAIN_SHARE = "≈{share}% of grade"
EXPLAIN_WEIGHT_UNKNOWN = "weight unknown"
EXPLAIN_EFFORT = "est. {hours} h"
EXPLAIN_START_BY = "start by {when}"
TYPE_LABELS = {"quiz": "quiz", "peer_review": "peer review"}

# Reminders and alerts
REMINDER_HEADERS = (
    "⏰ Due within 24 hours: {count} not submitted",
    "⏰ Still to submit in the next 24 hours: {count}",
    "⏰ Reminder: {count} due within 24 hours",
)
REMINDER_LINE = "due {when} · {left} left"
UNDER_TWO_HOURS = " ⚠️"
NEW_URGENT_HEADER = "🆕 Just posted and due soon"
SNOOZE_END_HEADER = "⏰ Snooze over: still not submitted"
OVERNIGHT_HEADER = "🌙 Due while you sleep:"
OVERDUE_NOTICE = "❗ {title} is now overdue (was due {when})."
OVERDUE_STILL_ACCEPTED = "Canvas still accepts it until {until}."
AUTH_ALERT = (
    "🔑 Canvas rejected the bot's access token, so your list isn't updating.\n"
    "1. In Canvas, open Account → Settings → Approved Integrations.\n"
    '2. Create a new token ("+ New Access Token"), with an expiry of 120 days or less.\n'
    "3. Put it in the bot's token file. The bot picks it up on its next check, no restart needed."
)

# Pairing and basic commands
PAIRED = "✅ Paired! This bot will only talk to you now. Send /help to see what it can do."
SEND_CODE = (
    "Send /start followed by the pairing code from the bot's log, for example /start ABCD2345."
)
PAIR_WRONG = "That code isn't right. Check the bot's log and try again."
PAIR_EXPIRED = "That code has expired. A new one is in the bot's log."
PAIR_LOCKED = "Too many wrong codes. A new one is in the bot's log."
WELCOME = (
    "👋 Hi! Your digest arrives at {digest} ({tz}). When something is due within {window} h, "
    "you get a reminder every {interval} until it's submitted. Quiet hours: {quiet}.\n"
    "Send /help for commands."
)
QUIET_OFF = "off"
HELP = "\n".join(
    [
        "Commands:",
        "/today: what's due today, plus anything urgent or overdue",
        "/week: the next 7 days by priority",
        "/digest: send today's digest now",
        "/sync: check Canvas right now",
        "/status: last sync, token state, next digest and reminder",
        "/pause 3h | 30m | until 18:00 | off: pause reminders",
        "/help: this list",
    ]
)

# Button answers
DONE = "Marked done ✅"
SNOOZED = "Snoozed until {until} 💤"
SNOOZE_TOO_LATE = "It's due in under 30 minutes, so it can't be snoozed."
UNDONE = "Undone ↩️"
UNDO_EXPIRED = "Too late to undo. It reopens by itself if its due date changes."
STOPPED = "No more reminders for this one 🔕"
ITEM_GONE = "That item is no longer on your list."
UNDO_BUTTON = "✔️ {n} done · ↩️ Undo"

# Views and commands
TODAY_HEADER = "📋 Today, {date}"
NOTHING_TODAY = "Nothing due today 🎉"
WEEK_HEADER = "🗓 Next 7 days"
NOTHING_WEEK = "Nothing due in the next 7 days 🎉"
TIER_MEDIUM = "🟡 MEDIUM"
TIER_LOW = "⚪ LOW"
STATUS_LINES = (
    "Last sync: {sync}",
    "Token: {token}",
    "Next digest: {digest}",
    "Next reminder: {slot}",
    "{pause}",
    "Version: {version}",
)
STATUS_NEVER = "never"
STATUS_AUTH_OK = "OK"
STATUS_AUTH_FAILED = "failed since {since}"
STATUS_NO_SLOT = "none scheduled"
STATUS_REMINDERS_ON = "Reminders: on"
STATUS_PAUSED = "Paused until {until}"
PAUSE_USAGE = "Usage: /pause 30m, /pause 3h, /pause until 18:00, or /pause off (up to 7 days)."
PAUSED_UNTIL = "💤 Reminders paused until {until}. The digest still comes."
PAUSE_OFF = "🔔 Reminders are back on."
SYNC_OK = "✓ Synced: {count} items on your list"
SYNC_NOT_MODIFIED = "✓ No changes since the last sync"
SYNC_FAILED = {
    "auth_failed": "✗ Canvas rejected the access token. Check /status for what to do.",
    "unavailable": "✗ Couldn't reach Canvas right now. The bot keeps retrying.",
    "protocol_error": "✗ Canvas sent an unexpected response. The bot keeps retrying.",
}
