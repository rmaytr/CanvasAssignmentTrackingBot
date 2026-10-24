# Friends mode: one shared bot for the owner and 5–10 invited friends

Approved in chat on 2026-10-24. Supersedes the single-user setup of PRD §7.6–7.8
and §12 for the personal/friends stage; the public commercial launch (stronger
protection, privacy policy, bigger server) is out of scope here.

## Intent

The single-user build was too hard to set up: Docker, Git, the Terminal, token
files and a pairing code in the logs, for every person. In friends mode the
owner sets up **one** bot once, on a free always-on server. Friends set up
nothing: they tap an invite link, paste their Canvas address and access token
into the chat, pick their time zone and times, and they're done.

## Goals

- A friend goes from invite link to "✅ All set" in about 2 minutes, using
  only Telegram and Canvas.
- Free: runs on Google Cloud's always-free e2-micro VM (or any Docker host).
- Each friend has their own Canvas school, token, time zone, morning-list
  time and quiet hours. Every time shown or scheduled uses their own zone.
- Everything the single-user bot does (ranking, 2-hourly reminders, quiet
  hours, overnight warning, overdue notice, Done/Snooze/Undo, /today /week
  /digest /sync /status /pause) works the same for every friend.

## Non-goals (for now)

- Public sign-up, payments, a web site, calendar-feed mode, email.
- Per-friend reminder interval or look-ahead (global settings; easy to add).
- Scaling past a few dozen users.

## Anti-goals

- One friend ever seeing, or acting on, another friend's assignments.
- A Canvas token in a log line, a chat message left behind, a database in
  plain text, or an error message.
- Strangers using the bot or the owner's server.
- Sign-up that ever needs the Terminal.

## Design (decided)

- **Isolation by construction.** One SQLite file per friend
  (`DATA_DIR/users/<telegram id>.db`) with the existing schema, `Store`,
  `SyncService` and `Runtime` unchanged. A separate `DATA_DIR/registry.db`
  holds users, invites and bot-wide state. Every handler looks the user up by
  the Telegram ID of the update, so a button or command can only reach that
  user's own file.
- **Tokens encrypted at rest** with Fernet (AES + HMAC, `cryptography`). The
  key comes from `TOKEN_KEY` / `TOKEN_KEY_FILE`, separate from the data
  volume; `python -m canvas_tracker genkey` prints a new one. The token is
  decrypted only for each Canvas request.
- **Invite-only.** The owner sends `/invite` and gets a one-time link
  `https://t.me/<bot>?start=<code>` (16 random characters, valid 7 days,
  stored as a SHA-256 hash). `MAX_USERS` (default 25) caps sign-ups. Strangers
  who send `/start` without a valid invite get one polite "invite-only" reply;
  anything else from them is ignored.
- **Owner bootstrap.** `OWNER_TELEGRAM_ID` if set; otherwise the existing
  one-time pairing code in the log (the owner's only Terminal step). The owner
  then signs up like everyone else.
- **Sign-up in chat** (steps stored in the registry, so a restart resumes):
  1. Notice: who runs the bot, that the token is stored encrypted on the
     owner's server, `/disconnect` erases everything, and how to revoke the
     token in Canvas.
  2. Canvas address: accepts `school.instructure.com`, a full URL or any
     Canvas page URL; keeps only the `https://host`. Rejected: IPs, no dot,
     `localhost`/`.local`/`.internal`, and hosts that resolve to private or
     loopback addresses (so the server can't be pointed at itself).
  3. Token: the bot deletes the message, checks it with
     `GET /api/v1/users/self/profile` and one planner request, and keeps only
     the profile's `time_zone`. Clear replies for "rejected", "couldn't reach
     that Canvas" and "token works but can't read your To Do list".
  4. Time zone: button for the zone Canvas reports, buttons for US zones, or
     type a city or zone name ("Chicago", "Pacific", "Europe/Berlin").
  5. Morning list: buttons 7/8/9 AM or type a time ("7:30", "7:30 am").
  6. Quiet hours: buttons "12 AM–8 AM", "11 PM–7 AM", "Off", or type
     "23:00-07:00". A morning time inside quiet hours is refused with a reason.
  7. "✅ All set": first sync starts immediately; the morning list's
     late-delivery window is 4 h after its time (capped at 23:59).
- **`/settings`** shows the friend's settings with buttons to change time
  zone, morning time, quiet hours or Canvas token (same parsers and checks).
- **`/disconnect`** asks to confirm, then deletes the friend's database file
  and registry row and reminds them to delete the token in Canvas.
- **Owner commands:** `/invite`, `/users` (name, school host, signed-up date,
  last sync OK / token failing; never assignments), `/remove <n>`.
- **Configuration** (environment): `TELEGRAM_BOT_TOKEN(_FILE)`,
  `TOKEN_KEY(_FILE)`, `OWNER_TELEGRAM_ID`, `DATA_DIR` (default `/data`),
  `MAX_USERS`, and the global reminder settings already in `.env.example`.
  Per-user values (`CANVAS_BASE_URL`, `CANVAS_TOKEN`, `TIMEZONE`,
  `DIGEST_TIME`, `QUIET_HOURS`) leave the environment.
- **One loop** ticks every friend once a minute, concurrently, each tick
  isolated so one friend's Canvas outage or crash can't delay another. The
  health check reads the hub's last tick from `registry.db`.
- **Hosting guide:** Google Cloud e2-micro, browser SSH, one install script
  that installs Docker, asks for the bot token, generates the key and starts
  the bot.

## Left to the builder

Exact copy, button layout, module boundaries, and test structure.
