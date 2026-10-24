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
    "3. Send /settings here, tap 🔑 Canvas token and paste the new one."
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
        "/digest: send today's morning list now",
        "/sync: check Canvas right now",
        "/status: last sync, token state, next list and reminder",
        "/pause 3h | 30m | until 18:00 | off: pause reminders",
        "/settings: time zone, morning time, quiet hours, Canvas token",
        "/disconnect: delete everything the bot knows about you",
        "/help: this list",
    ]
)
HELP_OWNER = "\n".join(
    [
        "",
        "Owner:",
        "/invite: a one-time sign-up link for a friend",
        "/users: who's connected and whether their Canvas access works",
        "/remove N: remove user N from /users",
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
    "auth_failed": "✗ Canvas rejected your access token. Send /settings → 🔑 Canvas token.",
    "unavailable": "✗ Couldn't reach Canvas right now. The bot keeps retrying.",
    "protocol_error": "✗ Canvas sent an unexpected response. The bot keeps retrying.",
}

# Stale data (PRD anti-goal: never present stale data as current)
STALE_NOTE = "⚠️ Based on Canvas data from {since}. If you've already submitted, ignore this."
STALE_NOTE_NEVER = "⚠️ Haven't reached Canvas yet, so this may be out of date."

# Friends mode: sign-up, settings and owner commands
INVITE_ONLY = "👋 This bot is invite-only. Ask the person who runs it for an invite link."
BOT_FULL = "Sorry, this bot is full right now. Ask the person who runs it."
SIGNUP_INTRO = (
    "👋 Welcome! I'll send you a ranked list of what's due every morning, and a reminder "
    "every 2 hours for anything due within 24 hours, until you submit it.\n\n"
    "How your data is handled:\n"
    "• Your Canvas access token is stored encrypted on the server of the person who runs "
    "this bot. They could technically access it, so only sign up if you trust them.\n"
    "• The bot only reads Canvas. It never submits, posts or changes anything.\n"
    "• /disconnect deletes everything right away. You can also cancel the token any time "
    "in Canvas (Account → Settings → Approved Integrations)."
)
ASK_URL = (
    "Step 1 of 5: What's your school's Canvas address?\n"
    "Open Canvas in your browser and copy the address bar, for example "
    "school.instructure.com or canvas.school.edu."
)
URL_INVALID = (
    "That doesn't look like a Canvas address. Send just the site, for example "
    "school.instructure.com."
)
URL_UNREACHABLE = "I couldn't find that address on the internet. Check it and send it again."
ASK_TOKEN = (
    "Step 2 of 5: Now create an access token for the bot.\n"
    "1. Tap the button below (or open Canvas → Account → Settings).\n"
    '2. Scroll to "Approved Integrations" and tap "+ New Access Token".\n'
    '3. Purpose: "Reminder bot". For the expiry, pick the latest date Canvas allows.\n'
    "4. Copy the token and paste it here. I'll delete your message right away."
)
BTN_OPEN_SETTINGS = "🔗 Open Canvas settings"
TOKEN_FORMAT = "That doesn't look like a token. Copy the whole token from Canvas and paste it here."
TOKEN_CHECKING = "🔐 Checking the token with Canvas…"
TOKEN_PROBLEMS = {
    "rejected": "✗ Canvas rejected that token. Make a new one and paste it here.",
    "unreachable": "✗ I couldn't reach Canvas at {host}. Send /start to fix the address, "
    "or paste the token again in a minute.",
    "not_canvas": "✗ {host} doesn't answer like Canvas. Send /start to fix the address.",
    "no_planner": "✗ The token works, but Canvas won't let it read your To Do list. "
    "Your school may restrict tokens. Paste another token or send /disconnect.",
}
TOKEN_SAVED = "✓ Token works. I deleted your message, and the token is stored encrypted."
ASK_TZ = (
    "Step 3 of 5: Which time zone are you in? Tap one, or type your city "
    "(e.g. Chicago, Phoenix, Berlin)."
)
BTN_TZ_CANVAS = "✓ {zone} (from Canvas)"
TZ_UNKNOWN = "I don't know that one. Try a big city near you, or a zone like America/Denver."
ASK_DIGEST = (
    "Step 4 of 5: When should your morning list arrive? Tap one, or type a time "
    "(e.g. 7:30 or 9:15 am)."
)
CLOCK_INVALID = "I didn't get that time. Try something like 8:00, 7:30 am or 21:00."
DIGEST_IN_QUIET = (
    "That's inside your quiet hours ({quiet}), when I don't send anything. Pick a later time."
)
ASK_QUIET = (
    "Step 5 of 5: Quiet hours: when should I never message you? Tap one, or type a range "
    "(e.g. 23:00-07:00)."
)
QUIET_INVALID = "I didn't get that. Try something like 23:00-07:00, 11pm-7am, or off."
QUIET_COVERS_DIGEST = (
    "Those quiet hours would hide your morning list at {digest}. Pick hours that end before it."
)
BTN_QUIET_OFF = "Off"
QUIET_RANGE = "{start} to {end}"
ALL_SET = (
    "✅ All set! Your morning list arrives at {digest} ({tz}). Quiet hours: {quiet}.\n"
    "I'm checking Canvas now. Send /today to see what's due, or /help for everything else."
)
FINISH_SIGNUP_FIRST = "Let's finish setting up first."
SETTINGS = (
    "⚙️ Your settings\n"
    "Canvas: {host}\n"
    "Time zone: {tz}\n"
    "Morning list: {digest}\n"
    "Quiet hours: {quiet}\n\n"
    "Tap what you'd like to change."
)
BTN_SET_TZ = "🌎 Time zone"
BTN_SET_DIGEST = "☀️ Morning time"
BTN_SET_QUIET = "🌙 Quiet hours"
BTN_SET_TOKEN = "🔑 Canvas token"
ASK_TZ_EDIT = "Which time zone? Tap one, or type your city. /cancel keeps the current one."
ASK_DIGEST_EDIT = "What time should the morning list arrive? /cancel keeps the current one."
ASK_QUIET_EDIT = "Which quiet hours? /cancel keeps the current ones."
ASK_TOKEN_EDIT = (
    "Paste a new Canvas access token (Canvas → Account → Settings → + New Access Token). "
    "I'll delete your message right away. /cancel keeps the current one."
)
SAVED = "✓ Saved."
CANCELLED = "OK, nothing changed."
NOTHING_TO_CANCEL = "There's nothing to cancel."
DISCONNECT_CONFIRM = (
    "This deletes your settings, your Canvas token and everything the bot remembers about "
    "your assignments. Are you sure?"
)
BTN_DISCONNECT_YES = "Yes, delete everything"
BTN_DISCONNECT_NO = "No, keep it"
DISCONNECTED = (
    "🗑 Done. Everything is deleted. To be safe, also delete the token in Canvas: "
    "Account → Settings → Approved Integrations. Thanks for trying the bot!"
)
REMOVED_BY_OWNER = (
    "The bot's owner removed your access and your data was deleted. You can also delete the "
    "token in Canvas: Account → Settings → Approved Integrations."
)
DISCONNECT_KEPT = "OK, nothing was deleted."
OWNER_ONLY = "Only the bot's owner can do that."
INVITE_LINK = "Send this link to one friend. It works once and expires in 7 days:\n{link}"
INVITE_NO_USERNAME = "I can't make links until the bot has a username (set one in @BotFather)."
USERS_HEADER = "👥 Users ({count} of {max})"
USERS_LINE = "{n}. {name}{you} · {host} · {state}"
USERS_YOU = " (you)"
USERS_STATE_SETUP = "setting up"
USERS_STATE_OK = "✓ synced {when}"
USERS_STATE_AUTH = "🔑 token rejected since {when}"
USERS_STATE_NEVER = "not synced yet"
REMOVE_USAGE = "Usage: /remove N, where N is the number from /users."
REMOVE_SELF = "You can't remove yourself. Use /disconnect if you want to leave."
REMOVED = "Removed {name} and deleted their data."
PAIRED_OWNER = "✅ You're the owner of this bot. Let's set up your own account first."
