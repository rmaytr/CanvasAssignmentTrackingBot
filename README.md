# Canvas Assignment Tracker Bot

A self-hosted bot that reads your Canvas To Do list and keeps you ahead of deadlines:

- **08:00 digest** on Telegram: everything due in the next two weeks, ranked by urgency and share of your grade.
- **Every 2 hours in the last 24 hours** before a deadline: one combined reminder, until Canvas shows it submitted or you tap **✅ Done**.
- **💤 Snooze**, quiet hours (midnight to 08:00 by default), and a warning before work that's due overnight.

It runs for one student, on their own computer or a small server, with their own Canvas token. It only reads from Canvas.

**Status:** personal MVP. See [`docs/setup/run-mvp.md`](docs/setup/run-mvp.md) to run it, and
[`docs/PRD.md`](docs/PRD.md) for the full design. Public v1.0 (calendar-feed mode for schools that block tokens, email backup, hosting guides) is next.

Why no SMS? A bot has to rent a phone number and register with US carriers (about $20 up front plus $7–8 a month), and the free email-to-text gateways have shut down. Telegram is free and has buttons.

License: [Apache-2.0](LICENSE).
