# Canvas Assignment Tracker Bot: M0 Spike + M1 Personal MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-user, self-hosted bot that reads the owner's Canvas Planner with their access token, sends a ranked 08:00 digest, and sends one combined Telegram reminder every 2 hours for work due within 24 hours, stopping when the work is submitted or marked Done.

**Architecture:** One asyncio process runs two things:
- the python-telegram-bot application (long polling)
- a 60-second tick loop.

The core is pure. `domain/` (done rule, status, priority) and `planning/` (`plan(now, snapshot, settings) -> Plan`) do no I/O and never read the clock. The I/O layers around them (Canvas client, SQLite store, notifiers, bot handlers, runtime) are thin and swappable for fakes in tests. Every message has a deterministic send key, protected by a UNIQUE constraint.

**Tech Stack:**

| Area | Choice |
|---|---|
| Language | Python ≥3.13 |
| Packaging | uv 0.11 |
| Telegram | python-telegram-bot 22.8 |
| HTTP | httpx 0.28 |
| Settings | pydantic-settings 2.16 |
| Time | `zoneinfo` + tzdata |
| Database | stdlib `sqlite3` |
| Tests | pytest 9, pytest-asyncio 1.4, time-machine 3.5, Hypothesis 6, respx 0.23 |
| Lint and types | ruff 0.17, mypy 2.4 |
| Packaging for hosts | Docker |

**Spec:** [`docs/PRD.md`](../../PRD.md), approved 2026-10-16. Section references (§) below point there.

**Scope of this plan:** M0 (spike toolkit) and M1 (personal MVP, Mode A only) from PRD §15. M2 (public v1.0) gets its own plan once M1 has run for two weeks, because it depends on spike results (S1 decides how Mode B handles all-day events). Deferred to M2, not built here:
- Mode B (calendar feed) and email
- token-expiry warnings, the circuit-breaker alerts and the healthchecks.io heartbeat
- full supply-chain hardening (CodeQL, zizmor, attestations, release workflow) and public docs
- mutation testing

## Global Constraints

Every task implicitly includes these:

- Python `>=3.13`; CI runs on 3.13 and 3.14. Package `canvas_tracker` under `src/`, managed with `uv` and a committed `uv.lock`.
- All stored and compared times are timezone-aware UTC. Local rendering uses `zoneinfo.ZoneInfo(settings.tz)` with the `tzdata` dependency. **Naive datetimes are banned** (ruff `DTZ`), and so is reading the host's local time zone.
- `domain/` and `planning/` import nothing from `sources/`, `store/`, `notify/`, `bot/` or `runtime/`, do no I/O, and never call `datetime.now()`. The clock is always passed in as `now`.
- Canvas access is **GET only** in v1 (§10.2), with one request in flight at a time.
- Every Canvas request sends the header `User-Agent: CanvasAssignmentTrackingBot/<version> (+https://github.com/rmaytr/CanvasAssignmentTrackingBot)`.
- Canvas HTTP never follows redirects, and only follows pagination `Link` URLs whose scheme and host exactly match `CANVAS_BASE_URL`.
- Telegram:
  - HTML parse mode only.
  - Every Canvas-sourced string is escaped (`&`, `<`, `>`, and `"` inside attributes).
  - Messages are at most 4,096 characters.
  - `callback_data` is at most 64 bytes.
  - Link previews are off.
  - Only the owner's private chat is served.
  - Long polling only.
- Secrets (Canvas token, Telegram token) never appear in logs, exceptions, the database or fixtures. Each one is accepted as `X` or `X_FILE`.
- Defaults (§7.8):

  | Setting | Default |
  |---|---|
  | `DIGEST_TIME` | `08:00` |
  | `DIGEST_GRACE_UNTIL` | `12:00` |
  | `DIGEST_LOOKAHEAD_DAYS` | `14` |
  | `REMINDER_WINDOW_HOURS` | `24` |
  | `REMINDER_INTERVAL_MINUTES` | `120` (minimum `30`) |
  | `QUIET_HOURS` | `00:00-08:00` |
  | `OVERDUE_REMINDERS` | `false` |
  | `OVERDUE_REMINDER_MAX_HOURS` | `48` |
  | `ITEM_RETENTION_DAYS` | `30` |
  | Notification-row retention | 60 days |
  | `DB_PATH` | `/data/bot.db` |
  | `LOG_LEVEL` | `INFO` |

- Fixed rule constants (§7.4–7.5), defined once in `domain/models.py`:

  | Constant | Value |
  |---|---|
  | `SLOT_GRACE` | 30 min |
  | `DIGEST_FOLD` | 15 min |
  | `OVERNIGHT_LEAD` | 30 min |
  | `OVERDUE_NOTICE_GRACE` | 2 h |
  | `SNOOZE_END_GRACE` | 30 min |
  | `SNOOZE_LENGTH` | 2 h |
  | `SNOOZE_MIN_LEFT` | 30 min |
  | `OVERDUE_SECTION_MAX` | 7 days |
  | `STALE_AFTER` | 30 min |
  | `UNDO_WINDOW` | 10 min |
  | `FRESHNESS` | 5 min |

- All user-facing English text lives in `src/canvas_tracker/render/copy.py` (the PRD asks for strings in one place).
- Quality gates (§11.4):
  - `ruff check` (rule sets `E,F,W,I,B,UP,SIM,S,DTZ,RUF,ASYNC`), `ruff format --check`, `mypy --strict`
  - branch coverage ≥95% for `domain/` and `planning/`, ≥85% overall.
- Test layout: `tests/unit/`, `tests/property/`, `tests/integration/`, `tests/contract/`. Shared factories go in `tests/factories.py`. Run tests with `uv run pytest`.
- Read-only rule for whoever builds this: **never ask for, receive or use the owner's real tokens** (§15.1). Anything that needs real accounts is an owner step.

## Review Focus

Inputs the spec implies but doesn't spell out, most likely to bite first. Each one has a test added to the task that owns the code:

1. **Planner items with `"submissions": false`, a missing `planner_override`, or no `plannable_date`.** Expected: mapped with default flags, or skipped when there's no date, and never crashing the sync. *(Task 17)*
2. **Courses where points total 0, group weights are 0, or `points_possible` is null.** Expected: grade share is `None` ("weight unknown"), never a ZeroDivisionError. *(Task 5)*
3. **Finals week with 40+ urgent items.** Expected: the reminder splits into several messages, each ≤4,096 characters, with at most 30 items (90 buttons) per message, under Telegram's 100-button keyboard limit. *(Task 11)*
4. **The host's own time zone differs from `TIMEZONE`** (containers run in UTC). Expected: identical output whatever the host's `TZ` is. *(Task 10)*
5. **A token secret file with a trailing newline, surrounding spaces, or nothing in it.** Expected: whitespace is stripped; an empty file fails at startup with a readable message naming the variable. *(Task 14)*

---

### Task 1: Project scaffold and CI gates

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `src/canvas_tracker/__init__.py`, `src/canvas_tracker/py.typed`, `tests/__init__.py`, `tests/unit/test_version.py`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `LICENSE` (Apache-2.0 text)
- Modify: `.gitignore` (add `.venv/`, `.env`, `*.db`, `*.db-wal`, `*.db-shm`, `secrets/`, `spike/out/`, `.coverage`, `htmlcov/`, `.hypothesis/`)

**Interfaces:**
- Produces: `canvas_tracker.__version__: str = "0.1.0"`

- [ ] **Step 1: Write the failing test** in `tests/unit/test_version.py`

```python
import canvas_tracker

def test_version() -> None:
    assert canvas_tracker.__version__ == "0.1.0"
```

- [ ] **Step 2: Write `pyproject.toml`**
  - Build backend: `hatchling`. `requires-python = ">=3.13"`.
  - Runtime dependencies: `python-telegram-bot>=22.8,<23`, `httpx>=0.28,<0.29`, `pydantic-settings>=2.16,<3`, `tzdata>=2026.5`.
  - Dev dependency group: `pytest>=9.1`, `pytest-asyncio>=1.4`, `pytest-cov>=7.1`, `time-machine>=3.5`, `hypothesis>=6.170`, `respx>=0.23`, `ruff>=0.17`, `mypy>=2.4`, `pre-commit>=4.7`, `pip-audit>=2.10`.
  - `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `pythonpath = ["."]` (so tests can import `tests.factories` and `spike.scrub`), marker `slow`, `addopts = "--strict-markers"`.
  - `[tool.ruff]`: `line-length = 100`, `target-version = "py313"`, `lint.select = ["E","F","W","I","B","UP","SIM","S","DTZ","RUF","ASYNC"]`, per-file ignore `tests/** = ["S101","S105","S106"]`.
  - `[tool.mypy]`: `strict = true`, `plugins = ["pydantic.mypy"]`.
  - `[tool.coverage.run]`: `branch = true`, `source = ["canvas_tracker"]`.

- [ ] **Step 3: Run `uv lock && uv sync`.** Expected: `uv.lock` is created with no errors.

- [ ] **Step 4: Run the test.** `uv run pytest tests/unit/test_version.py -v`. Expected: FAIL (`AttributeError` or import error).

- [ ] **Step 5: Add `__version__ = "0.1.0"`** to `src/canvas_tracker/__init__.py`, then re-run. Expected: PASS.

- [ ] **Step 6: Write `.github/workflows/ci.yml`**
  - Top-level `permissions: {}`. Triggers: `push` and `pull_request`.
  - Job `lint`: `contents: read`; runs `uv run ruff check`, `uv run ruff format --check` and `uv run mypy src tests`.
  - Job `test`: matrix `python: ["3.13","3.14"]`. Runs `uv run pytest --cov --cov-fail-under=85`, then `uv run coverage report --include="src/canvas_tracker/domain/*,src/canvas_tracker/planning/*" --fail-under=95`.
  - Job `audit`: `uv run pip-audit`.
  - Pin `actions/checkout` and `astral-sh/setup-uv` to the **full commit SHA** of their latest release, with the tag in a trailing comment.
  - No `pull_request_target`.

- [ ] **Step 7: Write `.pre-commit-config.yaml`** with hooks for ruff (check and format) and gitleaks, pinned by `rev`. Run `uv run pre-commit run --all-files`. Expected: all hooks pass.

- [ ] **Step 8: Commit.** `git add -A && git commit -m "chore: scaffold package, CI gates and pre-commit"`

---

### Task 2: Spike toolkit (M0), for the owner to run

These are throwaway scripts that settle S1–S8 (§17). They **live outside the package** and are never imported by it. Only the scrubber gets real tests, because it guards secrets.

**Files:**
- Create: `spike/README.md`, `spike/probe_canvas.py`, `spike/probe_ical.py`, `spike/probe_telegram.py`, `spike/scrub.py`, `docs/spike-notes.md`, `tests/unit/test_scrub.py`

**Interfaces:**
- Produces: `spike.scrub.scrub(obj: Any, canvas_host: str) -> Any` and the CLI `uv run python spike/scrub.py --host <canvas host> <in_dir> <out_dir>`, which writes fixtures under `tests/fixtures/canvas/`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_scrub.py`

```python
from spike.scrub import scrub

RAW = {
    "html_url": "https://canvas.school.edu/courses/12/assignments/34?access_token=1234~AbCdEfGhIjKlMnOpQrStUvWxYz",
    "title": "Essay about Jane Doe",
    "context_name": "BIO 201 - Section 4",
    "description": "<p>secret instructions</p>",
    "user": {"name": "Jane Doe", "email": "jane@school.edu", "id": 987654},
    "nested": [{"note": "token 5678~ZyXwVuTsRqPoNmLkJiHgFeDcBa here"}],
}

def test_scrub_removes_tokens_emails_names_host_and_descriptions() -> None:
    out = repr(scrub(RAW, canvas_host="canvas.school.edu"))
    for needle in ["1234~", "5678~", "jane@school.edu", "Jane Doe", "canvas.school.edu",
                   "secret instructions", "987654"]:
        assert needle not in out
    assert "canvas.example.edu" in out

def test_scrub_is_deterministic_and_keeps_structure() -> None:
    a, b = scrub(RAW, "canvas.school.edu"), scrub(RAW, "canvas.school.edu")
    assert a == b
    assert set(a) == set(RAW) - {"description"}
```

- [ ] **Step 2: Run them.** `uv run pytest tests/unit/test_scrub.py -v`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `scrub()`** in `spike/scrub.py`, with `spike/__init__.py`.
  - Delete the keys `description`, `message` and `body` wherever they appear.
  - Replace these, wherever they appear in any string:
    - Canvas tokens matching `\d{1,6}~[A-Za-z0-9]{20,}` → `REDACTED_TOKEN`
    - emails → `user@example.edu`
    - the host → `canvas.example.edu`
  - Replace values of the keys `title`, `name`, `display_name`, `short_name`, `sortable_name`, `context_name` and `course_code` with stable placeholders such as `Title 1` or `Course 1`, numbered by first appearance.
  - Replace integer values under the keys `id` and `user_id` inside a `user` object with stable fake IDs starting at 1000.
  - Add a CLI that processes every `*.json` file in a directory.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Write the probe scripts** (plain httpx, no tests).
  - **`probe_canvas.py --base-url URL --token-file PATH`.** It never takes the token as a command-line argument, because arguments are visible in `ps` and shell history.
    - It calls these endpoints and saves raw responses to `spike/out/`:
      - `GET /api/v1/users/self`
      - `GET /api/v1/users/self/profile`
      - `GET /api/v1/planner/items` (the PRD §7.1 parameters), plus a second call with `If-None-Match` to record 304 behavior
      - `GET /api/v1/courses?enrollment_state=active`
      - `GET /api/v1/courses/:id/assignment_groups?include[]=assignments` for each course
      - `GET /api/v1/users/self/tokens` (S3)
    - It prints which of S3–S7 the data answers.
    - It sends the `User-Agent` header and makes **only** GET requests.
  - **`probe_ical.py --feed-file PATH`** (S1). Downloads the feed, then prints each event's UID prefix, whether `DTSTART` is a DATE or a DATE-TIME, and the count per type.
  - **`probe_telegram.py --token-file PATH --chat-id N`** (S8). Sends:
    - an HTML message with escaped tricky titles
    - a 4,096-character message, then a 4,097-character one (expected to be rejected)
    - a message with `disable_notification=True`
    - an inline keyboard that the script edits after a button press.
  - **`spike/README.md`** says these are for the owner only, run on their own machine; `spike/out/` is git-ignored; scrub before committing anything.

- [ ] **Step 6: Write `docs/spike-notes.md`**: a template with one heading per S1–S8 and Q5, each with "Result:" and "Evidence (scrubbed fixture file):" lines.

- [ ] **Step 7: Commit.** `git add spike docs/spike-notes.md tests/unit/test_scrub.py && git commit -m "feat(spike): owner-run Canvas/iCal/Telegram probes and fixture scrubber"`

- [ ] **Step 8 (owner):** Run the probes, scrub the outputs into `tests/fixtures/canvas/`, fill in `docs/spike-notes.md`, and commit. **Tasks 3–23 don't wait for this; Task 26 does.**

---

### Task 3: Domain models and test factories

**Files:**
- Create: `src/canvas_tracker/domain/__init__.py`, `src/canvas_tracker/domain/models.py`, `tests/factories.py`, `tests/unit/test_models.py`

**Interfaces:**
- Produces (all `@dataclass(frozen=True, slots=True, kw_only=True)` unless noted):
  - `class ItemType(StrEnum)`: `ASSIGNMENT="assignment"`, `QUIZ="quiz"`, `DISCUSSION="discussion_topic"`, `SUB_ASSIGNMENT="sub_assignment"`, `PEER_REVIEW="peer_review"`, `PAGE="wiki_page"`, `NOTE="planner_note"`, `EVENT="calendar_event"`, `OTHER="other"`.
  - `Item`. Canvas-owned fields:
    - `plannable_type: str`, `plannable_id: int`, `title: str`, `type: ItemType`
    - `course_id: int | None = None`, `course_name: str = ""`, `assignment_id: int | None = None`
    - `due_at: datetime | None = None`, `lock_at: datetime | None = None`, `html_url: str | None = None`
    - `points_possible: float | None = None`, `submission_types: tuple[str, ...] = ()`
    - `assignment_group_id: int | None = None`, `omit_from_final_grade: bool = False`
    - `submitted`, `excused`, `graded`, `late`, `missing`, `redo_request`: all `bool = False`
    - `marked_complete: bool | None = None` (`None` means no override; `False` means the student explicitly un-marked it).

    Bot-owned fields:
    - `db_id: int | None = None`, `bot_done_at: datetime | None = None`, `bot_done_due_at: datetime | None = None`
    - `snoozed_until: datetime | None = None`, `stop_reminders: bool = False`
    - `done_seen_at: datetime | None = None`, `gone_at: datetime | None = None`

    Property `ref -> str`, returning `f"{plannable_type}-{plannable_id}"`.
  - `Course(id: int, code: str, name: str, apply_group_weights: bool = False, total_points: float = 0.0)`
  - `AssignmentGroup(id: int, course_id: int, name: str, group_weight: float, total_points: float)`
  - `AssignmentDetail(assignment_id: int, points_possible: float | None, submission_types: tuple[str, ...], assignment_group_id: int | None, omit_from_final_grade: bool, lock_at: datetime | None)`
  - `Enrichment(courses: tuple[Course, ...], groups: tuple[AssignmentGroup, ...], details: Mapping[int, AssignmentDetail])`
  - `Cycle(anchor: datetime)`
  - `Settings`:
    - `tz: str` (an IANA name, validated with `ZoneInfo(tz)` in `__post_init__`)
    - `digest_time: time = time(8, 0)`, `digest_grace_until: time = time(12, 0)`, `digest_lookahead: timedelta = timedelta(days=14)`
    - `reminder_window: timedelta = timedelta(hours=24)`, `reminder_interval: timedelta = timedelta(minutes=120)`
    - `quiet_start: time | None = time(0, 0)`, `quiet_end: time | None = time(8, 0)`
    - `overdue_reminders: bool = False`, `overdue_reminder_max: timedelta = timedelta(hours=48)`
    - `canvas_host: str = ""`

    Property `zone -> ZoneInfo`.
  - `Snapshot`: `items: tuple[Item, ...]`, `courses: Mapping[int, Course]`, `groups: Mapping[int, AssignmentGroup]`, `sent_keys: frozenset[str]`, `last_reminded_at: Mapping[str, datetime]` (keyed by `Item.ref`), `cycle: Cycle | None`, `pause_until: datetime | None`, `last_successful_sync_at: datetime | None`, `auth_failed_since: datetime | None`.
  - `class SendKind(StrEnum)`: `DIGEST`, `REMINDER`, `NEW_URGENT`, `SNOOZE_END`, `OVERNIGHT`, `OVERDUE`, `AUTH_ALERT`, lowercase values.
  - `Send(key: str, kind: SendKind, item_refs: tuple[str, ...] = ())`
  - `Plan(sends: tuple[Send, ...] = (), open_cycle_at: datetime | None = None, close_cycle: bool = False)`
  - `REMINDER_KINDS = frozenset({SendKind.DIGEST, SendKind.REMINDER, SendKind.NEW_URGENT, SendKind.SNOOZE_END})`: the kinds that count toward `last_reminded_at`.
  - The fixed rule constants from Global Constraints, as `timedelta`s.
- Produces (tests): `tests/factories.py` with:
  - `NOW = datetime(2026, 10, 20, 16, 0, tzinfo=UTC)` (Tue 12:00 in New York)
  - `make_item(*, due_in: timedelta | None = timedelta(hours=10), now: datetime = NOW, **overrides) -> Item`. Defaults: an assignment, `plannable_id` auto-incrementing from 1, title `"Homework"`, `course_id=1`, `points_possible=10.0`, `submission_types=("online_upload",)`.
  - `make_settings(**overrides) -> Settings`, with `tz="America/New_York"`.
  - `make_snapshot(items=(), **overrides) -> Snapshot`, with empty mappings and `last_successful_sync_at=NOW`.

- [ ] **Step 1: Write the failing tests**

```python
def test_item_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="due_at must be timezone-aware UTC"):
        make_item(due_at=datetime(2026, 10, 20, 12, 0))  # noqa: DTZ001

def test_item_rejects_non_utc_offset() -> None:
    with pytest.raises(ValueError, match="UTC"):
        make_item(due_at=datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("America/New_York")))

def test_item_ref() -> None:
    assert make_item(plannable_type="quiz", plannable_id=7).ref == "quiz-7"

def test_settings_rejects_unknown_zone() -> None:
    with pytest.raises(ValueError):
        make_settings(tz="Mars/Olympus")
```

- [ ] **Step 2: Run them.** `uv run pytest tests/unit/test_models.py -v`. Expected: FAIL (import error).

- [ ] **Step 3: Implement `models.py`.**
  - `Item.__post_init__` checks every datetime field: `tzinfo is not None` and `utcoffset() == timedelta(0)`. Otherwise it raises `ValueError(f"{name} must be timezone-aware UTC")`.
  - `Settings.__post_init__` raises `ValueError` if the zone can't be loaded or `reminder_interval < timedelta(minutes=30)`.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -am "feat(domain): core dataclasses, rule constants and test factories"` (after `git add` for the new files).

---

### Task 4: Done rule and item status

**Files:**
- Create: `src/canvas_tracker/domain/done_rule.py`, `src/canvas_tracker/domain/status.py`, `tests/unit/test_done_rule.py`, `tests/unit/test_status.py`

**Interfaces:**
- Consumes: `Item`, `Settings`, and the constants from Task 3.
- Produces:
  - `class DoneSource(StrEnum)`: `CANVAS_MARKED`, `SUBMITTED`, `EXCUSED`, `GRADED_OFFLINE`, `BOT`.
  - `OFFLINE_SUBMISSION_TYPES = frozenset({"on_paper", "none", "external_tool"})`
  - `done_source(item: Item) -> DoneSource | None`, `is_done(item: Item) -> bool`
  - `REMINDABLE_TYPES: frozenset[ItemType]`: every type except `EVENT`.
  - `hours_left(item: Item, now: datetime) -> float | None`
  - `is_overdue_accepting(item: Item, now: datetime) -> bool`: true when the item is not done, not gone, `due_at <= now < due_at + OVERDUE_SECTION_MAX`, and `lock_at` is `None` or later than `now`.
  - `is_urgent(item: Item, now: datetime, settings: Settings) -> bool`: true when the type is remindable, the item is not done, `gone_at` is `None`, and either:
    - `0 < due_at - now <= reminder_window`, or
    - `overdue_reminders` is on, `not stop_reminders`, `due_at <= now < due_at + overdue_reminder_max`, and `lock_at` is `None` or later than `now`.
  - `is_active(item: Item, now: datetime, settings: Settings, pause_until: datetime | None) -> bool`: `is_urgent`, and not snoozed (`snoozed_until > now`), not `stop_reminders`, and not paused (`pause_until > now`).

**Done rule, in order** (§7.2, plus one refinement that matches Canvas):
1. `redo_request` → `None` (not done).
2. `marked_complete is True` → `CANVAS_MARKED`.
3. `submitted` and `marked_complete is not False` → `SUBMITTED`.
4. `excused` → `EXCUSED`.
5. `graded` and `submission_types` is non-empty and every type is in `OFFLINE_SUBMISSION_TYPES` and `marked_complete is not False` → `GRADED_OFFLINE`.
6. `bot_done_at is not None` and `bot_done_due_at == due_at` → `BOT`.
7. Otherwise → `None`.

The refinement: an explicit Canvas "un-mark" (`marked_complete is False`) overrides rules 3 and 5, as it does in Canvas's own `lib/plannable.rb`. *(Plan decision: the PRD table didn't cover explicit un-marking.)*

- [ ] **Step 1: Write the failing table test** (`tests/unit/test_done_rule.py`)

```python
CASES = [
    ("redo beats submitted", dict(submitted=True, redo_request=True), None),
    ("marked complete", dict(marked_complete=True), DoneSource.CANVAS_MARKED),
    ("submitted", dict(submitted=True), DoneSource.SUBMITTED),
    ("submitted but un-marked", dict(submitted=True, marked_complete=False), None),
    ("excused", dict(excused=True, missing=True), DoneSource.EXCUSED),
    ("graded offline", dict(graded=True, submission_types=("on_paper",)), DoneSource.GRADED_OFFLINE),
    ("graded zero online stays open", dict(graded=True, submission_types=("online_upload",)), None),
    ("mixed types not offline", dict(graded=True, submission_types=("on_paper", "online_upload")), None),
    ("graded no types", dict(graded=True, submission_types=()), None),
]

@pytest.mark.parametrize(("name", "fields", "expected"), CASES, ids=[c[0] for c in CASES])
def test_done_source(name: str, fields: dict[str, object], expected: DoneSource | None) -> None:
    assert done_source(make_item(**fields)) == expected

def test_bot_done_holds_until_due_changes() -> None:
    item = make_item()
    done = replace(item, bot_done_at=NOW, bot_done_due_at=item.due_at)
    assert done_source(done) is DoneSource.BOT
    extended = replace(done, due_at=item.due_at + timedelta(days=2))
    assert done_source(extended) is None
```

- [ ] **Step 2: Write the failing status tests** (`tests/unit/test_status.py`) with exact edges:
  - `is_urgent` is true at `due_in=24h` and false at `24h + 1s`, at `0s`, and at `-1s` (when overdue reminders are off).
  - It is false for an `EVENT` item, for a gone item, and for a done item.
  - With `overdue_reminders=True`: true at `-1h`; false at `-48h`; false when `lock_at = now - 1min`; false when `stop_reminders`.
  - `is_active` is false when `snoozed_until = now + 1min`, true when `snoozed_until = now`, and false when `pause_until = now + 1min`.
  - `is_overdue_accepting`: true at `-6d23h`, false at `-7d`, false when locked.

- [ ] **Step 3: Run them.** `uv run pytest tests/unit/test_done_rule.py tests/unit/test_status.py -v`. Expected: FAIL.

- [ ] **Step 4: Implement both modules** as specified.

- [ ] **Step 5: Run the tests.** Expected: PASS.

- [ ] **Step 6: Commit.** `git commit -m "feat(domain): done rule and urgency/active status"`

---

### Task 5: Prioritization

**Files:**
- Create: `src/canvas_tracker/domain/priority.py`, `tests/unit/test_priority.py`

**Interfaces:**
- Consumes: `Item`, `Course`, `AssignmentGroup`, `is_done`, `is_overdue_accepting`, `hours_left`.
- Produces:
  - `class Tier(StrEnum)`: `URGENT`, `HIGH`, `MEDIUM`, `LOW`.
  - `PriorityConfig` (frozen) holding every threshold below; `DEFAULT_PRIORITY = PriorityConfig()`.
  - `Score(urgency: int, importance: int, effort: int, tier: Tier, grade_share: float | None, effort_hours: float)` with property `total`.
  - `grade_share(item: Item, course: Course | None, group: AssignmentGroup | None) -> float | None`
  - `effort_hours(item: Item) -> float`
  - `score(item: Item, now: datetime, course: Course | None, group: AssignmentGroup | None, config: PriorityConfig = DEFAULT_PRIORITY) -> Score`

**Values (§7.3):**
- **Urgency:** overdue and accepting = 50 · ≤24 h = 45 · ≤48 h = 35 · ≤72 h = 25 · ≤168 h = 12 · otherwise 4.
- **Importance:** share ≥0.15 = 35 · ≥0.08 = 28 · ≥0.04 = 20 · ≥0.015 = 12 · >0 = 6 · 0 or ungraded = 2. If the share is `None`: 6 when `points_possible` > 0, else 2. Add +5 when the title matches `\b(exam|midterm|final|project)\b` (case-insensitive), capped at 35.
- **Effort:** `slack = hours_left − 1.5 × effort_hours`. ≤0 = 15 · ≤24 = 10 · ≤72 = 5 · otherwise 0.
- **Effort hours:** the first match wins:
  - `\b(exam|midterm|final)\b` → 8
  - `\b(essay|project|paper)\b` → 6
  - `\blab\b` → 3
  - type `QUIZ`, `DISCUSSION`, `PEER_REVIEW` or `PAGE`, or `\breading\b` → 1
  - otherwise 2
- **Grade share:**
  - 0.0 when `omit_from_final_grade` or `points_possible == 0`
  - `None` when `points_possible is None`
  - weighted course with a group whose `total_points > 0`: `group_weight / 100 × points / group.total_points`
  - unweighted course with `course.total_points > 0`: `points / course.total_points`
  - otherwise `None`.
- **Tiers:**
  - URGENT when `not is_done` and (`0 < hours_left <= 24` or overdue and accepting)
  - otherwise HIGH when `total >= 55`, or (`hours_left <= 72` and share ≥ 0.08), or (`hours_left <= 168` and share ≥ 0.10), or `slack < 24`
  - otherwise MEDIUM when `total >= 30`
  - otherwise LOW.

- [ ] **Step 1: Write the failing tests**

```python
def test_urgent_quiz_example() -> None:  # the PRD's own explanation example
    item = make_item(type=ItemType.QUIZ, due_in=timedelta(hours=5, minutes=20))  # 10 points
    course = Course(id=1, code="C", name="C", total_points=10 / 0.12)  # 10 pts = 12% share
    s = score(item, NOW, course, None)
    assert (s.urgency, s.importance, s.effort, s.tier) == (45, 28, 10, Tier.URGENT)
    assert s.total == 83 and s.grade_share == pytest.approx(0.12)

@pytest.mark.parametrize(("hours", "u"), [(24, 45), (24.01, 35), (48, 35), (72, 25), (168, 12), (169, 4)])
def test_urgency_edges(hours: float, u: int) -> None: ...

@pytest.mark.parametrize(("share", "i"), [(0.15, 35), (0.08, 28), (0.04, 20), (0.015, 12), (0.001, 6), (0.0, 2)])
def test_importance_edges(share: float, i: int) -> None: ...

def test_keyword_bonus_caps_at_35() -> None: ...           # share 0.20 + "Final project" -> 35
def test_slack_nonpositive_gives_15() -> None: ...           # essay (6 h) due in 8 h -> slack -1 -> 15
def test_high_by_weight_within_72h() -> None: ...           # due 60 h, share 0.09 -> HIGH
def test_high_by_weight_within_week() -> None: ...          # due 6 d, share 0.11 -> HIGH
def test_medium_example() -> None: ...                        # due 6 d, share 0.05, homework -> 12+20+0=32 MEDIUM
def test_low_example() -> None: ...                           # due 10 d, points 0 -> 4+2+0=6 LOW
def test_weighted_share() -> None: ...                        # weight 40, 10 pts of 100 -> 0.04
def test_zero_totals_give_none() -> None: ...                 # Review Focus 2: course total 0, group total 0, weight 0 -> None, no exception
def test_omitted_from_final_grade_is_zero_share() -> None: ...
```

  The implementer fills in the `...` bodies with exactly the values in the comments.

- [ ] **Step 2: Run them.** `uv run pytest tests/unit/test_priority.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `priority.py`.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(domain): transparent 100-point priority score and tiers"`

---

### Task 6: Time utilities

**Files:**
- Create: `src/canvas_tracker/planning/__init__.py`, `src/canvas_tracker/planning/timeutil.py`, `tests/unit/test_timeutil.py`

**Interfaces:**
- Produces:
  - `at_local(d: date, t: time, tz: ZoneInfo) -> datetime`: returns UTC. Uses `datetime.combine(d, t, tzinfo=tz)` with `fold=0`, then `.astimezone(UTC)`, so a time that doesn't exist (in a spring-forward gap) moves forward.
  - `local_date(instant: datetime, tz: ZoneInfo) -> date`
  - `in_quiet(instant: datetime, tz: ZoneInfo, start: time | None, end: time | None) -> bool`: `False` when either is `None` or `start == end`. When `start < end`, the window is `start <= t < end`; otherwise it wraps past midnight: `t >= start or t < end`.
  - `next_quiet_window(now: datetime, tz: ZoneInfo, start: time, end: time) -> tuple[datetime, datetime]`: the first window (UTC) whose start is later than `now`.
  - `floor_minute(instant: datetime) -> datetime`

- [ ] **Step 1: Write the failing tests**, with exact instants:
  - `at_local(date(2027,3,14), time(2,30), NY) == datetime(2027,3,14,7,30,tzinfo=UTC)`: the gap moves forward to 03:30 EDT.
  - Digest instants for `time(8,0)`:

    | Zone | Date | Expected UTC |
    |---|---|---|
    | New York | 2026-11-01 | 13:00Z |
    | New York | 2026-10-31 | 12:00Z |
    | Berlin | 2026-10-25 | 07:00Z |
    | Berlin | 2026-10-24 | 06:00Z |
    | Dublin | 2026-10-25 | 08:00Z |
    | Dublin | 2026-10-24 | 07:00Z |
    | Kolkata | 2026-10-20 | 02:30Z |
    | Lord Howe | 2026-10-04 | 21:00Z on 2026-10-03 |
    | Lord Howe | 2026-10-03 | 21:30Z on 2026-10-02 |
    | Kiritimati | 2026-10-20 | 18:00Z on 2026-10-19 |

  - `in_quiet` with 00:00–08:00 in New York: 23:59 → False, 00:00 → True, 07:59 → True, 08:00 → False. With 22:00–07:00: 23:00 → True, 12:00 → False. `None` → False.
  - `next_quiet_window(Tue 2026-10-20 16:00Z, NY, 00:00, 08:00) == (2026-10-21 04:00Z, 2026-10-21 12:00Z)`.

- [ ] **Step 2: Run them.** `uv run pytest tests/unit/test_timeutil.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `timeutil.py`.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(planning): zone-aware time helpers with DST tests"`

---

### Task 7: Send keys and digest planning

**Files:**
- Create: `src/canvas_tracker/planning/keys.py`, `src/canvas_tracker/planning/digest.py`, `tests/unit/test_keys.py`, `tests/unit/test_plan_digest.py`

**Interfaces:**
- Consumes: `Snapshot`, `Settings`, `Send`, `SendKind`, `is_urgent`, `at_local`, `local_date`.
- Produces. Keys use the UTC minute format `%Y-%m-%dT%H:%MZ`, written below as `{ts}`:
  - `digest_key(d: date) -> str` = `f"digest:{d.isoformat()}"`
  - `reminder_key(anchor: datetime, k: int) -> str` = `f"rem:{ts(anchor)}:{k}"`
  - `new_urgent_key(item: Item) -> str` = `f"new:{item.ref}:{ts(item.due_at)}"`
  - `snooze_end_key(item: Item) -> str` = `f"snz:{item.ref}:{ts(item.snoozed_until)}"`
  - `overnight_key(d: date) -> str` = `f"overnight:{d.isoformat()}"`
  - `overdue_key(item: Item) -> str` = `f"overdue:{item.ref}:{ts(item.due_at)}"`
  - `auth_alert_key(since: datetime) -> str` = `f"auth:{ts(since)}"`
  - `plan_digest(now: datetime, snap: Snapshot, settings: Settings) -> Send | None`: returns `Send(digest_key(d), SendKind.DIGEST, item_refs=<refs of urgent items, sorted>)` when `at_local(d, digest_time) <= now < at_local(d, digest_grace_until)` and the key hasn't been sent, where `d = local_date(now, zone)`. Otherwise `None`.

- [ ] **Step 1: Write the failing tests.**
  - `test_keys.py` pins the exact strings, e.g. `reminder_key(datetime(2026,10,20,3,59,tzinfo=UTC), 0) == "rem:2026-10-20T03:59Z:0"`.
  - `test_plan_digest.py` covers:
    - New York 2026-10-20: nothing at 11:59:59Z; a digest at 12:00Z with key `digest:2026-10-20`.
    - Still due at 15:59Z, `None` at 16:00Z (the grace window ends at 12:00 local).
    - `None` when the key is already sent.
    - `item_refs` lists only urgent items.
    - On 2026-11-01, the first due instant is 13:00Z.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement both modules.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(planning): deterministic send keys and digest timing"`

---

### Task 8: Reminder cycle and alerts

**Files:**
- Create: `src/canvas_tracker/planning/reminders.py`, `tests/unit/test_plan_reminders.py`

**Interfaces:**
- Consumes: Tasks 4, 6 and 7.
- Produces:
  - `plan_cycle(now: datetime, snap: Snapshot, settings: Settings) -> Plan`
  - `plan_alerts(now: datetime, snap: Snapshot, settings: Settings) -> tuple[Send, ...]`

**`plan_cycle` algorithm** (§7.5). The cycle steps don't fully pin this down, so it's written out:

```text
urgent = [i for i in snap.items if is_urgent(i, now, settings)]
if snap.cycle is None:
    if not urgent: return Plan()
    anchor = floor_minute(now); opened = anchor
else:
    if not urgent: return Plan(close_cycle=True)
    anchor = snap.cycle.anchor; opened = None
k = (now - anchor) // settings.reminder_interval
slot = anchor + k * settings.reminder_interval
digest_at = at_local(local_date(slot, zone), settings.digest_time, zone)
skip = (now - slot > SLOT_GRACE or in_quiet(slot, ...) or in_quiet(now, ...)
        or abs(slot - digest_at) <= DIGEST_FOLD or reminder_key(anchor, k) in snap.sent_keys)
active = sorted((i for i in urgent if is_active(i, now, settings, snap.pause_until)), key=due_at)
sends = () if skip or not active else (Send(reminder_key(anchor, k), REMINDER, refs(active)),)
return Plan(sends=sends, open_cycle_at=opened)
```

**`plan_alerts` rules.** All of them return nothing while paused (`pause_until > now`) and nothing while `in_quiet(now)`, except the overnight warning, which is sent outside quiet hours by design.
- **NEW_URGENT** for each active item. With `next_slot = anchor + (k+1)·interval` (or `now + interval` when no cycle is open yet), send when `due_at <= next_slot` and (`last_reminded_at[ref]` is missing or earlier than `due_at − reminder_interval`) and `new_urgent_key` hasn't been sent.
- **SNOOZE_END** for each urgent item with `snoozed_until` set: send when `now − SNOOZE_END_GRACE < snoozed_until <= now`, `last_reminded_at[ref]` is missing or earlier than `snoozed_until`, and the key hasn't been sent.
- **OVERNIGHT:** take `(qs, qe) = next_quiet_window(now, ...)`. Send when `qs − OVERNIGHT_LEAD <= now < qs` and some not-done, not-gone, remindable item has `qs <= due_at < qe`. The key is `overnight_key(local_date(qs − OVERNIGHT_LEAD))` and the refs are those items.
- **OVERDUE** for each remindable item that is not done, not gone and not `stop_reminders`: send when `due_at <= now < due_at + OVERDUE_NOTICE_GRACE` and the key hasn't been sent.

- [ ] **Step 1: Write the failing tests.** Each builds a snapshot at a specific instant (New York, quiet 00:00–08:00, digest 08:00):
  - **Cycle open:** no cycle, one item due in 24 h → `open_cycle_at == floor_minute(now)` and one REMINDER with key `rem:<now>:0`.
  - **Slot timing:** an anchor 2 h earlier → slot `k=1`. An anchor 1 h earlier and slot 0 already sent → no send.
  - **Catch-up:** anchor 10 h 20 m earlier (`k=5`, 20 min late) → sends. 10 h 40 m earlier (40 min late) → no send, and slots 0–4 are never produced.
  - **Quiet:** a slot at 03:59 local → no send.
  - **Digest fold:** a slot at 07:59 local, then one at 08:10 local → neither sends.
  - **Close:** a cycle with no urgent items → `close_cycle=True`, no sends.
  - **Done or snoozed** items are excluded from the slot refs.
  - **NEW_URGENT:**
    - an item due in 1 h, a cycle whose next slot is 1.5 h away, never reminded → alert;
    - the same item already reminded 30 min ago → no alert;
    - an item due in 3 h → no alert (it joins the next slot).
  - **SNOOZE_END:** `snoozed_until = now − 1min`, not reminded since → alert; `snoozed_until = now − 31min` → none.
  - **OVERNIGHT:** at 23:30 local, an item due 03:00 local tomorrow → one warning with key `overnight:2026-10-20`. At 23:29 → none. An item due 23:59 tonight is not included.
  - **OVERDUE:** due 1 min ago → notice; due 2 h ago → none; inside quiet hours → none; `stop_reminders` → none.
  - **Pause:** `pause_until = now + 1h` → no REMINDER, NEW_URGENT, SNOOZE_END or OVERDUE (the cycle still opens and closes).

- [ ] **Step 2: Run them.** `uv run pytest tests/unit/test_plan_reminders.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `reminders.py`.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(planning): consolidated 2-hour reminder cycle and alerts"`

---

### Task 9: `plan()` composition, simulation helper, worked example and property tests

**Files:**
- Create: `src/canvas_tracker/planning/plan.py`, `tests/planning_sim.py`, `tests/unit/test_plan.py`, `tests/property/test_plan_properties.py`

**Interfaces:**
- Consumes: Tasks 7 and 8, and `auth_alert_key`.
- Produces:
  - `plan(now: datetime, snap: Snapshot, settings: Settings) -> Plan`. Send order: DIGEST, REMINDER, NEW_URGENT, SNOOZE_END, OVERNIGHT, OVERDUE, AUTH_ALERT.
    - An `AUTH_ALERT` is sent when `auth_failed_since` is set, the time isn't quiet, and its key hasn't been sent.
    - A NEW_URGENT or SNOOZE_END alert for an item already in this plan's REMINDER or DIGEST refs is dropped.
  - Test helper `simulate(items_by_time: Callable[[datetime], tuple[Item, ...]], settings: Settings, start: datetime, end: datetime, step: timedelta = timedelta(seconds=60), crash_on: frozenset[str] = frozenset()) -> list[tuple[datetime, Send]]`:
    - Each step builds a `Snapshot` from the items the scenario says exist at that moment, plus the simulated sent keys, cycle and `last_reminded_at`. Then it calls `plan()` and applies the results.
    - A key in `crash_on` is "sent but not recorded" once, which models the one-duplicate crash allowance.

- [ ] **Step 1: Write the failing worked-example test** (`test_plan.py`, the PRD §7.5 example)

```python
def test_prd_worked_example_tuesday_2359() -> None:
    ny = ZoneInfo("America/New_York")
    due = datetime(2026, 10, 20, 23, 59, tzinfo=ny).astimezone(UTC)
    item = make_item(due_at=due)
    log = simulate(lambda _t: (item,), make_settings(),
                   start=datetime(2026, 10, 19, 20, 0, tzinfo=ny).astimezone(UTC),
                   end=datetime(2026, 10, 21, 1, 0, tzinfo=ny).astimezone(UTC))
    got = [(t.astimezone(ny).strftime("%a %H:%M"), s.kind) for t, s in log]
    assert got == [("Mon 23:59", SendKind.REMINDER), ("Tue 08:00", SendKind.DIGEST),
                   *[(f"Tue {h}:59", SendKind.REMINDER) for h in ("09", "11", "13", "15", "17", "19", "21")],
                   ("Tue 23:59", SendKind.OVERDUE)]
```

- [ ] **Step 2: Add the failing tests:**
  - **DST fall-back:** an item due Sun 2026-11-01 23:59 New York. Expected local send times: the 08:00 digest, then reminders at 09:59, 11:59, 13:59, 15:59, 17:59, 19:59 and 21:59, then the overdue notice at 23:59. Exactly one digest on that date.
  - **Submission mid-cycle:** the item becomes `submitted=True` at Tue 14:30 → no sends after 13:59, and the cycle closes.
  - **Extension:** `due_at` moves 2 days later at Tue 12:30 → no overdue notice on Tue, and reminders resume when the new deadline is within 24 h.
  - **Last-minute posting during an open cycle:** item A is due Wed 2026-10-21 12:00 local, so its cycle is anchored Tue 12:00 and has slots at 14:00 … 22:00, then 00:00 (quiet). Item D first appears Tue 22:50, due 23:30, so the next slot (00:00) is after D's deadline → a NEW_URGENT alert for D at 22:50. Then remove A from the scenario and check that D alone, appearing at 22:50, opens a new cycle with a REMINDER at 22:50 instead.
  - **Crash allowance:** `crash_on={"rem:...:5"}` produces exactly one duplicate of that key and no other.
  - **Auth alert:** sent once; not during quiet hours.

- [ ] **Step 3: Write the property tests** (`tests/property/test_plan_properties.py`).
  - Hypothesis profiles: `ci` (`max_examples=200`) and `dev` (50).
  - Generators:
    - a zone from `["America/New_York", "Europe/Berlin", "Europe/Dublin", "Asia/Kolkata", "Australia/Lord_Howe", "Pacific/Kiritimati"]`
    - quiet hours: `None`, or a pair of whole-hour times
    - 0–6 items with due offsets in `[-2d, +5d]`
    - optional submission time per item
    - a start inside 2026-10-24…2026-11-02 (it crosses both fall-back changes)
    - a 3-day horizon at 10-minute steps (to keep runtime down)
  - Properties:
    1. No key is sent twice (with `crash_on` empty).
    2. No REMINDER, NEW_URGENT or SNOOZE_END ref is done, snoozed or past its deadline at its send time (with `overdue_reminders=False`).
    3. No REMINDER, NEW_URGENT, SNOOZE_END, OVERDUE or AUTH_ALERT is sent inside quiet hours.
    4. Liveness: if an item stays active and outside quiet hours for a continuous span of `interval + DIGEST_FOLD + step`, at least one send of a kind in `REMINDER_KINDS` includes it within that span.
    5. `plan()` is deterministic, and replaying the same instant after applying its results produces no sends.
  - Also: `Europe/Dublin` gets its own example tests in `test_plan.py` (digest on 2026-10-24 and 2026-10-25), because Hypothesis's handling of negative DST is unreliable (§11.2).

- [ ] **Step 4: Run them.** `uv run pytest tests/unit/test_plan.py tests/property -v`. Expected: FAIL (no `plan` yet).

- [ ] **Step 5: Implement `plan()`** in `plan.py` and the helper in `tests/planning_sim.py`.

- [ ] **Step 6: Run the tests.** `uv run pytest tests/unit tests/property -v`. Expected: PASS. Coverage of `planning/` is ≥95% (`uv run pytest --cov=canvas_tracker.planning --cov-branch`).

- [ ] **Step 7: Commit.** `git commit -m "feat(planning): compose plan(), worked-example, DST and property tests"`

---

### Task 10: Render building blocks

**Files:**
- Create: `src/canvas_tracker/render/__init__.py`, `src/canvas_tracker/render/message.py`, `src/canvas_tracker/render/copy.py`, `src/canvas_tracker/render/format.py`, `tests/unit/test_format.py`

**Interfaces:**
- Produces:
  - `Button(label: str, callback_data: str | None = None, url: str | None = None)`: frozen. Exactly one of the two is set, and `callback_data` is at most 64 bytes in UTF-8; otherwise `__post_init__` raises.
  - `RenderedMessage(text: str, keyboard: tuple[tuple[Button, ...], ...] = ())`
  - `escape(text: str) -> str`: `html.escape(text, quote=True)`.
  - `safe_link(url: str | None, canvas_host: str) -> str | None`: returns the URL only if its scheme is `https` and its hostname equals `canvas_host`.
  - `format_due(due: datetime, now: datetime, tz: ZoneInfo) -> str`:
    - `"today 11:59 PM"` when on the same local date
    - `"tomorrow 2:00 PM"`
    - `"Thu 11:59 PM"` within 6 days
    - otherwise `"Oct 30 11:59 PM"`.
  - `format_left(delta: timedelta) -> str`: `"9 h 58 m"`, `"58 m"` under an hour, `"2 d 3 h"` at 48 h or more.
  - `split_blocks(blocks: Sequence[str], limit: int = 4096) -> list[str]`: joins blocks with `"\n"` and never splits inside a block. A single block longer than the limit is cut at the last whitespace before the limit, after any tags in it are closed. *(Blocks are built so they contain only balanced `<b>` and `<a>` tags.)*
  - `copy.py`: every user-facing template string (headers, tier labels, button labels `"✅ Done"`, `"💤 2h"`, `"🔗 Open"`, `"🔕 Stop"`, `"↩️ Undo"`, the stale banner, the nothing-due line, and command replies).

- [ ] **Step 1: Write the failing tests:**
  - `escape("<b>&\"x\"</b>") == "&lt;b&gt;&amp;&quot;x&quot;&lt;/b&gt;"`
  - `safe_link` rejects `http://` and `https://evil.example/x`, and accepts `https://canvas.example.edu/courses/1`.
  - `format_due` for the four cases, evaluated at `NOW` in New York.
  - `format_left` for `9h58m`, `58m`, `51h`.
  - `split_blocks` with 50 blocks of 100 characters: every part ≤4096, no block split, and the order is preserved.
  - Callback data of 65 bytes raises.
  - **Review Focus 4:** with `monkeypatch.setenv("TZ", "Asia/Tokyo"); time.tzset()`, `format_due` returns the same string as under `TZ=UTC`.

- [ ] **Step 2: Run them.** `uv run pytest tests/unit/test_format.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement the modules.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(render): message types, copy, escaping, links, time text, splitting"`

---

### Task 11: Render the digest, reminders and alerts

**Files:**
- Create: `src/canvas_tracker/render/digest.py`, `src/canvas_tracker/render/alerts.py`, `tests/unit/test_render_digest.py`, `tests/unit/test_render_alerts.py`

**Interfaces:**
- Consumes: Tasks 5 and 10, `Snapshot`, `Send`, `Settings`.
- Produces:
  - `render_digest(snap: Snapshot, now: datetime, settings: Settings) -> list[RenderedMessage]`
  - `render_send(send: Send, snap: Snapshot, now: datetime, settings: Settings) -> list[RenderedMessage]`: dispatches on `send.kind`; DIGEST delegates to `render_digest`.
  - `explain(item: Item, s: Score, now: datetime, settings: Settings) -> str`: e.g. `due today 11:59 PM (in 15 h) · ≈6% of grade · est. 2 h`.
    - It drops "≈x% of grade" when the share is `None` and shows `weight unknown` instead, but only for graded types.
    - It appends `· quiz` / `· peer review` for those types.
    - HIGH items get `· start by <local due − 1.5×effort, floored to the hour>`.

**Digest layout** (§7.4), in this order:
1. Header: `☀️ Good morning! Tue, Oct 20`.
2. Counts line: `3 urgent · 1 high · 4 later this week (synced 7:58 AM)`.
3. Stale banner, if `last_successful_sync_at` is `None` or older than `STALE_AFTER`. It replaces the "Nothing due" line.
4. URGENT and HIGH items, numbered.
5. MEDIUM and LOW collapsed: a count, the next three due, then `→ /week`.
6. OVERDUE (`is_overdue_accepting`).
7. Events today.
8. `✅ Done yesterday: N`, counting items whose `done_seen_at` or `bot_done_at` falls on the previous local date.

The look-ahead is `digest_lookahead`. The keyboard has rows of 4 `✅ n` buttons for the URGENT and HIGH items, with `callback_data=f"d:{db_id}"`. Titles become `<a href=…>` only through `safe_link`.

**Reminder message** (§7.5):
- Course label everywhere: `snap.courses[item.course_id].code` when known, else `item.course_name`.
- Header: `⏰ Due within 24 hours: N not submitted`.
- Items, nearest deadline first, each as `{course} · {title}` / `due {format_due} · {format_left} left`, with ` ⚠️` when under 2 h.
- The header rotates among three templates in `copy.py`, chosen by `k % 3` from the key's slot number.
- Each item gets the row `[✅ Done n] [💤 2h n] [🔗 n]`, using `d:`, `s:` and a URL button. The URL button is omitted when there's no safe link.
- At most 30 items per message; extra items continue in the next message.

**Other kinds:**
- NEW_URGENT and SNOOZE_END: a single-item version of the reminder.
- OVERNIGHT: `🌙 Due while you sleep:` followed by the items.
- OVERDUE: `❗ {title} is now overdue (was due {time}).` A second line says `Canvas still accepts it until {lock_at}.` when `lock_at` is in the future. Buttons: `[✅ Done] [🔕 Stop] [🔗 Open]`.
- AUTH_ALERT: renewal steps text from `copy.py`, with no Canvas data.

- [ ] **Step 1: Write the failing tests:**
  - A golden-text test of the digest for a fixed snapshot that reproduces the PRD §7.4 example items. Assert the exact lines; the PRD example is the reference.
  - The stale banner is shown and "Nothing due" is suppressed when the last sync is 31 minutes old.
  - "Nothing due in the next 14 days 🎉 (synced 7:58 AM)" appears when the list is empty and the data is fresh.
  - **Adversarial titles:** `"<b>"`, `"&amp;"`, `"*_[]()~"`, emoji, an RTL string, 5,000 characters, embedded newlines. The output contains no raw `<b>` from Canvas text, every part is ≤4096, and parsing it with `html.parser` finds balanced tags.
  - Links to a non-Canvas host are not linked.
  - **Review Focus 3:** 40 urgent items → 2 reminder messages, each ≤4096 characters, with keyboards of ≤90 buttons.
  - The overdue notice includes the `lock_at` sentence only when `lock_at > now`.
  - Every `callback_data` matches `^[dsux]:\d+$`.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement both modules.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(render): digest, reminder and alert messages with buttons"`

---

### Task 12: SQLite connection, migrations, state and send claims

**Files:**
- Create: `src/canvas_tracker/store/__init__.py`, `src/canvas_tracker/store/db.py`, `src/canvas_tracker/store/migrations/0001_init.sql`, `src/canvas_tracker/store/repo.py` (state and notification parts), `tests/unit/test_store_db.py`

**Interfaces:**
- Produces:
  - `connect(path: Path | str) -> sqlite3.Connection`: sets `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, row factory `sqlite3.Row`, and `isolation_level=None` (transactions are explicit).
  - `migrate(conn) -> int`: applies the `NNNN_*.sql` files from package resources whose number is above `PRAGMA user_version`, each inside its own transaction, and returns the new version.
  - `class Store` with `__init__(self, conn: sqlite3.Connection)` and:
    - `get_state(key: str) -> str | None`, `set_state(key: str, value: str | None) -> None`
    - `get_time(key: str) -> datetime | None`, `set_time(key: str, value: datetime | None) -> None` (stored as ISO 8601 UTC)
    - `claim(key: str, kind: SendKind, item_refs: Sequence[str], now: datetime) -> bool`
    - `mark_sent(key: str, now: datetime, message_id: int | None) -> None`
    - `mark_failed(key: str, error: str) -> None`
  - State key constants: `OWNER_ID`, `PAUSE_UNTIL`, `LAST_SUCCESSFUL_SYNC_AT`, `LAST_SYNC_ATTEMPT_AT`, `LAST_SYNC_ERROR`, `PLANNER_ETAG`, `AUTH_FAILED_SINCE`, `LAST_TICK_AT`, `LAST_ENRICHMENT_AT`, `LAST_PURGE_AT`.
  - Schema `0001_init.sql`, following §9.4:
    - `items`: one column per `Item` field (Task 3), with `db_id` as `id INTEGER PRIMARY KEY`, plus `enriched INTEGER NOT NULL DEFAULT 0`, with `UNIQUE(plannable_type, plannable_id)`.
    - `courses`, `assignment_groups`.
    - `cycles(anchor_utc TEXT NOT NULL, closed_at_utc TEXT)`.
    - `notifications(key TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','sent','failed')), item_refs TEXT NOT NULL DEFAULT '[]', claimed_at TEXT NOT NULL, sent_at TEXT, message_id INTEGER, error TEXT)`.
    - `state(key TEXT PRIMARY KEY, value TEXT)`.

**Claim semantics** (§9.3):
- **Insert** a `pending` row if the key is absent → `True`.
- **Re-claim** (set `pending` with the new `claimed_at`) when the status is `pending` or `failed` and `claimed_at < now − 2 min` → `True`.
- Otherwise → `False`. A `sent` row never re-claims.
- All of it runs as a single `INSERT … ON CONFLICT(key) DO UPDATE … WHERE …` statement; the return value comes from `changes()`.

- [ ] **Step 1: Write the failing tests:**
  - `migrate` on a fresh DB returns 1, a second call returns 1 and changes nothing, and `PRAGMA journal_mode` is `wal`.
  - The claim sequence:
    - `claim(k, now)` → True
    - `claim(k, now+1min)` → False
    - `claim(k, now+3min)` → True (a stale pending claim)
    - `mark_sent` → `claim(k, now+1h)` → False
    - `mark_failed` on a fresh key, then claim at +3 min → True.
  - `set_time` then `get_time` round-trips an aware UTC value; `set_time(key, None)` deletes it.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(store): sqlite WAL, migrations, state and idempotent send claims"`

---

### Task 13: Store items, courses, cycles, snapshot, user actions and purge

**Files:**
- Modify: `src/canvas_tracker/store/repo.py`
- Create: `tests/unit/test_store_items.py`

**Interfaces:**
- Consumes: Task 12, `Item`, `Enrichment`, `is_done`.
- Produces these `Store` methods:
  - `upsert_items(items: Sequence[Item], now: datetime) -> None`. It updates **only Canvas-owned columns**.
    - On a `due_at` change, it clears `bot_done_at`, `bot_done_due_at`, `snoozed_until` and `stop_reminders`.
    - It sets `done_seen_at = now` when the item goes from not done to done (judged by `is_done` on the merged row), and clears it when the item goes back to not done.
    - It clears `gone_at`.
  - `mark_gone(window: tuple[datetime, datetime], seen_refs: set[str], now: datetime) -> None`
  - `apply_enrichment(e: Enrichment) -> None`: replaces courses and groups, writes `AssignmentDetail` fields onto items with a matching `assignment_id`, and sets `enriched=1` on them.
  - `needs_enrichment() -> bool`: true when any item has an `assignment_id` and `enriched=0`.
  - `get_item(db_id: int) -> Item | None`
  - `set_bot_done(db_id: int, now: datetime) -> None`
  - `clear_user_flags(db_id: int) -> None`: clears the bot done fields and `stop_reminders`.
  - `snooze(db_id: int, until: datetime) -> None`, `set_stop(db_id: int) -> None`
  - `open_cycle(anchor: datetime) -> None`, `close_cycle(now: datetime) -> None`
  - `snapshot(hidden_courses: frozenset[str] = frozenset()) -> Snapshot`:
    - leaves out items whose course id (as a string) or course code is in `hidden_courses`
    - `sent_keys` holds every `sent` key
    - `last_reminded_at` is the latest `sent_at` for each ref, over `sent` rows whose kind is in `REMINDER_KINDS`
    - `cycle` is the open one, if any
    - `pause_until`, `last_successful_sync_at` and `auth_failed_since` come from state.
  - `purge(now: datetime, item_retention: timedelta, notification_retention: timedelta = timedelta(days=60)) -> None`

- [ ] **Step 1: Write the failing tests:**
  - **Upsert keeps bot fields:** set bot done, then re-upsert with the same `due_at` → still done.
  - **Extension:** an upsert with a new `due_at` clears the bot, snooze and stop fields.
  - `done_seen_at` is set when `submitted` flips to true and cleared when `redo_request` appears.
  - Upserting the same planner item twice in one batch (duplicate across pages) leaves one row.
  - **`mark_gone`:** an in-window item not seen gets `gone_at`; an out-of-window item is untouched; seeing it again clears `gone_at`.
  - **Enrichment:** applying it sets points and `lock_at`; `needs_enrichment` flips from true to false.
  - **Snapshot:** a hidden course code excludes its items; `last_reminded_at` takes the latest of two reminders and ignores OVERDUE.
  - **Purge:** removes an item due 31 days ago and a notification from 61 days ago, and keeps newer ones.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(store): item upsert rules, enrichment, cycles, snapshot, purge"`

---

### Task 14: Configuration and secrets

**Files:**
- Create: `src/canvas_tracker/config.py`, `tests/unit/test_config.py`, `.env.example`

**Interfaces:**
- Consumes: `Settings`.
- Produces:
  - `validate_base_url(url: str) -> str`. Rules:
    - the scheme must be `https`
    - no userinfo, query or fragment
    - the path must be empty or `/`
    - the host must not be an IP literal (`ipaddress.ip_address` succeeds → reject)
    - returns `https://<host>[:port]`, lowercased.
  - `class AppConfig(BaseSettings)` with fields: `data_mode: Literal["api"] = "api"` (`ical` is rejected with the message `"DATA_MODE=ical arrives in v1.0 (M2)"`), `canvas_base_url: str`, `canvas_token: SecretStr`, `telegram_bot_token: SecretStr`, `telegram_owner_id: int | None = None`, `timezone: str`, `digest_time: time`, `digest_grace_until: time`, `digest_lookahead_days: int = 14`, `reminder_window_hours: int = 24`, `reminder_interval_minutes: int = Field(120, ge=30)`, `quiet_hours: str = "00:00-08:00"`, `overdue_reminders: bool = False`, `overdue_reminder_max_hours: int = 48`, `hide_courses: str = ""`, `db_path: Path = Path("/data/bot.db")`, `item_retention_days: int = 30`, `log_level: str = "INFO"`.
  - `load_config(env: Mapping[str, str] | None = None) -> AppConfig`. For each secret `X`, it accepts `X` or `X_FILE` (read, then whitespace-stripped). Errors:
    - both set → `ValueError("set CANVAS_TOKEN or CANVAS_TOKEN_FILE, not both")`
    - neither set → a missing-field error naming both
    - an empty file → `ValueError("CANVAS_TOKEN_FILE is empty")`.
  - `token_provider(cfg: AppConfig, env: Mapping[str, str] | None = None) -> Callable[[], str]`: when `CANVAS_TOKEN_FILE` is used, it re-reads the file on every call, which allows renewal without a restart (§7.1).
  - `to_settings(cfg: AppConfig) -> Settings`: parses `QUIET_HOURS` (`"HH:MM-HH:MM"` or `"off"`), converts minutes and hours, and sets `canvas_host` from the validated URL.
  - `hidden_courses(cfg) -> frozenset[str]`
  - `.env.example`: every variable with its default, and secrets shown only as `*_FILE=/run/secrets/...`.

- [ ] **Step 1: Write the failing tests:**
  - `validate_base_url` accepts `https://Canvas.School.edu/` → `https://canvas.school.edu`, and rejects `http://x`, `https://u:p@x`, `https://1.2.3.4`, `https://[::1]`, `https://x/path` and `https://x?q=1`.
  - **Review Focus 5:** a token file containing `"  abc123\n"` → `"abc123"`; an empty file → the exact error; both variables set → the exact error.
  - `REMINDER_INTERVAL_MINUTES=29` is rejected.
  - `QUIET_HOURS=off` gives `quiet_start is None`.
  - `TIMEZONE=Mars/Olympus` is rejected.
  - `DATA_MODE=ical` is rejected with the M2 message.
  - `repr(cfg)` doesn't contain the token value.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(config): validated settings with *_FILE secrets"`

---

### Task 15: Logging with redaction

**Files:**
- Create: `src/canvas_tracker/runtime/__init__.py`, `src/canvas_tracker/runtime/logging.py`, `tests/unit/test_logging.py`

**Interfaces:**
- Produces:
  - `class RedactingFilter(logging.Filter)`, built with `__init__(self, secrets: Iterable[str])`. It replaces exact secret values and these patterns with `[REDACTED]`, in `record.msg`, `record.args` and the formatted exception text:
    - Telegram tokens: `\b\d{6,12}:[A-Za-z0-9_-]{30,}\b`
    - Canvas tokens: `\b\d{1,6}~[A-Za-z0-9]{20,}\b`
    - `bot<token>/` URL segments.
  - `class JsonFormatter(logging.Formatter)`: one JSON object per line, with the keys `ts`, `level`, `logger`, `msg`, plus any `extra` fields.
  - `configure_logging(level: str, secrets: Iterable[str]) -> None`: installs the formatter and filter on the root handler (stdout), and sets the `httpx` and `httpcore` loggers to WARNING.

- [ ] **Step 1: Write the failing tests:**
  - Log `"GET https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789ab/getUpdates"` → the output contains `[REDACTED]` and not the token.
  - An exact secret inside `args` is redacted.
  - An exception message carrying a Canvas token is redacted in the traceback text.
  - Output lines parse as JSON.
  - After `configure_logging("DEBUG", ...)`, the effective level of `logging.getLogger("httpx")` is WARNING.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(runtime): JSON logs with secret redaction"`

---

### Task 16: Canvas HTTP client (GET only)

**Files:**
- Create: `src/canvas_tracker/sources/__init__.py`, `src/canvas_tracker/sources/canvas_client.py`, `tests/unit/test_canvas_client.py`

**Interfaces:**
- Consumes: `__version__`.
- Produces:
  - `USER_AGENT = f"CanvasAssignmentTrackingBot/{__version__} (+https://github.com/rmaytr/CanvasAssignmentTrackingBot)"`
  - Exceptions: `CanvasError`, and its subclasses `CanvasAuthError`, `CanvasUnavailable`, `CanvasProtocolError`.
  - `EtagResult(not_modified: bool, data: list[Any], etag: str | None)`
  - `class CanvasClient`, built with `__init__(self, base_url: str, token: Callable[[], str], *, transport: httpx.AsyncBaseTransport | None = None, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, rand: Callable[[], float] = random.random, max_retries: int = 4)`:
    - `async get_json(path: str, params: Mapping[str, str | Sequence[str]] | None = None) -> Any`
    - `async get_all(path, params=None) -> list[Any]`: follows `Link rel="next"` URLs.
    - `async get_all_if_changed(path, params, etag: str | None) -> EtagResult`: sends `If-None-Match` on the first page only; a 304 → `not_modified=True`.
    - `async aclose() -> None`

**Rules:**
- **Allowed paths:** must start with `/api/v1/`, otherwise `ValueError`.
- **Headers on every request:** `Authorization: Bearer {token()}`, `User-Agent`, `Accept: application/json`.
- **Client options:** `follow_redirects=False`, `httpx.Timeout(20.0)`. One `asyncio.Lock` wraps every request, so only one is in flight.
- **Responses:**
  - **2xx:** parsed as JSON.
  - **304:** handled as above.
  - **3xx (other):** `CanvasProtocolError("redirect refused")`.
  - **401:** `CanvasAuthError` (no retry).
  - **Throttling and server errors**, retried up to `max_retries` times with `await sleep(rand() * min(60, 2 * 2**attempt))`, then `CanvasUnavailable`:
    - 429
    - 403 whose body contains `Rate Limit Exceeded`
    - 5xx
    - `httpx.TimeoutException` and `httpx.TransportError`.
  - **Other 4xx:** `CanvasProtocolError`.
- **Pagination:** a next URL whose scheme or host differs from the base → `CanvasProtocolError("cross-host pagination refused")`.

- [ ] **Step 1: Write the failing tests** (respx with a mocked transport; `sleep` is an `AsyncMock`; `rand=lambda: 0.5`):
  - Three pages via `Link` headers are concatenated in order.
  - A `Link` to `https://evil.example` raises.
  - A 302 raises.
  - A 304 with an ETag → `not_modified`.
  - A 429, then a 429, then a 200 → success, with sleeps of `[1.0, 2.0]`.
  - A 403 with "Rate Limit Exceeded" retries; a 403 without it raises `CanvasProtocolError`.
  - Five 503s → `CanvasUnavailable`.
  - A 401 → `CanvasAuthError` after exactly one request.
  - Every request carries the exact User-Agent and a Bearer token from the provider; the provider is called on every request.
  - A `/login` path raises `ValueError`.
  - **Read-only guard:** `{n for n in dir(CanvasClient) if not n.startswith("_")} == {"get_json", "get_all", "get_all_if_changed", "aclose"}`.
  - Two concurrent `get_json` calls never overlap (a respx side effect checks an in-flight counter of at most 1).

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(sources): read-only, host-pinned Canvas client with jittered retries"`

---

### Task 17: Planner mapping and enrichment

**Files:**
- Create: `src/canvas_tracker/sources/planner.py`, `src/canvas_tracker/sources/enrichment.py`, `tests/fixtures/canvas/planner_items.handmade.json`, `tests/fixtures/canvas/assignment_groups.handmade.json`, `tests/unit/test_planner.py`, `tests/unit/test_enrichment.py`

**Interfaces:**
- Consumes: Task 16, `Item`, `ItemType`, `Course`, `AssignmentGroup`, `AssignmentDetail`, `Enrichment`.
- Produces:
  - `PLANNER_PATH = "/api/v1/planner/items"`
  - `planner_window(now: datetime) -> tuple[datetime, datetime]` = `(now − 28 d, now + 21 d)`
  - `planner_params(now: datetime) -> dict[str, str]`: `start_date` and `end_date` as ISO `Z` strings, `per_page="100"`, and no `filter`.
  - `map_planner_item(raw: Mapping[str, Any], base_url: str) -> Item | None`
  - `PlannerFetch(items: tuple[Item, ...] | None, etag: str | None, window: tuple[datetime, datetime])`: `items` is `None` when the response was a 304.
  - `async fetch_planner(client: CanvasClient, now: datetime, etag: str | None, base_url: str) -> PlannerFetch`
  - `map_course(raw) -> Course`, using `id`, `course_code`, `name` and `apply_assignment_group_weights`.
  - `map_assignment_groups(course_id: int, raw_groups: list[Mapping]) -> tuple[list[AssignmentGroup], dict[int, AssignmentDetail], float]`. The last value is the course's total points, summed over assignments that have `points_possible > 0`, are not `omit_from_final_grade`, and are `published` when that field is present. Each group's `total_points` uses the same rule.
  - `async fetch_enrichment(client: CanvasClient) -> Enrichment`:
    - `GET /api/v1/courses` with `enrollment_state=active&per_page=100`
    - then, for each course, `GET /api/v1/courses/{id}/assignment_groups` with `include[]=assignments&per_page=100`.

**Mapping rules:**
- `type` comes from `plannable_type`:
  - `assignment`, `quiz`, `discussion_topic`, `sub_assignment`, `wiki_page`, `planner_note` and `calendar_event` map to their own types.
  - `assessment_request` and `peer_review_sub_assignment` → `PEER_REVIEW`.
  - Anything else → `OTHER`.
- `due_at` = `plannable_date`, parsed with `datetime.fromisoformat` (it accepts both `Z` and `±HH:MM`) and converted to UTC. If it's missing → return `None`.
- `title` = `plannable.title` (falling back to `plannable.name`).
- `course_name` = `context_name`.
- `assignment_id` = `plannable.assignment_id`, or `plannable_id` when the type is `assignment`.
- `points_possible` = `plannable.points_possible`.
- `submissions` may be a dict or `false`. All flags default to `False`.
- `planner_override` may be `null` or a dict; `marked_complete` comes from `override.get("marked_complete")`.
- `html_url`: a relative path gets `base_url` prefixed; an absolute URL is kept as-is (rendering filters it with `safe_link`).

- [ ] **Step 1: Write the hand-made fixtures.** They are synthetic JSON shaped like the research's field list (§7.2), with no real data:
  - one assignment with a submissions dict
  - a quiz with `submissions: false`
  - a `planner_note` with no `plannable_date`
  - a peer review (`assessment_request`)
  - a `calendar_event`
  - an item with `planner_override: {"marked_complete": true}`
  - an item whose `plannable_date` uses a `-04:00` offset.

- [ ] **Step 2: Write the failing tests:**
  - **Review Focus 1:** every fixture item maps without raising; the dateless note → `None`; the quiz's flags are all False.
  - The peer review → `PEER_REVIEW`.
  - The offset date becomes UTC.
  - Relative `html_url` → absolute.
  - `marked_complete` is True when the override says so.
  - `planner_params` at `NOW` → `start_date="2026-09-22T16:00:00Z"`, `end_date="2026-11-10T16:00:00Z"`.
  - **Enrichment** with the groups fixture: weights, totals that exclude omitted and unpublished assignments, and details keyed by assignment id. A course with every assignment at 0 points → total 0.0, and no exception.
  - `fetch_planner` returns `items=None` on a 304 (respx).

- [ ] **Step 3: Run them.** Expected: FAIL.

- [ ] **Step 4: Implement both modules.**

- [ ] **Step 5: Run the tests.** Expected: PASS.

- [ ] **Step 6: Commit.** `git commit -m "feat(sources): planner item mapping and course/group enrichment"`

---

### Task 18: Sync service

**Files:**
- Create: `src/canvas_tracker/runtime/sync.py`, `tests/unit/test_sync.py`

**Interfaces:**
- Consumes: Tasks 12, 13, 16 and 17.
- Produces:
  - `SYNC_INTERVAL_AWAKE = timedelta(minutes=10)`, `SYNC_INTERVAL_QUIET = timedelta(minutes=30)`, `ENRICH_INTERVAL = timedelta(hours=12)`
  - `class SyncOutcome(StrEnum)`: `OK`, `NOT_MODIFIED`, `AUTH_FAILED`, `UNAVAILABLE`, `PROTOCOL_ERROR`.
  - `sync_due(now: datetime, last_attempt_at: datetime | None, quiet: bool) -> bool`
  - `enrichment_due(now: datetime, last_enrichment_at: datetime | None, needs_enrichment: bool) -> bool`
  - `class SyncService`, built with `__init__(self, client: CanvasClient, store: Store, base_url: str)`:
    - `async sync(now: datetime) -> SyncOutcome`
    - `async enrich(now: datetime) -> SyncOutcome`

**Behavior:**
- `LAST_SYNC_ATTEMPT_AT` is always written.
- **On OK:** `upsert_items`, `mark_gone(window, refs)`, set `LAST_SUCCESSFUL_SYNC_AT` and `PLANNER_ETAG`, clear `AUTH_FAILED_SINCE` and `LAST_SYNC_ERROR`.
- **On NOT_MODIFIED:** set `LAST_SUCCESSFUL_SYNC_AT` only.
- **On `CanvasAuthError`:** set `AUTH_FAILED_SINCE` if it isn't already set.
- **On other errors:** set `LAST_SYNC_ERROR` to the exception class name only, never the message text.
- `enrich` writes `apply_enrichment` and `LAST_ENRICHMENT_AT`.

The Store is called **synchronously** from the event loop. This is a plan decision: every operation is sub-millisecond for one user, and keeping the sqlite connection on one thread avoids `check_same_thread` issues. It replaces PRD §9.1's `to_thread` design call.

- [ ] **Step 1: Write the failing tests** (a real in-memory Store; a respx-backed client):
  - `sync_due`: last attempt 9 min ago, awake → False; 10 min → True; quiet with 29 min → False, 30 min → True; `None` → True.
  - `enrichment_due`: 12 h → True; `needs_enrichment` → True.
  - **OK** writes items and the timestamps.
  - **A 304** writes only `LAST_SUCCESSFUL_SYNC_AT`.
  - **A 401** sets `AUTH_FAILED_SINCE`; a second 401 keeps the original timestamp; a following OK clears it.
  - **Five 503s** → UNAVAILABLE, `LAST_SYNC_ERROR == "CanvasUnavailable"`, and items unchanged.
  - **A missing item** is marked gone.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(runtime): sync service with cadence and error state"`

---

### Task 19: Notifiers (fake and Telegram)

**Files:**
- Create: `src/canvas_tracker/notify/__init__.py`, `src/canvas_tracker/notify/base.py`, `src/canvas_tracker/notify/telegram.py`, `tests/unit/test_notify.py`

**Interfaces:**
- Consumes: `RenderedMessage` and `Button`.
- Produces:
  - `class NotifyError(Exception)`, `class NotPairedError(NotifyError)`
  - `class Notifier(Protocol)`: `async def send(self, msg: RenderedMessage) -> int | None`
  - `class FakeNotifier`: `.sent: list[RenderedMessage]`, `.fail_times: int = 0` (raises `NotifyError` that many times first). It returns incrementing message IDs.
  - `to_markup(keyboard: tuple[tuple[Button, ...], ...]) -> InlineKeyboardMarkup | None`
  - `class TelegramNotifier`, built with `__init__(self, bot: telegram.Bot, chat_id: Callable[[], int | None], sleep=asyncio.sleep)`. `send()` calls `bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=to_markup(...), link_preview_options=LinkPreviewOptions(is_disabled=True))`.
    - `chat_id()` returning `None` → `NotPairedError`.
    - `telegram.error.RetryAfter` → sleep `retry_after`, then retry once.
    - Other `TelegramError` → `NotifyError(type(e).__name__)`.

- [ ] **Step 1: Write the failing tests** (`AsyncMock` for `telegram.Bot`):
  - The HTML parse mode and link-preview option are passed.
  - The markup has the right callback and URL buttons.
  - An empty keyboard → `reply_markup=None`.
  - `RetryAfter(3)`, then success → slept 3, and the message ID is returned.
  - `NetworkError` → `NotifyError("NetworkError")`.
  - No chat ID → `NotPairedError`.
  - The fake's `fail_times` behavior.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(notify): notifier protocol, fake, and Telegram HTML notifier"`

---

### Task 20: Bot owner gate, pairing, /start and /help

**Files:**
- Create: `src/canvas_tracker/bot/__init__.py`, `src/canvas_tracker/bot/deps.py`, `src/canvas_tracker/bot/pairing.py`, `src/canvas_tracker/bot/gate.py`, `tests/unit/test_pairing.py`, `tests/unit/test_gate.py`
- Modify: `src/canvas_tracker/render/copy.py` (add `PAIRED`, `SEND_CODE`, `PAIR_WRONG`, `PAIR_EXPIRED`, `PAIR_LOCKED`, `WELCOME`, `HELP`)

**Interfaces:**
- Consumes: `Store` (the `OWNER_ID` state), `Settings`, `copy.py`.
- Produces:
  - `class PairingResult(StrEnum)`: `OK`, `WRONG`, `EXPIRED`, `LOCKED`.
  - `class PairingCode`, built with `__init__(self, now: Callable[[], datetime], on_new_code: Callable[[str], None], rng: random.Random | None = None)`. It has `.code: str` (8 characters from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, generated with `secrets` unless `rng` is given), `.expires_at = now() + 15 min`, and `check(attempt: str) -> PairingResult`.
    - The comparison uses `hmac.compare_digest` on the upper-cased attempt.
    - The 5th wrong attempt → `LOCKED`, and a new code is generated and passed to `on_new_code`.
    - Expiry → `EXPIRED`, and a new code is generated and passed to `on_new_code`.
  - `BotDeps`, a dataclass: `store: Store`, `settings: Settings`, `clock: Callable[[], datetime]`, `sync: SyncService`, `pairing: PairingCode`, `env_owner_id: int | None`, `hidden_courses: frozenset[str]`.
  - `owner_id(deps: BotDeps) -> int | None`: `env_owner_id` wins; otherwise the `OWNER_ID` state.
  - `build_gate(deps: BotDeps) -> TypeHandler`, registered in group `-1`. It:
    - drops updates without a user, or from a chat that isn't private, by raising `ApplicationHandlerStop` with no reply;
    - when an owner is known, drops every update from anyone else;
    - when no owner is known, lets through only `/start <code>` messages (handled by `start` below) and drops everything else.
  - `async start(update, context)`, registered as a `CommandHandler("start")`:
    - With no owner: check the code. On OK, store `OWNER_ID` and reply `copy.PAIRED`. On WRONG, EXPIRED or LOCKED, give the matching copy reply. A missing code gets `copy.SEND_CODE`.
    - With an owner: reply with the welcome text and a summary of the settings.
  - `async help_cmd(update, context)` lists the commands from `copy.py`.

- [ ] **Step 1: Write the failing tests:**
  - **Pairing:** the code is 8 characters from the alphabet; a correct code → OK; a lowercase correct code → OK; 4 wrong then the right one → OK; 5 wrong → LOCKED with `on_new_code` called once and the old code invalid; at +15 min → EXPIRED.
  - **Gate** (PTB `Update` objects built with `Update.de_json` from dicts):
    - a stranger with an owner set → `ApplicationHandlerStop` and no `send_message`;
    - a group chat from the owner → stop;
    - the owner's private chat → passes;
    - no owner, and a stranger sends `/today` → stop;
    - no owner, and `/start ABCD2345` → passes.
  - **/start** with the correct code stores the owner ID in the Store.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(bot): owner-only gate and one-time pairing code"`

---

### Task 21: Button callbacks (Done, Snooze, Undo, Stop)

**Files:**
- Create: `src/canvas_tracker/bot/callbacks.py`, `tests/unit/test_callbacks.py`
- Modify: `src/canvas_tracker/render/copy.py` (add `DONE`, `SNOOZED`, `SNOOZE_TOO_LATE`, `UNDONE`, `UNDO_EXPIRED`, `STOPPED`, `ITEM_GONE`)

**Interfaces:**
- Consumes: `BotDeps`, Store user actions (Task 13), and the constants `SNOOZE_LENGTH`, `SNOOZE_MIN_LEFT` and `UNDO_WINDOW`.
- Produces:
  - `parse_callback(data: str) -> tuple[Literal["d", "s", "u", "x"], int] | None`
  - `snooze_until(now: datetime, due_at: datetime) -> datetime | None` = `min(now + SNOOZE_LENGTH, due_at − SNOOZE_MIN_LEFT)`, or `None` when `due_at − now <= SNOOZE_MIN_LEFT`.
  - `async on_callback(update, context)`, registered as a `CallbackQueryHandler`. Every path calls `query.answer(text)` exactly once.

**What each action does:**
- **`d`:** `set_bot_done`. Then edit **only the keyboard** (plan decision; the PRD's "show the item ticked"): that item's button row becomes one button `✔️ {n} done · ↩️ Undo` with `u:{id}`. Answer `copy.DONE`.
- **`s`:** set `snooze(id, until)` and answer `copy.SNOOZED.format(until_local)`. If `snooze_until` returns `None`, answer `copy.SNOOZE_TOO_LATE` and change nothing.
- **`u`:** if `bot_done_at` is within `UNDO_WINDOW`, or the item has `stop_reminders`, call `clear_user_flags` and answer `copy.UNDONE`. Otherwise answer `copy.UNDO_EXPIRED`.
- **`x`:** `set_stop` and answer `copy.STOPPED`.
- **Unknown or malformed data, or an item that's missing or gone:** answer `copy.ITEM_GONE`.

- [ ] **Step 1: Write the failing tests:**
  - `parse_callback("d:12") == ("d", 12)`. `"z:1"`, `"d:x"` and `"d:1:2"` → `None`.
  - `snooze_until`: due in 3 h → `now + 2 h`; due in 1 h 50 m → `due − 30 min`; due in 30 min → `None`.
  - **Done:** marks the item done and `edit_message_reply_markup` gets the undo row.
  - **Undo:** at +5 min clears the flags; at +11 min answers "expired".
  - **Stop:** sets `stop_reminders`.
  - **Stale id:** answers `ITEM_GONE`.
  - `answer` is called exactly once in every case.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(bot): Done/Snooze/Undo/Stop buttons"`

---

### Task 22: Commands /today, /week, /digest, /sync, /status, /pause

**Files:**
- Create: `src/canvas_tracker/bot/commands.py`, `src/canvas_tracker/render/views.py`, `tests/unit/test_commands.py`, `tests/unit/test_views.py`
- Modify: `src/canvas_tracker/render/copy.py` (add `PAUSE_USAGE`, `PAUSED_UNTIL`, `PAUSE_OFF`, `SYNC_OK`, `SYNC_NOT_MODIFIED`, one line per `SyncOutcome`, and the status labels)

**Interfaces:**
- Consumes: `BotDeps`, `render_digest`, `score`, `Store.snapshot`, `SyncService.sync`, `next_quiet_window` and `at_local`.
- Produces:
  - `render_today(snap, now, settings) -> list[RenderedMessage]`: items due on the current local date, plus all URGENT and overdue-accepting items, with Done buttons.
  - `render_week(snap, now, settings) -> list[RenderedMessage]`: the next 7 days grouped by tier.
  - `StatusInfo`, a dataclass: `last_successful_sync_at`, `auth_failed_since`, `next_digest_at`, `next_slot_at: datetime | None`, `pause_until`, `version: str`.
  - `render_status(info: StatusInfo, settings) -> RenderedMessage`
  - `parse_pause(arg: str, now: datetime, tz: ZoneInfo) -> datetime | None`. It accepts `30m`, `3h`, `90m`, `until 18:00` (the next occurrence) and `off` (returns `None`). The result must be later than `now` and no more than 7 days ahead; otherwise it raises `ValueError(copy.PAUSE_USAGE)`.
  - `register_commands(app: Application, deps: BotDeps) -> None`: registers the commands, with `start` and `help` from Task 20.
  - `/digest` sends `render_digest` immediately and **does not claim** the day's digest key.
  - `/sync` runs `deps.sync.sync(now)`. On OK it replies `✓ synced: N items on your list`, where N is the number of not-done, not-gone items in a fresh `store.snapshot(...)`. On NOT_MODIFIED it replies `✓ no changes`. Otherwise it replies with the outcome's copy line.
  - `/status` reports the next reminder slot: `anchor + (k + 1) × interval` when a cycle is open, otherwise `None`.

- [ ] **Step 1: Write the failing tests:**
  - **`parse_pause`:** `"3h"` → `now + 3h`; `"until 18:00"` at 16:00Z New York (12:00 local) → 22:00Z; `"until 08:00"` at 12:00 local → the next day at 12:00Z; `"off"` → `None`; `"0m"`, `"8d"` and `"soon"` raise.
  - **Views:** `/today` includes an overdue-accepting item and leaves out tomorrow's LOW item; `/week` groups by tier.
  - **Status** text includes the version and "Token: OK" or "Token: failed since …".
  - **Handlers:**
    - `/pause 3h` sets the `PAUSE_UNTIL` state;
    - `/pause` with no argument replies with the usage text;
    - `/digest` doesn't create a `digest:` notification row;
    - `/sync` replies with the count.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(bot): today/week/digest/sync/status/pause commands"`

---

### Task 23: Tick loop, entry point and health check

**Files:**
- Create: `src/canvas_tracker/runtime/loop.py`, `src/canvas_tracker/__main__.py`, `tests/unit/test_loop.py`, `tests/unit/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `class Runtime`, built with `__init__(self, *, store: Store, sync: SyncService, notifier: Notifier, settings: Settings, clock: Callable[[], datetime], can_send: Callable[[], bool], token: Callable[[], str], hidden_courses: frozenset[str] = frozenset(), item_retention: timedelta = timedelta(days=30))`. `AUTH_RECHECK = timedelta(hours=6)`.
    - `async tick() -> None`, following PRD §9.3 exactly:
      1. Sync when `sync_due` says so and one of these holds:
         - `AUTH_FAILED_SINCE` is unset;
         - `token()` returns a different value than at the last failed attempt (the Runtime keeps a SHA-256 of it in memory, never the token itself);
         - the last attempt was `AUTH_RECHECK` or more ago.

         Enrich when `enrichment_due` says so.
      2. Build the snapshot and call `plan()`.
      3. If the plan has sends and the last successful sync is older than `FRESHNESS`, re-sync inside `asyncio.timeout(30)`, then build the snapshot and plan again.
      4. Apply `open_cycle_at` and `close_cycle`.
      5. If `can_send()` is false (not paired), skip all sends.
      6. For each send: `claim`, then `render_send`, then `notifier.send` for every part. Then `mark_sent(key, now, first_message_id)`. On `NotifyError`, `mark_failed(key, type(e).__name__)` instead.
      7. Set `LAST_TICK_AT`.
      8. Run `purge` when `LAST_PURGE_AT` is more than 24 h old.
    - `async run_forever(interval_s: float = 60.0) -> None`: it never dies on an exception. It logs `exc_info`, which the redaction filter covers, and continues.
  - `main(argv: list[str] | None = None) -> int` in `__main__.py`.
    - **Subcommand `healthcheck`:** opens `DB_PATH` read-only (`file:...?mode=ro` URI) and returns 0 if `LAST_TICK_AT` is within 3 min, otherwise 1. It doesn't need the Telegram or Canvas secrets.
    - **Default:**
      1. `load_config` → `configure_logging(level, secrets=[canvas token, telegram token])`.
      2. `connect` + `migrate` the database.
      3. Build the client, `SyncService`, the PTB `Application` (`Application.builder().token(...)`), `TelegramNotifier(app.bot, chat_id=lambda: owner_id(deps))`, `Runtime` (with `token=token_provider(cfg)` and `can_send=lambda: owner_id(deps) is not None`) and `BotDeps`.
      4. Register the gate, commands and callbacks.
      5. Start `runtime.run_forever()` from `post_init` as a task stored on the app; cancel it in `post_shutdown`.
      6. Log the pairing code if no owner exists (that log line deliberately shows the code: it's not a secret token, it's one-time, and it expires).
      7. Call `app.run_polling(allowed_updates=["message", "callback_query"])`.

- [ ] **Step 1: Write the failing tests** (`FakeNotifier`, real in-memory Store, a stub `SyncService` with an `AsyncMock` `sync` that returns OK and upserts given items):
  - One urgent item, first tick → one REMINDER sent, the cycle opened, and `LAST_TICK_AT` set.
  - Second tick 60 s later → no sends.
  - **Freshness:** the last sync was 6 min ago and a send is due → `sync` is called before sending. If that sync marks the item submitted, nothing is sent.
  - **Notify failure:** the row is `failed`, and the next tick 3 min later (the slot still inside its grace) sends successfully.
  - **Not paired** (`can_send` False) → no claims are written.
  - **Auth recheck:** after a 401, no sync for the next 5 h 59 m. A sync happens at 6 h, or right away once the `token` callable returns a new value.
  - **Exception tolerance:** `run_forever` survives `tick()` raising (patch it to raise once, then cancel).
  - **`healthcheck`:** returns 0 with a fresh `LAST_TICK_AT`, 1 with one 4 min old, and 1 with a missing DB file.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Smoke run.** Run `CANVAS_BASE_URL=https://canvas.example.edu CANVAS_TOKEN=x TELEGRAM_BOT_TOKEN=y TIMEZONE=America/New_York DB_PATH=/tmp/t.db uv run python -m canvas_tracker healthcheck; echo $?`. Expected: `1` (no ticks yet), and no traceback.

- [ ] **Step 6: Commit.** `git commit -m "feat(runtime): tick loop, entry point and healthcheck"`

---

### Task 24: Simulation and secret-leak end-to-end tests

**Files:**
- Create: `tests/integration/test_simulation.py`, `tests/integration/golden/simulation.txt`, `tests/integration/test_no_secret_leaks.py`, `tests/conftest.py` (adds the `--update-golden` option)

**Interfaces:**
- Consumes: `Runtime`, `SyncService` with a `CanvasClient` on a respx transport serving planner JSON from a scenario, `FakeNotifier`, a real file-backed Store in `tmp_path`.

- [ ] **Step 1: Write the simulation test.** It's marked `slow`. Time zone `America/New_York`. It runs 2026-10-26 00:00 to 2026-11-15 00:00 local with a fake clock advancing 60 s per tick, crossing the 2026-11-01 change.

  The scenario has these items:
  - A. an assignment due every Tuesday 23:59, never submitted
  - B. due Thu 23:59, submitted Thu 15:10
  - C. due Fri 17:00, extended on Thu by +3 days
  - D. posted Wed 22:50, due 23:30, while no cycle is open
  - E. `on_paper`, graded Mon
  - F. due Sat 03:00 (overnight)
  - G. due Sun 2026-11-01 23:59

  The respx planner route returns the scenario's state at the fake clock's current time. Every send is written as `"{local %a %m-%d %H:%M} {kind} {key}"`, and the log is compared with `golden/simulation.txt`. With `--update-golden`, the file is rewritten instead.

- [ ] **Step 2: Generate the golden file and review it by hand** against the PRD §7.4–7.5 rules. Then commit it.

  Run: `uv run pytest tests/integration/test_simulation.py --update-golden -m slow`. The review must confirm:
  - one digest per day at 08:00
  - no sends at all between 00:00 and 08:00 local (quiet hours)
  - B gets no reminders after its first post-15:10 sync
  - D gets a REMINDER at 22:50 (it opens a new cycle)
  - F gets an OVERNIGHT warning on Fri at 23:30
  - G's reminders follow the 09:59…21:59 pattern on Nov 1
  - A gets exactly one OVERDUE per week.

- [ ] **Step 3: Write `test_no_secret_leaks.py`.**
  - Sentinels: Canvas `"4242~SENTINELsentinelSENTINELsentinel00"` and Telegram `"424242424:SENTINEL_sentinel_SENTINEL_sentinel_00"`.
  - Run `configure_logging("DEBUG", secrets)` with `logging.getLogger("httpx").setLevel(logging.DEBUG)` re-enabled, to simulate the worst case.
  - Run 30 ticks, including a 401 and a 503 response whose bodies echo the token.
  - Assert neither sentinel appears in `caplog.text`, in any notifier message, or in the DB file bytes (`tmp_path / "bot.db"` and `-wal`).

- [ ] **Step 4: Run them.** `uv run pytest tests/integration -m slow -v`. Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -m "test: 3-week DST-crossing simulation golden and secret-leak e2e"`

---

### Task 25: Docker image, compose file and run guide

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `compose.yaml`, `docs/setup/run-mvp.md`
- Modify: `.github/workflows/ci.yml` (add a `docker` job), `README.md` (a short "Status: personal MVP; see docs/setup/run-mvp.md")

**Interfaces:**
- Consumes: `python -m canvas_tracker` and `python -m canvas_tracker healthcheck`.

- [ ] **Step 1: Write the `Dockerfile`.**
  - **Builder stage:** `ghcr.io/astral-sh/uv:0.11-python3.13-bookworm-slim` pinned by `@sha256:` digest (look up the current one). Runs `uv sync --frozen --no-dev --no-editable` into `/app/.venv`.
  - **Runtime stage:** `python:3.13-slim-bookworm@sha256:<digest>`. Copies `/app/.venv`. `ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1`. `USER 10001:10001`. `WORKDIR /data`. `VOLUME /data`.
  - `HEALTHCHECK --interval=60s --timeout=10s --start-period=120s CMD ["python","-m","canvas_tracker","healthcheck"]`
  - `ENTRYPOINT ["python","-m","canvas_tracker"]`
  - No `EXPOSE`.

- [ ] **Step 2: Write `compose.yaml`.**
  - Service `bot`: `image: canvas-tracker:dev`, `build: .`, `env_file: .env`, `restart: unless-stopped`.
  - Secrets `canvas_token` and `telegram_bot_token` from `./secrets/*.txt`, mounted with `CANVAS_TOKEN_FILE=/run/secrets/canvas_token` and the matching Telegram variable.
  - Volume `data:/data`.
  - Hardening: `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`.
  - `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}`. No `ports:`.

- [ ] **Step 3: Add the CI `docker` job**: `docker build -t canvas-tracker:ci .`, then `docker run --rm --entrypoint python canvas-tracker:ci -c "import canvas_tracker; print(canvas_tracker.__version__)"`. Expected output: `0.1.0`.

- [ ] **Step 4: Write `docs/setup/run-mvp.md`** for the owner. It covers:
  - creating the token (with a 120-day expiry and a purpose) and writing it to `secrets/canvas_token.txt` with `chmod 600`
  - creating the Telegram bot with @BotFather
  - `.env` from `.env.example`
  - `docker compose up -d --build`
  - reading the pairing code with `docker compose logs bot | grep pairing`
  - sending `/start <code>`
  - `/status`
  - running without Docker: `uv run python -m canvas_tracker`.

- [ ] **Step 5: Verify.** Push the branch and confirm the `docker` CI job passes. Expected: green, printing `0.1.0`. If Docker is available locally, also run `docker compose config`; expected: no errors.

- [ ] **Step 6: Commit.** `git commit -m "build: hardened Docker image, compose file and MVP run guide"`

---

### Task 26: Contract tests from real (scrubbed) Canvas fixtures

**Blocked on Task 2, Step 8 (the owner's spike run).**

**Files:**
- Create: `tests/contract/test_canvas_contract.py`, `tests/contract/test_fixtures_clean.py`
- Modify: `docs/PRD.md` §17 (record the S1–S8 answers), `src/canvas_tracker/sources/planner.py` and `enrichment.py` (only if the real shapes differ from the hand-made fixtures)

**Interfaces:**
- Consumes: `tests/fixtures/canvas/*.json` from the scrubber.

- [ ] **Step 1: Write the failing tests:**
  - **Planner:** every real planner item maps (no exceptions), every `due_at` is aware UTC, and at least one item has `type == ItemType.ASSIGNMENT`.
  - **Enrichment:** the real `assignment_groups` map; the total points per course are > 0 for at least one course.
  - **`test_fixtures_clean.py`** scans every fixture file for `\d{1,6}~[A-Za-z0-9]{20,}`, `@` email patterns, and any host other than `canvas.example.edu` → none found.

- [ ] **Step 2: Run them.** `uv run pytest tests/contract -v`. Expected: PASS. Any FAIL is a real shape difference: fix the mapper and add a unit test for that shape in `test_planner.py`.

- [ ] **Step 3: Update PRD §17** with the spike answers, and note any resulting change.

- [ ] **Step 4: Commit.** `git commit -m "test: contract tests on scrubbed real Canvas responses; record spike answers"`

---

### Task 27: M1 acceptance (owner-run)

**Files:**
- Create: `docs/m1-acceptance.md`

- [ ] **Step 1: Write `docs/m1-acceptance.md`.** It's a checklist with one box per item from PRD §11.6, plus a 14-day log table (date | digest time | reminders | false nags | duplicates | notes). The checklist items:
  - pairing
  - first digest
  - a real submission stopping reminders, including one New Quiz
  - Done on an offline item
  - snooze
  - quiet hours overnight
  - a revoked test token → one alert
  - a container restart mid-cycle
  - 1 h with the network unplugged → no burst, and the stale banner shown.

- [ ] **Step 2: Commit.** `git commit -m "docs: M1 acceptance checklist"`

- [ ] **Step 3 (owner):** Deploy, following `docs/setup/run-mvp.md`, on your own computer or the recommended host. Run the checklist and keep the 14-day log.
  - **M1 exit (PRD §15):** 14 days with no duplicates, no false nags, and every digest on time.
  - After that, write the M2 plan.
