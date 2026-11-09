# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Optional email.** `/email you@school.edu` (confirmed with a 6-digit code sent to that address) adds an email copy of the morning list and one email 2 hours before each deadline. Assignments due at the same time share one email. Deadline emails wait out quiet hours and `/pause`, and are never sent after the deadline. `/email off` or `/disconnect` deletes the address. Telegram messages are unchanged.
- Works with any SMTP provider (Brevo, Gmail, your own domain): `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `EMAIL_FROM`, `EMAIL_FROM_NAME` in `.env`, with the password in `secrets/smtp_password.txt`. Email is off unless `SMTP_HOST` is set. See the hosting guide.

- **Your own reminder rhythm.** `/settings → ⏰ Reminders` lets each person choose how often reminders repeat (every 1, 2, 3 or 4 hours, or **no repeats**), how early work counts as urgent (12, 24 or 48 hours before it's due) and how far ahead the morning list looks (7, 14 or 21 days). With no repeats, the morning list and the one-off messages (new last-minute work, work due overnight, overdue work, the end of a snooze) still come. Everyone starts on the bot-wide defaults from `.env`, so nothing changes for existing users until they choose. The end of sign-up points to the new menu.
- Changing the interval mid-cycle restarts the cycle from its latest reminder: nothing is sent twice and nothing is skipped.

- **`/feedback your message`** sends a note to the person who runs the bot, with the sender's Telegram name and ID (never any Canvas data). Up to 5 an hour per person, also during sign-up. A note containing a Canvas token is deleted from the chat and not sent. Listed in `/help` and the command menu.
- **A fuller `/status`:** it now also shows the reminder rhythm, whether email is on (the address masked, e.g. `m***@school.edu`, or "not available on this bot"), when the next 📅 event heads-up goes out and when the latest announcement was posted.
- **`/settings → 📧 Email`** explains `/email` and shows the current address, so every setting can be reached from `/settings`. The email line says "not available on this bot" when the bot has no mail server.
- Owner `/users` shows whether each person gets email (yes/no only).

- **Owner alerts.** The person who runs the bot gets a ⚠️ Telegram message when a user's Canvas sync has failed for 6 hours for a reason other than a rejected token, when 3 emails in a row couldn't be sent, when the data disk has under 200 MB or 5 % free, or when a user's check has been running for 10 minutes. Each problem is reported at most once per 24 hours, with a ✅ note when it clears, and a restart doesn't repeat them. Alerts name people only by name and Telegram ID, never their assignments, tokens or addresses.
- **Owner `/health`:** uptime, version, users (active and signing up), the last check, free disk space, whether email is set up (and failing), how many people have sync problems and how many alerts are open.
- An `hourly summary` log line with counts only (users, messages sent and failed by kind, sync problems, free disk), for `docker compose logs`.
- Hosting guide: a *Monitoring* section, a *Back up and restore* section (the backup now also includes `.env`; it holds the bot token, the encryption key and the SMTP password, so keep it private) and more troubleshooting rows.

- **Announcements and events are no longer treated as homework.** A course announcement now gets one 📢 message when it's posted, a calendar event gets a 📅 heads-up an hour before it starts, and the morning list shows both under a new *Announcements & events* section. Neither is ever reminded, ranked or reported as overdue.

### Fixed
- The sign-up welcome, the "All set" message and `/start` always said "every 2 hours … within 24 hours", whatever the bot was configured with; they now show the person's actual rhythm. The ⏰ reminder header also names the person's window instead of always "24 hours".
- When a 💤 snooze ended shortly before the deadline, the item could get a "Snooze over" message and a "Just posted and due soon" alert in the same minute. Now only the first is sent.
- After `/disconnect` and signing up again, a ✅/💤/🔕 button on an old message could act on a different item in the new account (item numbers start again at 1). Buttons now carry a random code tied to the user's database, and old ones answer "This button is from before you reconnected". Buttons sent before this update keep working for existing users.
- Sign-ups abandoned part-way no longer hold a `MAX_USERS` slot forever: after 7 days without an answer they're cleared (owner and active users never are), and the person is told to ask for a new invite. Sign-ups already in progress when you update get a full 7 days.
- The Docker image builds without first downloading the BuildKit `dockerfile:1` frontend from Docker Hub (that download could stall the install).
- Course announcements (and posts like "Attend the social this Thursday!") were reminded about and reported as ❗ overdue, because Canvas's `announcement` items were treated as assignments.

### Security
- At most 5 Canvas token checks per user per 15 minutes (sign-up and `/settings`), then a friendly "wait N min"; `/sync` at most once a minute per user.
- The "Canvas host resolves only to public addresses" check now also runs before every sync and token check (cached for 5 minutes), not just at sign-up, so a host that is later re-pointed at a private address (DNS rebinding) is refused.
- Email addresses are stored Fernet-encrypted like Canvas tokens, and only after confirmation. Codes are stored hashed, expire after 15 minutes, lock after 5 wrong tries, and can be requested at most once a minute. SMTP errors are logged by class name only.

### Upgrading
- `compose.yaml` now mounts `secrets/smtp_password.txt`. Running the install command again creates it (empty means no email). If you update by hand, run `touch secrets/smtp_password.txt` first.

### Changed
- Repository cleanup: a new README with diagrams, plus architecture, how-it-works, testing and security docs, contributor guides and issue templates.
- Updated dependencies flagged by `pip-audit`: `certifi` (runtime, CA bundle), plus the dev-only `filelock` and `virtualenv`.

## [0.2.0] - 2026-10-24: Friends mode

One shared, invite-only bot instead of one self-hosted copy per student.

### Added
- **Sign-up in the chat:** Canvas address → access token → time zone → morning time → quiet hours, in about 2 minutes.
- **Per-user isolation:** each user has their own database file, Canvas client, settings and scheduler.
- **Encrypted tokens:** Fernet (AES + HMAC) with a key kept outside the data volume (`python -m canvas_tracker genkey`).
- **Owner commands:** `/invite` (one-time, 7-day links), `/users` (sync health, never assignments), `/remove` (confirm by name).
- **`/settings`** for time zone, morning time, quiet hours, Canvas token and Canvas address; **`/disconnect`** deletes everything.
- **One-command installer** (`deploy/install.sh`) for Debian and Ubuntu servers, and guides for hosting and joining.
- The bot registers its own Telegram command menu.

### Security
- A message containing a token is deleted at any step, and the bot only says so if deletion worked.
- Canvas addresses must be public HTTPS hosts on port 443.
- A wrong or lost encryption key is detected at start-up and reported to the owner. Users are not told their token was rejected.

### Fixed (from an independent review)
- One user's slow Canvas could delay everyone's reminders and the health check.
- Telegram updates were handled one at a time across all users.
- A morning time of 23:59 never fired; times after 8 PM are now refused.
- `/remove N` could hit the wrong person after someone left.
- There was no way to change the Canvas address after sign-up.

### Removed
- Single-user configuration through `CANVAS_BASE_URL`, `CANVAS_TOKEN`, `TIMEZONE` and similar environment variables. These settings now live in the chat.

## [0.1.0] - 2026-10-17: Personal MVP

### Added
- Canvas Planner sync (ETag-cached, rate-limit aware), with enrichment from courses and assignment-group weights.
- A 100-point priority score (urgency, share of grade, effort) and the URGENT / HIGH / MEDIUM / LOW tiers.
- Morning digest; one combined reminder every 2 hours while anything is due within 24 hours; quiet hours; an overnight warning; one overdue notice.
- ✅ Done, 💤 Snooze, ↩️ Undo and 🔕 Stop buttons; the `/today`, `/week`, `/digest`, `/sync`, `/status` and `/pause` commands.
- Deterministic send keys with atomic claims, so there are no duplicate messages across restarts.
- A hardened Docker image (non-root, read-only filesystem, no capabilities) and CI on GitHub Actions.
- A 20-day minute-by-minute simulation test across a daylight-saving change, property-based tests and secret-leak tests.

### Fixed (from an independent review)
- A multi-page planner could hide changes behind a page-1 ETag.
- Docker secrets were unreadable by the non-root user.
- Non-Canvas errors aborted a tick.
- A permission-only 401 raised a false token alert.
- Stale data wasn't labelled.
- Split messages were resent in full after a crash.
- Startup errors could print a token.
- The scheduler drifted past minute boundaries.

[Unreleased]: https://github.com/rmaytr/CanvasAssignmentTrackingBot/compare/a869d92...HEAD
[0.2.0]: https://github.com/rmaytr/CanvasAssignmentTrackingBot/tree/a869d92
[0.1.0]: https://github.com/rmaytr/CanvasAssignmentTrackingBot/tree/92c923d
