# M1 acceptance: personal MVP

Run this yourself, against your real Canvas account and Telegram, after
following [`docs/setup/host-the-bot.md`](setup/host-the-bot.md). It checks the PRD §11.6
items and the M1 exit criteria (PRD §15): **14 days with no duplicate
messages, no false nags, and every digest on time.**

## One-time checks

- [ ] **Install:** the install command finishes, `sudo docker compose ps` shows the bot `healthy` (not restarting) and the logs show no "can't be read".
- [ ] **Owner pairing:** the `/start <code>` the installer printed makes you the owner and starts your sign-up.
- [ ] **Strangers:** a message from a Telegram account without an invite gets no reply; `/start` without a valid invite gets only the "invite-only" answer.
- [ ] **Friend sign-up:** a friend at another school joins with an `/invite` link in about 2 minutes; their token message disappears from the chat; their morning list arrives at their chosen time in their own time zone.
- [ ] **Isolation:** your `/today` and your friend's `/today` only ever show each person's own assignments; `/users` shows names and schools but no assignments.
- [ ] **Settings:** `/settings` changes to time zone, morning time and quiet hours take effect the same day; a morning time inside quiet hours is refused.
- [ ] **Leaving:** `/disconnect` (and `/remove N` for the owner) deletes that person's data; they're ignored afterwards.
- [ ] **First digest:** at 08:00 (or `/digest`) the list matches your Canvas To Do list, ranked sensibly.
- [ ] **Submission stops reminders:** for something due within 24 hours, submit it in Canvas. No reminder follows after the next sync (≤10 minutes).
- [ ] **New Quiz:** the same check for a New Quiz (spike S2).
- [ ] **Done on offline work:** tap ✅ Done on a paper or in-class item. It leaves the next reminder; ↩️ Undo within 10 minutes brings it back.
- [ ] **Snooze:** tap 💤 2h. The item skips the next reminder, then comes back once.
- [ ] **Quiet hours:** nothing arrives between 00:00 and 08:00; anything due overnight gets the 23:30 warning.
- [ ] **Revoked token:** delete a test token in Canvas while the bot uses it. Exactly one 🔑 alert; after you paste a new one via `/settings → 🔑 Canvas token`, `/sync` works without a restart.
- [ ] **Restart mid-cycle:** `docker compose restart bot` while reminders are active. No duplicate message; the next reminder arrives on schedule.
- [ ] **Network outage:** unplug the network for an hour. No burst of messages afterwards; a digest sent while offline data is old shows the ⚠️ stale banner.

## 14-day log

| Date | Digest time | Reminders | False nags | Duplicates | Notes |
|---|---|---|---|---|---|
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |

When the log shows 14 clean days, M1 is done and the M2 (public v1.0) plan can be written.
