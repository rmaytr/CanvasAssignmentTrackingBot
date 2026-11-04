# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Optional email.** `/email you@school.edu` (confirmed with a 6-digit code sent to that address) adds an email copy of the morning list and one email 2 hours before each deadline. Assignments due at the same time share one email. Deadline emails wait out quiet hours and `/pause`, and are never sent after the deadline. `/email off` or `/disconnect` deletes the address. Telegram messages are unchanged.
- Works with any SMTP provider (Brevo, Gmail, your own domain): `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `EMAIL_FROM`, `EMAIL_FROM_NAME` in `.env`, with the password in `secrets/smtp_password.txt`. Email is off unless `SMTP_HOST` is set. See the hosting guide.

### Security
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
