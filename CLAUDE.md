# CLAUDE.md

Telegram bot that reads Canvas LMS To Do lists and sends a ranked morning list plus 2-hourly reminders until work is submitted. **Friends mode (v0.2):** one shared, invite-only bot; each user signs up in chat; private beta with 6 users. Owner deploys with `deploy/install.sh` on a Debian/Ubuntu VM (Docker Compose).

Read before changing things: `README.md`, `docs/architecture.md`, `docs/how-it-works.md`, `CONTRIBUTING.md`.

## Commands

```sh
uv sync                         # install (Python 3.13+, uv)
uv run pytest -m "not slow"     # fast suite (~25 s); full `uv run pytest` ~5 min (20-day simulation)
uv run ruff check && uv run ruff format --check && uv run mypy src tests   # must pass (CI)
uv run pip-audit                # CI fails on known vulnerabilities
```

## Layout and rules

- `src/canvas_tracker/domain`, `planning`, `render` are **pure** (no I/O, no clock). Ranking/scheduling changes go there, with tests.
- `hub/` is the multi-user layer (registry, Fernet-encrypted tokens, sign-up state machine, Telegram routing). Each user has their own SQLite file and `Tenant`; never add code that reads across users.
- All user-facing text lives in `render/copy.py`.
- DB changes are **new** numbered migrations (`store/migrations/`, `hub/migrations/`); never edit old ones.
- Times are UTC internally; convert to the user's zone only at the edges.
- Test first; bug fixes need a regression test. If behaviour changes on purpose, regenerate `tests/integration/golden/simulation.txt` with `--update-golden` and review the diff.
- Never put real tokens or Canvas data in code, tests or commits.
- Conventional commits (`feat:`, `fix:`, `docs:` …). Update `CHANGELOG.md` under Unreleased for user-visible changes.

## Known open items

- Instructure's API policy disfavours users pasting personal tokens into a shared app; public launch needs OAuth or the calendar-feed (iCal) mode (roadmap in README).
- Deferred minors: no rate limit on token attempts or `/sync`; DNS rebinding only checked at sign-up; old buttons can act on a new item after `/disconnect` and re-join; abandoned sign-ups use `MAX_USERS` slots; sign-up intro hard-codes "2 hours / 14 days".
