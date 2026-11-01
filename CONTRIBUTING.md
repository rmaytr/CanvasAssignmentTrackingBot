# Contributing

Thanks for your interest! Bug reports, ideas and pull requests are all welcome. This guide gets you from a clone to a green pull request.

## Ground rules

- **Never** paste a real Canvas or Telegram token into an issue, a pull request, a test or a commit. Use obviously fake values (the tests use `4242~SENTINEL…`).
- Real Canvas data in tests must go through the scrubber in [`spike/`](spike/README.md) first; a test fails if a fixture still looks personal.
- Security problems go through [private reporting](SECURITY.md), not public issues.
- Be kind. See the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setup

You need **Python 3.13+** and **[uv](https://docs.astral.sh/uv/)**. uv installs the right Python by itself if needed.

```sh
git clone https://github.com/rmaytr/CanvasAssignmentTrackingBot.git
cd CanvasAssignmentTrackingBot
uv sync                       # creates .venv with runtime + dev dependencies (locked)
uv run pre-commit install     # optional: run the checks on every commit
uv run pytest -m "not slow"   # ~25 s
```

To run the bot itself locally, create a test bot with @BotFather and run:

```sh
export TELEGRAM_BOT_TOKEN='123456:your-test-bot-token'
export TOKEN_KEY="$(uv run python -m canvas_tracker genkey)"
export DATA_DIR=./.data
uv run python -m canvas_tracker     # prints a pairing code: send /start CODE to your test bot
```

## Before you open a pull request

CI runs these, and all must pass:

```sh
uv run ruff check              # lint (incl. Bandit security rules)
uv run ruff format --check     # formatting
uv run mypy src tests          # strict typing
uv run pytest                  # full suite incl. the 20-day simulation (~5 min)
uv run pip-audit               # known vulnerabilities in dependencies
```

## How the code is organized

Read [Architecture](docs/architecture.md) first. The short version:

- **`domain/`, `planning/` and `render/` are pure.** No I/O, no clock, no globals. Behaviour changes to ranking or scheduling go here, with tests.
- **I/O lives at the edges:** `sources/` (Canvas), `store/` (SQLite), `notify/` (Telegram), `runtime/` (loop), `bot/` and `hub/` (chat).
- **All user-facing text lives in [`render/copy.py`](src/canvas_tracker/render/copy.py).** Change the wording there, not inline.
- **Database changes are new numbered migrations** (`store/migrations/000N_*.sql` or `hub/migrations/`). Never edit an existing one.

## Conventions

- **Test first.** Write a failing test that shows the bug or the new behaviour, then make it pass. Bug fixes always come with a regression test.
- **Times are UTC** everywhere inside the program. Convert to the user's zone only when rendering or reading their settings. The models reject naive datetimes.
- **Types:** everything must pass `mypy --strict`; avoid `Any` and `# type: ignore` unless there's no other way, and explain why on the same line.
- **Simulation golden file:** if you change behaviour on purpose, run `uv run pytest tests/integration/test_simulation.py --update-golden` and review the diff line by line in your pull request.
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `build:`, `refactor:`. The body explains *why*.
- **Dependencies** are added with `uv add` (runtime) or `uv add --dev`, and pinned to a compatible range.

## Pull requests

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Keep each pull request focused on one change.
3. Fill in the template: what changed, why, how you tested it, and any user-visible change to messages.
4. Add an entry under **Unreleased** in [`CHANGELOG.md`](CHANGELOG.md) for user-visible changes.
