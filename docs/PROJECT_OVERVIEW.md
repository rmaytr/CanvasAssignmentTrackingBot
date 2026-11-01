# Canvas Assignment Tracker Bot

**A multi-user Telegram assistant that turns a student's Canvas LMS To-Do list into a ranked morning briefing and persistent, deadline-aware reminders.**

`Python 3.13` · `asyncio` · `python-telegram-bot` · `httpx` · `SQLite` · `Pydantic` · `cryptography (Fernet)` · `Docker` · `Google Cloud Compute Engine` · `GitHub Actions` · `pytest` · `Hypothesis` · `mypy --strict`

**Status:** Private beta. 6 active users (the author plus 5 invited testers at several universities); a public release is planned after the beta.
**Repository:** [github.com/rmaytr/CanvasAssignmentTrackingBot](https://github.com/rmaytr/CanvasAssignmentTrackingBot) · **License:** Apache-2.0

---

## 1. Overview

Students miss deadlines because Canvas notifications are easy to ignore: a single email that arrives once, mixed in with announcements. This project replaces them with an assistant that:

- Reads each student's real **Canvas To-Do data** through the Canvas REST API (read-only).
- Sends a **ranked morning list** at the time the student picks, ordered by urgency, share of the final grade and estimated effort.
- Sends **a reminder every 2 hours** for anything due within 24 hours **until it is actually submitted**. It detects submission automatically from Canvas, or the student taps ✅ Done for paper or in-class work.
- Respects **quiet hours**, warns at 11:30 PM about work due overnight, and sends **exactly one** overdue notice instead of nagging forever.
- Runs as **one shared, invite-only bot**. A new user signs up entirely inside the Telegram chat in about 2 minutes, with no installs, accounts or configuration files.

The project went from problem research to a deployed, multi-user beta in about two weeks. Along the way it covered product research, a written specification, test-driven implementation, two independent code reviews, containerized deployment on a cloud VM and live user onboarding.

---

## 2. Key numbers

| Metric | Value |
|---|---|
| Production code | **5,500+ lines** of Python and SQL across **51 modules** in **9 packages** |
| Test code | **5,300 lines** in **42 test files** |
| Automated tests | **426** (unit, property-based, integration, end-to-end simulation, contract) |
| Line + branch coverage | **94%** overall; **98%** on the scheduling and ranking core (CI gate: 95%) |
| Static typing | **100% of modules** type-checked under `mypy --strict`, zero errors |
| Lint rules | 11 Ruff rule families, including security (`S`/Bandit), async-safety and timezone (`DTZ`) checks |
| Simulated time in tests | **3 weeks** (20 days), minute by minute (~28,800 scheduler ticks), across a daylight-saving change |
| Independent code reviews | **2** whole-codebase reviews; **18** Critical or Important findings, all fixed with regression tests |
| Database migrations | 4 versioned SQL migrations across 2 schemas |
| User-facing message templates | 140+ centralized strings (ready for localization) |
| Version history | 54 commits with descriptive, conventional messages |
| Research and design writing | ~43,000 words of research notes, a ~13,000-word product spec and design docs, and a ~12,000-word implementation plan |
| Beta users | **6** (author plus 5 testers), several schools and time zones |
| Hosting cost during beta | **$0** (Google Cloud free-tier `e2-micro` VM under trial credit) |
| Friend sign-up time | about **2 minutes**, entirely in Telegram |
| Owner deployment | **1 command** (`curl … install.sh \| bash`) on a fresh Debian/Ubuntu server |

---

## 3. Features

### For students
- **Morning list** at a chosen time, in the student's own time zone. It covers 14 days ahead and has sections for 🔴 URGENT, 🟠 HIGH, MEDIUM/LOW, ⚠️ OVERDUE, events today and "done yesterday". Each item has a one-line explanation of its rank, for example *"due Thu 11:59 PM (in 2 d) · ≈12% of grade · est. 3 h · start by Thu 7 PM"*.
- **One combined reminder every 2 hours** while anything is due within 24 hours, with ✅ Done, 💤 Snooze 2h, 🔗 Open-in-Canvas and ↩️ Undo buttons.
- **Automatic completion detection** from Canvas submission, grading, excused and "marked complete" states. A deadline extension re-opens an item automatically.
- **Quiet hours** that may wrap past midnight, a **23:30 overnight warning**, a **single overdue notice**, **snooze** (capped at 30 minutes before the deadline) and **/pause**.
- Commands: `/today`, `/week`, `/digest`, `/sync`, `/status`, `/pause`, `/settings`, `/disconnect`, `/help`, plus a native Telegram command menu.
- **Honest stale-data labelling**: when Canvas can't be reached, every message says how old its data is, and the bot never claims "nothing due".

### For the bot owner
- **Invite-only access** through one-time, 7-day invite links (`/invite`).
- **User management**: `/users` shows health per user (school, last sync, token status) without exposing anyone's assignments. `/remove` deletes a user's data after a confirmation by name.
- **One-command install and update** script, a container health check, automatic restarts and log rotation.

---

## 4. Architecture

```
            Telegram (long polling)
                   │
        ┌──────────▼───────────┐
        │  Handlers + gate     │  invite-only, private chats only,
        │  (per-user ordering) │  concurrent across users
        └──────────┬───────────┘
                   │ telegram user id → tenant
        ┌──────────▼───────────┐      ┌───────────────────────────┐
        │  Hub                 │──────│ Registry DB (SQLite)      │
        │  sign-up · settings  │      │ users · invites · state   │
        │  owner commands      │      │ tokens: Fernet ciphertext │
        └──────────┬───────────┘      └───────────────────────────┘
                   │ one tenant per user
   ┌───────────────┼────────────────┐
   ▼               ▼                ▼
 Tenant A        Tenant B   …     Tenant N      each with its own:
 ┌──────────────────────────┐                   • SQLite file
 │ SyncService → CanvasClient│ ── HTTPS ──▶ that user's Canvas
 │ Runtime (60 s tick loop)  │                   • settings / time zone
 │ plan() → render → send    │ ──────────▶ Telegram
 └──────────────────────────┘
```

### Design principles
- **Functional core, imperative shell.** All scheduling and ranking logic is pure and deterministic: `plan(now, snapshot, settings) → Plan`. It does no I/O, which made property-based testing and minute-by-minute simulation practical.
- **Tenant isolation by construction.** Each user has a separate database file and a separate Canvas client, sync service and scheduler. Every Telegram update is routed by the sender's Telegram ID, so no code path can query another user's data.
- **Exactly-once-in-practice delivery.** Every message has a deterministic send key, for example `rem:<cycle-anchor>:<slot>`, claimed atomically with a `UNIQUE` constraint before it is sent. Restarts, crashes and clock changes can't produce duplicate reminders. Split messages resume from the last delivered part.
- **Fault isolation.** Each user's tick runs as its own task. A user whose Canvas instance hangs is skipped rather than waited on, so other users' reminders and the health heartbeat are never delayed.

### Package structure (9 packages, 51 modules)

| Package | Responsibility |
|---|---|
| `domain` | Immutable models, the completion rule, urgency, and the 100-point priority score (urgency 0–50, grade weight 0–35, effort 0–15) |
| `planning` | Pure scheduler: daily digest, reminder cycles anchored in UTC, quiet-hours windows, overnight and overdue alerts, deterministic send keys |
| `render` | Channel-neutral message rendering: HTML escaping, 4,096-character splitting, keyboard and callback-size limits, relative times |
| `sources` | Read-only Canvas REST client and mappers for Planner items, courses and assignment-group weights |
| `store` | SQLite repository in WAL mode with versioned migrations, atomic send claims and column ownership per data source |
| `runtime` | Minute-aligned tick loop, sync scheduling, secret-redacting JSON logging |
| `notify` | Telegram delivery with rate-limit handling |
| `bot` | Per-user commands and inline-button callbacks |
| `hub` | Multi-user layer: registry, encryption, sign-up state machine, input parsing, tenant lifecycle, Telegram routing |

---

## 5. Technical highlights

### Canvas integration
- Uses the **Canvas Planner API** (`/api/v1/planner/items`) with a 28-day lookback and 21-day lookahead window. It adds course and assignment-group data so each item can be ranked by its **actual share of the final grade**, including weighted grade groups.
- A **conditional request (ETag/304)** cuts load from 10-minute polling. The ETag is kept only for single-page results, after a review found that a page-1 ETag can hide changes on later pages.
- **Rate-limit aware** (HTTP 429, and Canvas's 403 "Rate Limit Exceeded"), with capped exponential backoff and full jitter.
- **Hardened client:** GET-only, restricted to `/api/v1/` paths, redirects refused, and cross-host pagination links refused, so a token can never leave its Canvas host. It tells an invalid token (401 with `WWW-Authenticate`) apart from a per-course permission error.

### Scheduling and time handling
- Every timestamp is stored and compared in UTC and converted to the user's IANA time zone only at the edges. Validation in the data model rejects naive or non-UTC datetimes.
- The scheduler runs a **minute-aligned tick** (1 s past each minute), so the loop can't drift past a minute boundary and silently skip, for example, a 23:59 notice.
- Correct across **daylight-saving transitions**, quiet hours that wrap past midnight, and per-user digest windows. This is checked by a 3-week simulation over the US November clock change, compared against a hand-reviewed golden file.

### Security and privacy
- **Encryption at rest:** Canvas tokens are sealed with **Fernet (AES-128-CBC + HMAC-SHA256)**. The key lives outside the data volume, and a wrong key is detected at startup and reported to the owner instead of being shown to users as "token rejected".
- **Secret hygiene:** logging redacts known secrets, tokens learned at runtime and token-shaped strings. Startup and configuration errors never echo a secret. The bot **deletes any chat message that contains a token** at any step of the conversation, and reports honestly when it can't.
- **SSRF protections:** Canvas addresses must be HTTPS on port 443. IP literals and local or internal host names are rejected, and the host must resolve only to public addresses.
- **Least privilege in deployment:** non-root container (UID 10001), read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`, a memory cap, and Docker file secrets instead of environment variables.
- **Supply chain:** dependencies locked with `uv.lock`, the base image pinned by digest, GitHub Actions pinned to commit SHAs, `pip-audit` in CI, and `pre-commit` hooks.
- **Invite codes** have 96 bits of randomness and are stored only as SHA-256 hashes. Owner pairing uses one-time codes with an attempt limit and a 15-minute expiry.

### Conversational onboarding
- A **resumable state machine** stored in the registry (address → token → time zone → morning time → quiet hours) survives restarts.
- **Forgiving input parsing:** accepts any Canvas page URL; time zones by city, region or abbreviation ("Chicago", "Pacific Standard Time", "EST"); times such as "7:30 am", "19:00" or "8"; and quiet hours such as "11pm-7am".
- **Live validation:** the token is checked against Canvas before it is stored, and only the profile's time zone is kept, which is then offered as a one-tap default.
- **Per-user ordering under concurrency:** updates are processed concurrently across users but strictly in order for each user, so sign-up steps never interleave.

### Deployment and operations
- A multi-stage **Docker** build (Python 3.13 slim, uv), **Docker Compose** with a health check, automatic restarts, log rotation and a persistent volume.
- A **one-command installer** (Bash) for Debian/Ubuntu servers:
  - adds swap on 1 GB machines and installs Docker;
  - validates the bot token against the Telegram API without exposing it in the process list;
  - generates the encryption key, refusing to overwrite one while existing data needs it;
  - sets file ownership for the non-root container, starts the bot, and prints the owner's pairing code.
- Runs on **Google Cloud Compute Engine** (`e2-micro`, free tier) and is documented for Oracle Cloud Always Free and home hardware.

---

## 6. Quality engineering

| Layer | What it covers |
|---|---|
| **Unit tests** | Ranking, the completion rule, time utilities, rendering limits, parsing, the store, the Canvas client (with mocked HTTP), sign-up flows, owner commands |
| **Property-based tests** (Hypothesis) | Scheduler invariants: never sends during quiet hours, never sends a key twice, never nags about completed items, respects reminder spacing |
| **Simulation test** | Three simulated weeks run minute by minute against a fake Canvas, across a daylight-saving change, checked against a hand-reviewed golden file of every message sent |
| **End-to-end security tests** | Sentinel tokens pushed through sign-up, sync failures and error paths must never appear in logs, chat messages or any database file. Each test was proven able to fail by injecting the bug it guards against. |
| **Application wiring test** | The real python-telegram-bot `Application` driven by a fake Telegram API through a full owner → invite → friend sign-up → settings → disconnect flow |
| **Contract tests** | Ready to check the parsers against scrubbed real Canvas responses, with a scrubber tool that removes personal data |
| **CI (GitHub Actions)** | Lint, format, `mypy --strict`, tests on Python 3.13 and 3.14 with coverage gates, `pip-audit`, and a Docker build |

**Process:** spec-driven, test-first (red → green → refactor). Every bug found in review was first reproduced with a failing test. Two independent whole-codebase reviews raised 18 Critical or Important issues, all fixed. Examples:
- multi-page ETag staleness;
- container secrets unreadable by the non-root user;
- one tenant's slow Canvas delaying every other tenant;
- duplicate delivery of split messages after a crash;
- tokens remaining in chat history.

---

## 7. Development process

1. **Research.** Compared ways to get Canvas data (REST API, Planner API, iCal feed, GraphQL, scraping), notification channels (Telegram, email, SMS costs and carrier registration), hosting options, security practices and prior art in task prioritization. Result: about 43,000 words of research notes and a synthesized report.
2. **Product specification.** A detailed PRD (goals, anti-goals, the completion rule, ranking model, reminder rules, UX copy, security model, testing strategy, milestones) and later a design doc for the multi-user pivot.
3. **Implementation plan.** 27 bite-sized, test-first tasks with explicit interfaces and a "review focus" list of risky edge cases.
4. **Build.** Implemented test-first, with a written log of every design decision and its cost if wrong.
5. **Review and hardening.** Independent whole-codebase reviews, with every finding re-graded by user impact and fixed using regression tests.
6. **Product pivot.** User feedback showed self-hosting was too complex for non-technical students. The bot was re-architected from a single-user, self-hosted tool into an **invite-only, multi-tenant service with chat-based onboarding** while keeping the tested core unchanged.
7. **Deployment and beta.** Deployed to Google Cloud and onboarded 5 testers at several schools.

AI-assisted development (Claude Code) was used throughout as a pair programmer within this spec-driven, test-first, review-gated workflow. Design decisions, product direction, deployment and beta operations were owned by the author.

---

## 8. Skills demonstrated

**Languages and core:** Python 3.13 (asyncio, dataclasses, typing/generics, protocols), SQL (SQLite schema design, migrations, UPSERT and atomic claims), Bash scripting, Markdown and technical writing.

**Backend and systems:** asynchronous and concurrent programming, multi-tenant architecture and isolation, event-loop scheduling, idempotent and exactly-once delivery design, state machines, REST API integration and pagination, rate limiting and retries with backoff, conditional HTTP caching (ETag), time-zone and DST-correct scheduling.

**Security:** encryption at rest (Fernet/AES + HMAC), secret management and log redaction, SSRF prevention, least-privilege containers, threat modelling (cross-tenant access, token leakage, abuse by strangers), privacy-by-design and data minimization, supply-chain hygiene.

**Testing and quality:** test-driven development, property-based testing (Hypothesis), golden-file simulation testing, HTTP mocking (respx, httpx MockTransport), time travel in tests (time-machine), coverage gates, strict static typing (mypy), linting (Ruff with Bandit rules), code review and root-cause debugging.

**DevOps and cloud:** Docker and Docker Compose (multi-stage builds, health checks, read-only root filesystem, secrets), Google Cloud Compute Engine and Cloud Shell (gcloud CLI), Linux server administration, CI/CD with GitHub Actions, dependency locking with uv.

**APIs and platforms:** Canvas LMS REST API (Planner, Courses, Assignment Groups), Telegram Bot API (python-telegram-bot v22: commands, inline keyboards, callback queries, deep links, message deletion).

**Product and process:** user research and problem framing, writing a PRD, technical design docs, task breakdown and planning, UX copywriting for conversational interfaces, running a beta and onboarding users, cost analysis of hosting options, and turning tester feedback into an architecture pivot.

---

## 9. Roadmap

- **Public release:** a hosted, sign-up-anywhere version with stronger protection (per-user key wrapping, rate limiting, monitoring), a privacy policy and a scalable host.
- **Calendar-feed mode** for schools that block personal access tokens.
- **Email backup** for the morning list, per-user reminder settings, and localization (the copy is already centralized in one module).
- Contract tests against scrubbed real Canvas data gathered during the beta.

---

## 10. Résumé-ready bullet points

- Built a **multi-user Telegram assistant** in **Python (asyncio)** that turns Canvas LMS To-Do data into ranked daily briefings and submission-aware reminders. Now in private beta with **6 users at several universities**.
- Designed a **tenant-isolated architecture** (a database, Canvas client and scheduler per user) with **Fernet-encrypted credentials**, invite-only access and **chat-based onboarding that takes about 2 minutes**.
- Engineered a **deterministic, DST-correct scheduler** with idempotent send keys that prevent duplicate notifications across crashes and restarts. Validated by a **3-week minute-by-minute simulation** and Hypothesis property tests.
- Wrote **426 automated tests** (**94% coverage**, 98% on core logic) under **mypy --strict** and Ruff security linting. Fixed **18 Critical or Important findings** from two independent code reviews, each with a regression test.
- Shipped a **hardened Docker deployment** (non-root, read-only filesystem, no capabilities, file secrets) with a **one-command installer**, running at **$0** on Google Cloud's free tier, with CI on GitHub Actions.
- Integrated the **Canvas REST API** with ETag caching, rate-limit backoff and host-pinned pagination, and the **Telegram Bot API** with inline keyboards, deep-link invites and secure token handling.
