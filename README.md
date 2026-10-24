# Canvas Assignment Tracker Bot

A Telegram bot that reads your Canvas To Do list and keeps you ahead of deadlines:

- **A morning list** at the time you choose: everything due in the next two weeks, ranked by urgency and share of your grade.
- **Every 2 hours in the last 24 hours** before a deadline: one combined reminder, until Canvas shows it submitted or you tap **✅ Done**.
- **💤 Snooze**, quiet hours, a warning before work that's due overnight, and one notice if something becomes overdue.

**Friends mode:** one person hosts the bot on a small server, then invites friends with one-time links. Each friend signs up in the chat in about two minutes, with their own school, Canvas token (stored encrypted), time zone, morning time and quiet hours. The bot only reads from Canvas.

- **Host it:** [`docs/setup/host-the-bot.md`](docs/setup/host-the-bot.md): one install command on a free Google Cloud (or Oracle, or home) server.
- **Join it:** [`docs/setup/friends-guide.md`](docs/setup/friends-guide.md): what to send your friends.
- **Design:** [`docs/PRD.md`](docs/PRD.md) and [`docs/superpowers/specs/2026-10-24-friends-mode-design.md`](docs/superpowers/specs/2026-10-24-friends-mode-design.md).

Why no SMS? A bot has to rent a phone number and register with US carriers (about $20 up front plus $7–8 a month), and the free email-to-text gateways have shut down. Telegram is free and has buttons.

License: [Apache-2.0](LICENSE).
