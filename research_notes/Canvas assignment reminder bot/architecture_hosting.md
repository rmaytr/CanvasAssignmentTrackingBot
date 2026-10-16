# Architecture, Scheduling, Storage & Hosting for a Self-Hosted Canvas Reminder Bot (state as of 2026-10-16)

> **How these notes were gathered (read first).** Research date: 2026-10-16. Direct page fetches were blocked by the sandbox proxy for most vendor domains (docs.github.com, developers.cloudflare.com, render.com, fly.io, docs.oracle.com, healthchecks.io, railway, koyeb). Where a vendor keeps its docs in a public GitHub repo, I read the **primary source text from that repo** (GitHub Docs, Cloudflare Docs, CPython docs, Canvas LMS docs, APScheduler, croner, grammY, Docker docs, healthchecks) and cite the public docs URL. Package versions and dates come straight from the PyPI JSON API and the npm registry. Hosting free-tier facts for Render, Fly, Railway, Koyeb, PythonAnywhere, Oracle, GCP, Hetzner, Neon and AWS come from **search-engine summaries** of official or third-party pages. These are marked "(via search summary)" and should be re-checked before publishing.

## 1. Scheduling approaches and their reliability (which give accurate 8:00 AM local delivery with DST?)

### Takeaway
For exact 8:00 local delivery with correct DST, run one always-on process that **computes local time itself with an IANA zone** (a tick loop, or APScheduler 3.11.3+ / croner / node-cron with a `timezone`). An OS-level `systemd` timer with a zone suffix is the other good option. Hosted cron services vary a lot. AWS EventBridge Scheduler supports time zones with documented DST rules and 60 s precision. Cloudflare Cron Triggers are UTC-only but reliable enough if you tick and gate in code. GitHub Actions `schedule` gained a `timezone:` field in 2026, but GitHub documents that it can be delayed or dropped, so it is **unsuitable for an on-time 8:00 digest**.

### Cited Findings

**Python in-process schedulers**
- APScheduler latest stable is **3.11.3 (2026-06-28)**. Latest 4.x is **4.0.0a6 (2025-04-27)**, still alpha, so there has been no 4.x release in about 18 months. — [PyPI APScheduler](https://pypi.org/project/APScheduler/)
- The APScheduler 4.0 version history warns that the v4.0 series is a pre-release that may change in backwards-incompatible ways: "do NOT use this release in production!". The unreleased 4.x branch drops Python 3.9/3.10 and adds more DST fixes for cron/calendar triggers. — [APScheduler master versionhistory.rst](https://github.com/agronholm/apscheduler/blob/master/docs/versionhistory.rst)
- The APScheduler 3.x line has needed repeated DST fixes recently:
  - 3.11.0 added `ZoneInfo` support and deprecated pytz.
  - 3.11.1 fixed "`CronTrigger` sticking on a folded datetime during the fall-back DST transition".
  - 3.11.2 fixed "a job using a `CronTrigger` scheduled in a repeated time interval during DST transitions could cause the scheduler to get stuck in an infinite loop".
  - 3.11.3 fixed sub-minute interval jobs stalling during a spring-forward gap with `ZoneInfo`.
  - UNRELEASED: fixes `AsyncIOScheduler` "permanently stopping the processing of jobs if `_process_jobs()` raised an exception" and `CalendarIntervalTrigger` skipping dates after a forward DST shift.
  — [APScheduler 3.x versionhistory.rst](https://github.com/agronholm/apscheduler/blob/3.x/docs/versionhistory.rst)
- APScheduler 3.x user guide:
  - A late job "is considered to have 'misfired'". "coalescing" can "roll all these missed executions into one".
  - "By default, only one instance of each job is allowed to be run at the same time" (`max_instances`).
  - Persistent job stores need an explicit job ID and `replace_existing=True`.
  - "**Job stores must never be shared between schedulers.**"
  — [APScheduler 3.x userguide.rst](https://github.com/agronholm/apscheduler/blob/3.x/docs/userguide.rst) (rendered: [apscheduler.readthedocs.io/en/3.x](https://apscheduler.readthedocs.io/en/3.x/userguide.html))
- APScheduler 3.x `misfire_grace_time`: `None` means "run it however late it is". `coalesce` defaults to True. Both go in `job_defaults`. — (via search summary) [APScheduler 3.x migration docs](https://apscheduler.readthedocs.io/en/3.x/migration.html), [cronuru APScheduler guide](https://cronuru.com/guides/apscheduler)
- `python-telegram-bot` 22.8 (2026-06-12) pins its `job-queue` extra to `apscheduler>=3.10.4,<3.12.0`, so PTB's JobQueue is APScheduler 3.x underneath. — [PyPI python-telegram-bot](https://pypi.org/project/python-telegram-bot/) (PyPI JSON API)
- `schedule` (dbader) is at 1.2.2, last released 2024-05-25. It supports `every().day.at("12:42", "Europe/Amsterdam")`. Its docs say not to use it if you need "Job persistence (remember schedule between restarts)", "Exact timing", "Concurrent execution", or "Localization". — [schedule README](https://github.com/dbader/schedule), [schedule docs index](https://schedule.readthedocs.io/), [PyPI schedule](https://pypi.org/project/schedule/)

**Node in-process schedulers**
- `node-cron` 4.6.0 (published 2026-07-05) has a `timezone` option. On spring-forward, a daily time inside the missing hour "is skipped that day". On fall-back it "fires on the first occurrence and ignores the second". Sub-hourly schedules can pause during the repeated hour. — [nodecron.com: Timezones and DST](https://nodecron.com/timezones-and-dst); version/date from [npm node-cron](https://www.npmjs.com/package/node-cron)
- `croner` 10.0.1 (2026-02-01):
  - Has a `timezone` option ("Europe/Stockholm format").
  - "Proper DST handling: Jobs scheduled during DST gaps are skipped; jobs in DST overlaps run once at first occurrence."
  - `protect` gives "over-run protection. Will block new triggers as long as an old trigger is in progress".
  - "Zero dependencies". Works on Node ≥18, Deno ≥2.0, Bun ≥1.0 and browsers.
  — [croner README](https://github.com/Hexagon/croner); [npm croner](https://www.npmjs.com/package/croner)
- BullMQ 6.3.15 (2026-10-14) describes itself as a "Redis-based distributed queue", so it adds a Redis/Valkey/Dragonfly dependency. — [BullMQ README](https://github.com/taskforcesh/bullmq)

**OS-level**
- systemd timers:
  - `Persistent=true` stores the last trigger time on disk and "fires immediately if it should have run while the timer was inactive", subject to `RandomizedDelaySec=`. It only applies to `OnCalendar=` timers.
  - An `OnCalendar` expression can carry a zone suffix, e.g. `Mon *-*-* 10:00:00 Asia/Kolkata`.
  - A past Ubuntu bug had timers lock up on a Europe/Dublin DST transition (since fixed).
  — (via search summary of man page) [systemd.timer man page](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html); [NixOS wiki: Systemd/timers](https://wiki.nixos.org/wiki/Systemd/timers); [Launchpad bug 1966800](https://bugs.launchpad.net/bugs/1966800)

**GitHub Actions `schedule`** (primary text read from the GitHub Docs source repo)
- Official text: "The `schedule` event can be delayed during periods of high loads of GitHub Actions workflow runs. High load times include the start of every hour. If the load is sufficiently high enough, some queued jobs may be dropped. To decrease the chance of delay, schedule your workflow to run at a different time of the hour." — [GitHub Docs: Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) (source: [schedule-delay.md](https://github.com/github/docs/blob/main/data/reusables/actions/schedule-delay.md))
- Official text: "By default, scheduled workflows run in UTC. You can optionally specify a timezone using an IANA timezone string". Also: "Scheduled workflows run on the latest commit on the default branch. The shortest interval you can run scheduled workflows is once every 5 minutes." DST note: "during DST spring-forward transitions, scheduled workflows in skipped hours advance to the next valid time. For example, a 2:30 AM schedule advances to 3:00 AM." Example: `- cron: '30 5 * * 1-5'` / `timezone: "America/New_York"`. — [GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) (source: [actions-scheduled-workflow-example.md](https://github.com/github/docs/blob/main/data/reusables/repositories/actions-scheduled-workflow-example.md))
- The timezone feature flag is enabled for github.com (`fpt: '*'`), GHEC, and GHES ≥3.22. — [actions-schedule-timezone.yml](https://github.com/github/docs/blob/main/data/features/actions-schedule-timezone.yml)
- Third-party guides date timezone support to **March 2026** (I couldn't open the GitHub changelog post). — (via search summary) [cronuru GHA guide](https://cronuru.com/guides/github-actions-scheduled-workflows), [itime.day](https://itime.day/articles/github-actions-cron-timezone)
- Official text: "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days." `@daily`/`@hourly` shorthands are not supported. — [GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- Whether GitHub warns before the 60-day disable is disputed. A community thread says an email is sent some days before; third-party guides say it is silent. — [GitHub Community #184653](https://github.com/orgs/community/discussions/184653); [cronuru](https://cronuru.com/guides/github-actions-scheduled-workflows)
- Field report from **2026-07-13**:
  - A daily cron on a new free account and public repo ran **8–14 hours late**.
  - Moving the minute from :00 to :07 didn't help.
  - Runs were dropped entirely on at least two days.
  - No GitHub staff reply. A community answer speculated about a low-priority queue for new accounts, which is undocumented.
  — [GitHub Community #201738](https://github.com/orgs/community/discussions/201738)
- Minutes and cost: usage is "**free** for **self-hosted runners** and for **public repositories** that use standard GitHub-hosted runners". Private repos get **2,000 min/month** (Free plan) or **3,000** (Pro/Team). "GitHub rounds the minutes and partial minutes each job uses up to the nearest whole minute." — [GitHub Docs: Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions); [included quotas](https://github.com/github/docs/blob/main/data/reusables/billing/actions-included-quotas.md); [Actions runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing)
- A single-CPU `ubuntu-slim` runner (container-based, unprivileged, no Docker-in-Docker) is "available in both public and private repositories" as a lower-cost option for lightweight jobs. — [GitHub Docs: GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- 2026 pricing changes:
  - Hosted-runner price cuts of up to 39% took effect 2026-01-01.
  - A proposed $0.002/min self-hosted runner platform charge (planned for 2026-03-01) was **postponed**.
  - Public repos remain free.
  — (via search summary) [GitHub changelog 2025-12-16](https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/); [resources.github.com 2026 pricing](https://resources.github.com/actions/2026-pricing-changes-for-github-actions/)
- Forgejo Actions also supports a `timezone` field. Its docs say spring-forward jobs are **skipped** and fall-back jobs **run twice**, which differs from GitHub's "advance to next valid time". — (via search summary) [Forgejo Actions reference](https://forgejo.org/docs/latest/user/actions/)

**Cloudflare Workers Cron Triggers** (primary text from the cloudflare-docs repo)
- "Cron Triggers execute on UTC time." Changes "may take several minutes (up to 15 minutes) to propagate". The local test endpoint returns `noRetry`, set when the handler calls `controller.noRetry()`, which implies failed scheduled runs may be retried. — [Cloudflare Docs: Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
- Free plan limits:
  - Requests: 100,000/day.
  - CPU per Cron Trigger: **10 ms**. CPU time does **not** include time spent waiting on `fetch()`/KV/DB.
  - Memory: 128 MB.
  - Subrequests: **50/request**.
  - **5 Cron Triggers per account**.
  - Cron duration: 15 min wall-clock.
  — [Cloudflare Docs: Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
- A third-party "gotchas" reference says cron delivery is at-least-once, so handlers should be idempotent. This is not confirmed in official text. — (via search summary) [claude-code-skills cron gotchas (jsDelivr)](https://cdn.jsdelivr.net/npm/claude-code-skills@0.5.0/data/skills/cloudflare-deploy/references/cron-triggers/gotchas.md)

**Serverless cron on AWS / GCP**
- AWS EventBridge Scheduler:
  - Each schedule has an expression plus a time zone (`--schedule-expression-timezone`), and it "automatically adjusts schedules for daylight saving time".
  - On spring-forward, a run at a nonexistent local time is **skipped**. On fall-back it fires **once**.
  - Precision is **60 seconds**.
  - Free tier: **14 million invocations/month**.
  — (via search summary) [AWS Docs: Schedule types](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html); [EventBridge Scheduler product page](https://aws.amazon.com/eventbridge/scheduler/)
- AWS Free Tier changed for accounts created on or after **2025-07-15**:
  - $100 credit at sign-up plus up to $100 earned.
  - The free plan expires after **6 months or when credits run out**.
  - "Over 30 always-free services" remain. The Lambda 1M requests/month figure came only from a community post in my results.
  — (via search summary) [AWS What's New 2025-07](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/); [AWS News Blog](https://aws.amazon.com/blogs/aws/aws-free-tier-update-new-customers-can-get-started-and-explore-aws-with-up-to-200-in-credits)
- Google Cloud Scheduler gives **3 free jobs per billing account** per month (not per project), then $0.10/job/month. Paused jobs still count. Per-job time zones are supported (third-party listing). — (via search summary) [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing); [SoftwareOne listing](https://platform.softwareone.com/product/cloud-scheduler/PCP-8002-5839)

### Inferences

**Accuracy and DST ranking for an 8:00 local digest (best to worst):**

| Approach | Typical punctuality | DST correctness | Free? | Notes |
|---|---|---|---|---|
| Always-on process with its own tick loop + `zoneinfo`/Temporal | ≤ tick interval (e.g. 60 s) | You control it (test both transitions) | Host-dependent | Fewest moving parts. Survives restarts if state is in the DB |
| APScheduler 3.11.3+ CronTrigger with `ZoneInfo` | seconds | Good after the 3.11.1–3.11.3 fixes | yes | Pin `>=3.11.3,<4`. Don't adopt 4.0 alpha |
| croner / node-cron with `timezone` | seconds | Gap skipped, overlap once | yes | croner `protect:true` prevents overlapping runs |
| systemd `OnCalendar=… America/Chicago` + `Persistent=true` | seconds | Good | yes | Catch-up after downtime is built in, but each run is a cold process start |
| AWS EventBridge Scheduler (tz) → Lambda | ≤60 s | Documented skip/once | Within always-free (re-verify) | New AWS accounts' free plan expires after 6 months, so this needs a paid-plan account billed at ~$0 |
| Cloudflare Cron (`*/5 * * * *`, gate on local time in code) | Minutes (no documented delays) | You handle it (cron is UTC) | yes | 5 triggers/account. 10 ms CPU (I/O excluded). 50 subrequests/invocation |
| GitHub Actions `schedule` with `timezone:` | **Minutes to hours late; can be dropped** | Documented skip-forward | Public repo free | **Not acceptable for an 8:00 SLA.** Fine as a best-effort fallback |

- A tick loop also avoids most scheduler-library DST bugs. The APScheduler changelog shows DST edge cases kept turning up through 2025–2026. Computing "is it ≥ 08:00 local today and has today's digest not been sent?" with `zoneinfo` sidesteps cron-trigger arithmetic entirely.
- For a GitHub-Actions-only variant, scheduling at an odd minute (e.g. `:17`) follows GitHub's own advice. A digest window ("any run between 08:00 and 11:00 local sends today's digest if not yet sent") turns late runs into late-but-delivered messages instead of losses.

### Gaps
- No official uptime or punctuality statistics for Cloudflare Cron Triggers. "At-least-once" comes only from third-party material.
- Couldn't open the GitHub changelog entry announcing `timezone:` support, so the exact launch date (reported as March 2026) is unverified.
- No official statement on whether GitHub sends a warning email before the 60-day disable. Sources conflict.
- No official doc on how GitHub handles the **fall-back** (repeated hour) case for timezone schedules. Docs only describe spring-forward.

## 2. Time zone and DST correctness

### Takeaway
Store every instant as UTC (Canvas already returns UTC ISO-8601). Store the user's **IANA zone name** (e.g. `America/New_York`), never a fixed offset. Convert only at the edges: computing "today's 08:00 local" and rendering due dates. Python's `zoneinfo` (plus the `tzdata` package in slim containers) and JS Temporal (now default in Node 26) both handle gaps and folds correctly if used as documented.

### Cited Findings
- `zoneinfo` provides IANA time zone support (PEP 615). It uses the system tz database and falls back to the first-party `tzdata` PyPI package. "Some systems, including notably Windows systems, do not have an IANA database available", so it is "recommended to declare a dependency on tzdata". If neither is present, `ZoneInfo` raises an error. — [Python docs: zoneinfo](https://docs.python.org/3/library/zoneinfo.html) (source: [cpython Doc/library/zoneinfo.rst](https://github.com/python/cpython/blob/main/Doc/library/zoneinfo.rst))
- `zoneinfo` supports PEP 495 `fold`. During ambiguous transitions, `fold=0` uses the offset *before* the transition and `fold=1` the offset *after*. "When converting from another time zone, the fold will be set to the correct value." — [Python docs: zoneinfo](https://docs.python.org/3/library/zoneinfo.html)
- Temporal shipped in Firefox 139 (2025-05-27) and Chrome 144 (2026-01-13). Safari has not shipped it per the proposal README. The proposal is at Stage 4. — [tc39/proposal-temporal README](https://github.com/tc39/proposal-temporal)
- Node.js **26.0.0 (2026-05-05)** enables Temporal by default with no flag (V8 14.6). Node 26 is "Current", with LTS promotion scheduled for October 2026. — [Help Net Security 2026-05-07](https://www.helpnetsecurity.com/2026/05/07/node-js-26-released/); [InfoQ 2026-07](https://infoq.com/news/2026/07/nodejs-26-temporal)
- Documented DST behaviors differ by scheduler:
  - GitHub Actions advances spring-forward runs to the next valid time.
  - EventBridge skips nonexistent times and fires once on fall-back.
  - node-cron and croner skip gap times and run once in overlaps.
  - Forgejo skips gaps and **runs twice** on fall-back.
  — [GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows); [AWS Scheduler docs](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html) (via search summary); [nodecron.com](https://nodecron.com/timezones-and-dst); [croner](https://github.com/Hexagon/croner); [Forgejo](https://forgejo.org/docs/latest/user/actions/) (via search summary)
- Cloudflare Cron Triggers are UTC-only, so local-time schedules must be converted manually and re-adjusted at DST changes, or handled in code. — [Cloudflare Docs: Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/); [cronuru Cloudflare guide](https://cronuru.com/guides/cloudflare-workers-cron-triggers) (via search summary)
- `canvasapi` depends on `arrow`, `pytz` and `requests` (PyPI metadata). That is relevant because pytz has different localization semantics from zoneinfo, and APScheduler 3.11 deprecated pytz. — [PyPI canvasapi](https://pypi.org/project/canvasapi/); [APScheduler 3.x versionhistory](https://github.com/agronholm/apscheduler/blob/3.x/docs/versionhistory.rst)

### Inferences
- **8:00 AM is never inside a DST gap or overlap in any common zone**, since transitions happen around 00:00–03:00 local. So the daily digest itself is safe. The real DST risks are:
  1. "Every 2 hours" reminders. Use **UTC durations** (`last_sent_utc + 2h`), not local wall-clock slots. Otherwise reminders bunch up or skip across transitions.
  2. "Due within 24 hours". Compute `due_at_utc - now_utc <= 24h` in UTC. Across a transition, "24 h" and "same time tomorrow" differ by an hour.
  3. Rendering "due tomorrow at 11:59 PM". Convert UTC→zone only for display.
- Recommended computation for the digest: `today_local = now_utc.astimezone(tz).date()`, `target = datetime.combine(today_local, time(8), tzinfo=tz)`. Then `if now_utc >= target.astimezone(UTC) and not sent(user, 'digest', today_local): send`. The idempotency key is the **local date**, which handles DST, restarts and late ticks together.
- Ship `tzdata` as a Python dependency and use `python:*-slim` images. Slim/Alpine/distroless images may lack `/usr/share/zoneinfo`, and the docs recommend `tzdata` where no system database exists.
- Prefer `zoneinfo` + stdlib `datetime.fromisoformat` (which parses Canvas's `Z` suffix on Python 3.11+) over arrow/pytz in your own code, even though canvasapi pulls in pytz. In TS on Node 24 LTS, use `@js-temporal/polyfill` or Luxon until Node 26 LTS is adopted. Luxon wasn't researched here.
- Let users override the zone with a `/timezone` command. Default to the zone in the Canvas user profile if the Canvas-API researcher confirms one is exposed (not verified here).

### Gaps
- Didn't verify whether Cloudflare Workers' runtime exposes Temporal natively. `Intl.DateTimeFormat` with `timeZone` is the safe fallback.
- No authoritative test matrix found comparing DST behavior across APScheduler, croner and node-cron. Behaviors above are each library's own claims.

## 3. Reminder scheduling design: tick loop vs per-job scheduling; idempotency; missed ticks

### Takeaway
Use a **single idempotent "tick" (reconcile) loop**, roughly every 1–5 minutes for sends and every 10–15 minutes for Canvas polling. It derives everything owed from persisted state and records each send under a **deterministic idempotency key** in the same database as a UNIQUE constraint. Don't schedule one job per reminder. Missed ticks should **coalesce**: send at most one catch-up digest within a grace window and only the *current* reminder, never a burst.

### Cited Findings
- APScheduler's own model for missed runs is "misfire" plus "coalescing" to "roll all these missed executions into one". `misfire_grace_time` controls how late is too late. — [APScheduler 3.x user guide](https://github.com/agronholm/apscheduler/blob/3.x/docs/userguide.rst)
- APScheduler persistent job stores require explicit IDs and `replace_existing=True`, or re-adding raises `ConflictingIdError`. "Job stores must never be shared between schedulers." — [APScheduler 3.x user guide](https://github.com/agronholm/apscheduler/blob/3.x/docs/userguide.rst); [cronuru APScheduler](https://cronuru.com/guides/apscheduler) (via search summary)
- systemd `Persistent=true` catches up missed runs on activation. Blog posts warn that a multi-hour outage with catch-up can cause "a burst of catch-up runs". — (via search summary) [systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html); [cronuru systemd timers](https://cronuru.com/guides/systemd-timers)
- croner's `protect` option blocks new triggers while a previous run is still going, which prevents overlapping ticks. — [croner README](https://github.com/Hexagon/croner)
- Transactional outbox pattern:
  - Write the message to an outbox table in the same transaction as the state change, then a relay publishes it.
  - Because the relay can republish after a crash, consumers must be **idempotent**, e.g. by tracking processed message IDs. Delivery is at-least-once.
  - Running several relays risks double-publishing. Locking such as `FOR UPDATE SKIP LOCKED` is the mitigation in Postgres.
  — (via search summary) [microservices.io: Transactional outbox](https://microservices.io/patterns/data/transactional-outbox.html)
- Cloud cron triggers can retry (`noRetry` exists in Cloudflare's scheduled handler API). Third-party sources call Cloudflare cron at-least-once. — [Cloudflare Docs: Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/); [jsDelivr gotchas](https://cdn.jsdelivr.net/npm/claude-code-skills@0.5.0/data/skills/cloudflare-deploy/references/cron-triggers/gotchas.md)
- GitHub Actions scheduled runs can be delayed or dropped, so any GHA-driven design must tolerate missing and late ticks. — [GitHub Docs schedule-delay](https://github.com/github/docs/blob/main/data/reusables/actions/schedule-delay.md)

### Inferences

**Recommended tick-loop design (single-user, multi-tenant-ready):**
- **Two loops, one process.**
  - (a) `sync` every 10–15 min (configurable). Fetch upcoming assignments and submission status from Canvas, then upsert `assignments(id, course_id, name, due_at_utc, html_url, submitted, submitted_at, updated_at)`.
  - (b) `notify` every 60 s. It is pure DB work plus sends, so it's cheap.
  - Also run a sync right before the 08:00 digest so the digest is fresh.
- **What's owed** (evaluated every notify tick):
  - Digest: `now_local >= 08:00` and no `notifications` row with key `digest:{user}:{local_date}`. Add a **grace window** (e.g. until 12:00 local). If the host was down past it, skip and optionally fold a note into the next message.
  - 2-hourly reminders: for each assignment with `0 < due_at_utc - now_utc <= 24h` and not submitted, compute a **slot index** `k = floor((now_utc - (due_at_utc - 24h)) / 2h)`. Key it `rem:{user}:{assignment_id}:{k}`. That gives at most 12 reminders per assignment, with a deterministic key per 2-hour slot. After downtime, only the current slot fires, which coalesces naturally. Alternative: `last_reminded_at_utc` with `now - last >= 2h - tolerance`. That is simpler but less explicit about duplicates.
  - Re-check submission status shortly before each reminder (or rely on a recent sync), so a "you still haven't submitted" message doesn't go out right after a submission. A sync just before each reminder slot, or a sync interval ≤ 15 min, bounds the staleness.
  - Handle edits: if `due_at` changes, the slot keys change too. Including `due_at` in the key (`rem:{assignment_id}:{due_at_epoch}:{k}`) makes an extended deadline restart the schedule cleanly.
- **Exactly-once-ish send protocol.** Telegram has no idempotency key, so you must choose:
  - *At-least-once:* `INSERT notifications(key, status='pending')` (UNIQUE key). Send, then `UPDATE status='sent', sent_at=…`. On restart, retry `pending` rows older than N minutes. A crash between send and update can produce **one** duplicate, which is acceptable for reminders.
  - *At-most-once:* mark sent before sending. A crash loses a message. Prefer at-least-once for the digest and either for reminders.
- **Overlap and leader safety.**
  - Single instance: run the ticks sequentially in one asyncio task (no concurrency). Also take a SQLite `BEGIN IMMEDIATE` or an OS file lock at startup so a second container on the same volume refuses to start.
  - Multi-tenant or multi-replica: Postgres advisory lock or `SELECT … FOR UPDATE SKIP LOCKED` on due work.
- **Why not per-reminder jobs** (APScheduler `date` jobs / BullMQ delayed jobs):
  - Jobs must be rescheduled whenever Canvas data changes (due date edits, submissions, new assignments).
  - The job store becomes a second source of truth, and it must never be shared between schedulers.
  - Every edit and restart becomes a reconciliation problem anyway.
  - A tick loop *is* the reconciliation, so it's naturally idempotent and restart-safe.
- **Fits every hosting model.** The same `tick()` function can be called by an in-process loop (VPS/Pi), systemd timer, Cloudflare cron, EventBridge or GitHub Actions. That makes the "GitHub-Actions-only" mode a deployment option rather than a separate codebase.

**Multi-tenant later phase — what changes:**
- Add `users(id, tz, chat_id, canvas_base_url, token_ref, active)` and scope all keys by user.
- Shard ticks by user with `SKIP LOCKED` or a per-user `next_check_at`. Spread Canvas polling with jitter to avoid hitting all users at :00.
- Move to OAuth2 (see §8). Encrypt tokens at rest.
- Use Postgres instead of SQLite once there are multiple workers. Switch Telegram from long polling to webhooks behind a load balancer.

### Gaps
- No authoritative source on Telegram Bot API idempotency (none known). The duplicate-on-crash trade-off above is inference.
- Exact Canvas submission-state semantics (e.g. `workflow_state`, `excused`, `missing`, resubmissions) were out of scope here and belong to the Canvas-API research.

## 4. Storage

### Takeaway
For a single-user (or one-household) self-hosted bot, **SQLite in WAL mode on a local Docker volume** is the right default. It has zero ops, one file to back up, readers don't block the writer, and the bot only ever has a single writer. Avoid JSON files once you need atomic "check-then-record" idempotency. Use hosted Postgres (Neon/Supabase) only for serverless deployments or the multi-tenant phase, and note that both free tiers sleep or pause. For Cloudflare Workers, D1 is a free SQLite-compatible option whose free-tier limits became **hard-enforced on 2026-09-01**.

### Cited Findings
- SQLite WAL: "readers do not block writers and a writer does not block readers". "Since there is only one WAL file, there can only be one writer at a time". WAL "will not work on a network filesystem". It requires shared-memory support, which the default unix/windows VFS provides. — (via search summary of sqlite.org docsrc) [SQLite: Write-Ahead Logging](https://www.sqlite.org/wal.html)
- Cloudflare D1 free plan:
  - **5 million rows read/day**, **100,000 rows written/day**, **5 GB total storage**.
  - 10 databases, 500 MB max per DB, 50 queries per Worker invocation.
  - Limits reset 00:00 UTC. Indexes add an extra written row.
  — [Cloudflare D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/) (source: [d1-pricing partial](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/partials/workers/d1-pricing.mdx)); [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- "Beginning September 1, 2026, D1 queries on the Workers Free plan will fail when an account exceeds the daily row read or row write limits … until the limit resets at midnight UTC. Stored data is not affected." — [Cloudflare changelog 2026-09-01](https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/)
- Workers KV free plan: 100,000 reads/day and **1,000 writes/day** (also 1,000 deletes/lists per day). Same-key writes are limited to 1/s. — (via search summary) [Cloudflare KV limits](https://developers.cloudflare.com/kv/platform/limits/); [KV pricing](https://developers.cloudflare.com/kv/platform/pricing/)
- Supabase pauses Free Plan projects with low activity "over a 7-day period". It sends a warning about a week ahead, and projects can be restored for up to 1 year. A blog claim about changes from 2026-10-30 is unverified. — (via search summary) [Supabase Docs: Project pausing](https://supabase.com/docs/guides/platform/free-project-pausing)
- Neon free plan (2026 third-party): ~**100 CU-hours/month per project**, 0.5 GB storage. Compute **scales to zero after 5 minutes** and that can't be disabled on Free. One listing says "5 compute hours", which looks like an outlier. — (via search summary) [Jetadmin: Neon pricing (2026-09-26)](https://www.jetadmin.io/blog/neon-pricing/); [selfhost.dev](https://selfhost.dev/neon-pricing-cost-of-serverless-postgres/)
- APScheduler's SQLAlchemy job store exists, but its jobs are pickled and the store must not be shared between schedulers. — [APScheduler 3.x user guide](https://github.com/agronholm/apscheduler/blob/3.x/docs/userguide.rst)

### Inferences
- **Schema** (minimal):
  - `users(id, tz, chat_id, digest_hour default 8, created_at)`
  - `courses(id, name, enabled)`
  - `assignments(id PK, course_id, name, due_at_utc, url, submitted bool, submitted_at, last_synced_at)`
  - `notifications(key TEXT UNIQUE, user_id, kind, assignment_id NULL, status, created_at, sent_at, error)`
  - `kv(key, value)` for `last_successful_sync_at`, `token_status`, `schema_version`
- **SQLite settings:**
  - `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000; foreign_keys=ON;`
  - Keep the DB on a **local** Docker named volume, never NFS/SMB, per the WAL network-FS warning.
  - Back up with `sqlite3 .backup` or `VACUUM INTO`, not a raw file copy while running.
- **Migrations:**
  - Python: Alembic (with SQLAlchemy) is the standard. A hand-rolled `schema_version` + ordered `.sql` files runner is also sufficient at this size and avoids SQLAlchemy entirely.
  - TS: Drizzle (`drizzle-kit`) supports SQLite/D1/Postgres from one schema, which fits a "VPS SQLite ↔ Cloudflare D1 ↔ Postgres later" story. Prisma is heavier.
  - (Alembic/Drizzle/Prisma docs weren't retrieved; this is general knowledge, so verify before citing.)
- **JSON file:** OK for a GitHub-Actions-only mode where state is committed back to the repo or cache. There, "write file + commit" *is* the persistence and concurrency is controlled by `concurrency:` groups. It is fragile otherwise, with no atomic UNIQUE check and a corruption risk on crash without write-rename.
- **Usage fits easily within D1 free:** a single user writes perhaps a few hundred rows/day (sync upserts + notifications), far below 100k. A 1-minute cron is 1,440 invocations/day, well under the 100k requests/day limit.
- **Hosted Postgres:** Neon's scale-to-zero means the first query after idle has a cold-start delay. That's fine for a tick every 5–15 min. Supabase's 7-day inactivity pause doesn't trigger because a polling bot queries daily, but don't depend on that for a production multi-tenant service.

### Gaps
- Couldn't retrieve official Neon pricing page text. The 100 CU-hour figure is from third-party 2026 blogs.
- Didn't retrieve Alembic/Drizzle/Prisma docs (no reachable source in this session).

## 5. Hosting options for 24/7 small bots (2026), with free-tier facts and gotchas

### Takeaway
Truly free and always-on hosts that keep a **long-polling** process alive are now scarce:
- **Oracle Cloud Always Free (A1 Arm):** generous, but idle-reclaim risk unless you upgrade to Pay-As-You-Go.
- **Google Cloud e2-micro:** small but always-free in three US regions.
- **Your own Raspberry Pi or home server.**
- **Cloudflare Workers:** serverless, cron + webhooks, no long polling.

Render free, Koyeb free and Fly (for new users) all **sleep or have no free tier**, which breaks polling bots. Hetzner is the "just pay ~€5–6/month" option after its 2026 price rises. PythonAnywhere free is unusable here because of outbound restrictions and no always-on task.

### Cited Findings

**Comparison table (facts below are each cited)**

| Host | Free / cheapest | Sleeps / spins down? | Long-polling bot OK? | Key gotchas | Sources |
|---|---|---|---|---|---|
| Oracle Cloud Always Free (Ampere A1) | 3,000 OCPU-h + 18,000 GB-h/mo = **4 OCPU / 24 GB** | No, but **idle instances may be reclaimed** | Yes | Idle if over 7 days the 95th-percentile CPU, network **and** (A1 only) memory are all <20%. Threshold history: 10% → 15% (2023) → 20% today. Converting to PAYG avoids reclaim while staying $0 within limits. An unconfirmed 2026 blog claims the allowance was cut to ~2 OCPU/12 GB | [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) (via search summary); [51sec: idle reclaim & PAYG](https://blog.51sec.org/2023/02/oracle-cloud-cleaning-up-idle-compute.html); [braindetox (unconfirmed cut claim)](https://braindetox.kr/en/posts/oracle_always_free_tier_reduced_2026.html) |
| Google Cloud e2-micro | 1 e2-micro in us-west1/us-central1/us-east1, 30 GB **standard** PD, 1 GB/mo N. America egress | No | Yes | Balanced/SSD disks are billed. Hours may be pooled across the 3 regions (744 h). External IPv4 may not be free (unconfirmed). All from third-party guides | [agentdeals GCP 2026](https://agentdeals.dev/gcp-free-tier-2026); [dev.to GCP guide](https://dev.to/jeaniscoding/how-to-host-your-side-projects-for-0-the-ultimate-gcp-free-tier-guide-3p07) (via search summary) |
| Fly.io | **No free tier for new customers.** Trial reported as 2 machine-hours or 7 days. Legacy orgs keep 3 shared VMs + 3 GB | Machines can auto-stop if configured | Paid only (cheap) | Hobby/Launch/Scale plans discontinued around 2024-10-07. grammY's community table still lists Fly as "Free" (stale) | [Fly: discontinued plans](https://fly.io/docs/about/discontinued-plans/); [temps.sh Fly 2026](https://temps.sh/blog/fly-io-pricing-2026); [SaaS Price Pulse](https://www.saaspricepulse.com/blog/flyio-pricing-history) (via search summary); [grammY hosting comparison](https://grammy.dev/hosting/comparison) |
| Railway | Hobby **$5/mo** (includes $5 usage). Trial reported as $5 for 30 days; a "$1/mo free" tier is reported inconsistently | Not when paid | Yes (paid) | Sources conflict on the free tier. Treat as paid | [livemy Railway 2026](https://livemy.app/blog/railway-pricing); [toolradar Railway](https://toolradar.com/tools/railway/pricing) (via search summary) |
| Render | Free **web services** only, 750 instance-h/mo per workspace | **Yes: after 15 min with no inbound HTTP or WebSocket message** (Feb 2026 rule) | **No** (outbound polling isn't inbound traffic) | Background workers have **no free type** (cheapest ~$7/mo). Cold start ~30–60 s. Legacy workspaces auto-migrated to new plans on 2026-08-01 with much less included bandwidth | [Render changelog (WebSocket keep-alive)](https://render-www.onrender.com/changelog/free-web-services-now-remain-active-while-receiving-websocket-messages); [Render: new workspace plans](https://render.com/docs/new-workspace-plans); [temps.sh Render 2026](https://temps.sh/blog/render-pricing-2026); [jwatte review (Jul 2026)](https://jwatte.com/blog/render-com-platform-review/) (via search summary) |
| Koyeb | 1 free instance/org (512 MB, 0.1 vCPU, 2 GB SSD; Frankfurt/Washington) | **Yes: scales to zero after 1 h without traffic, can't be disabled** | **No.** Free instance "cannot be used for Worker Services" | Acquired by **Mistral AI (announced 2026-02-17)**. Card verification reportedly now required ($29 pre-auth). New accounts reportedly default to Pro $29/mo. Sources are partly competitors | [Koyeb pricing](https://www.koyeb.com/pricing); [SnapDeploy (competitor)](https://snapdeploy.dev/blog/koyeb-vs-free-container-tier); [Kuberns](https://kuberns.com/blogs/koyeb-alternatives/); [Plushcap Koyeb 2026-02](https://www.plushcap.com/companies/koyeb/blog/summaries/2026/2) (via search summary) |
| PythonAnywhere | Free "Beginner" | No always-on tasks on free. Third-party sources say no scheduled tasks on free | **No** | Free outbound internet limited to an **allowlist of sites over HTTP(S)**, so arbitrary university Canvas domains may be blocked. The always-on task needs the paid Developer plan | [PythonAnywhere pricing](https://www.pythonanywhere.com/pricing/); [freetier.co](https://freetier.co/directory/products/pythonanywhere); [InstaPods comparison](https://instapods.com/vs/pythonanywhere/) (via search summary) |
| Hetzner Cloud (VPS + Docker Compose) | CAX11 (Arm): €3.29 → **€4.49** (2026-04-01) → **€5.99** for new orders (2026-06-15, DE/FI). CX23: €3.99 → €5.49 | No | Yes | Two 2026 price rises. Prices exclude VAT and IPv4. Sources disagree on the size of the June rise | [igorslab (Apr 2026)](https://www.igorslab.de/en/hetzner-to-significantly-increase-prices-for-cloud-and-dedicated-servers-from-april-2026/); [wz-it (Jun 2026)](https://wz-it.com/en/blog/hetzner-price-increase-june-2026-cpx-ccx-alternatives/); [privatedevops](https://privatedevops.com/news/hetzner-june-2026-cloud-price-increase-what-to-do); [agentdeals](https://agentdeals.dev/hetzner-pricing-2026) (via search summary) |
| Cloudflare Workers (+ D1) | Free: 100k req/day, 10 ms CPU, 5 cron triggers/account, D1 5M reads / 100k writes per day | N/A (serverless) | **No polling.** Webhooks + cron only | UTC-only cron. 50 subrequests/invocation. D1 limits hard-enforced since 2026-09-01 | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/); [D1 changelog](https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/) |
| GitHub Actions-only | Public repo: free standard runners. Private: 2,000 min/mo on the Free plan, jobs rounded up to whole minutes | N/A | **No** (no inbound, so push-only and no bot commands) | ≥5-min interval. Delays and drops. **60-day auto-disable in public repos**. Runs on the default branch | [GitHub Docs events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows); [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions); [runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing) |
| AWS EventBridge Scheduler + Lambda | 14M scheduler invocations/mo free | N/A | Webhook only | New accounts (≥2025-07-15) get a 6-month/credit-limited free plan, then must upgrade to a paid plan. Always-free services continue | [EventBridge Scheduler](https://aws.amazon.com/eventbridge/scheduler/); [AWS Free Tier 2025-07](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/) (via search summary) |
| Raspberry Pi / home server | Hardware + electricity | No | Yes (outbound only, no port forwarding needed for polling) | See inferences | — |

- grammY's hosting guide: "on serverless infrastructures you are required to use webhooks. Most of providers below will have issues when you try running your bot with polling". Polling on PaaS works only "if the provider you choose lets you keep exactly single instance running at all times". Its table is community-maintained and partly stale (e.g. Fly listed as Free). — [grammY: Comparison of Hosting Providers](https://grammy.dev/hosting/comparison) (source: [grammyjs/website](https://github.com/grammyjs/website/blob/main/site/docs/hosting/comparison.md))
- Render: upgrading the workspace plan "does not remove limitations on Free instances". Only moving the service to a paid instance does. When the 750 hours run out, all free services are suspended until next month. — (via search summary) [temps.sh Render 2026](https://temps.sh/blog/render-pricing-2026); [livemy Render](https://livemy.app/blog/render-pricing)

### Inferences
- **Recommendation tiers for the README:**
  1. "I have a spare Pi / always-on PC" → Docker Compose.
  2. "Free cloud VM" → Oracle A1 (convert to PAYG to stop idle reclaim, and set a $0 budget alert) or GCP e2-micro (us-central1/us-east1/us-west1, standard disk).
  3. "~€5/month, zero hassle" → Hetzner CAX11 or any $4–6 VPS.
  4. "No server at all" → Cloudflare Workers + D1 (webhook bot, cron tick every 5 min) or a GitHub Actions push-only mode (best-effort timing).
- **Oracle reclaim nuance:** reclaim needs CPU, network *and* memory (A1) all below 20%. A tiny bot on a 24 GB VM will be under 20% on all three. A right-sized A1 shape (e.g. 1 OCPU / 6 GB) still leaves memory under 20% for a ~100 MB bot, so **PAYG conversion is the reliable fix**. Busy-loop "keep-alive" scripts are commonly used but unofficial and against the spirit of the policy.
- **Render/Koyeb "keep-alive ping" hacks:** an external pinger hitting a free web service every <15 min (Render) is a common workaround. It's against the spirit of the tier, burns the 750 h pool (one service running 24/7 uses ~744 h), and any Render redeploy or cold start drops polling. Not recommended for a public project's docs.
- **GitHub Actions-only mode specifics:**
  - In a **public** repo it's free. A private repo running every 15 min (96 jobs/day × ≥1 min) ≈ 2,880 min/month, which **exceeds 2,000 free minutes**. Every 30 min (48/day) ≈ 1,440 min fits.
  - The 60-day inactivity disable hits public repos. A workflow that commits state back to the repo counts as activity, but whether bot or `GITHUB_TOKEN` commits count isn't documented (gap).
  - Forks of a public template are public by default, and self-hosters may not notice disabled workflows. Pair with healthchecks.io.
- **Raspberry Pi gotchas** (general experience, no source retrieved): SD-card wear from frequent SQLite writes (prefer SSD/USB or fewer writes), power and ISP outages (the catch-up policy and dead-man's switch matter), and arm64 images are required. Long polling needs only outbound HTTPS, so CGNAT and dynamic IPs don't matter.

### Gaps
- Couldn't open official pricing pages for Render, Fly, Railway, Koyeb, PythonAnywhere, Oracle or GCP (blocked). Every free-tier figure in those rows is from search-engine summaries dated 2025–2026 and must be re-verified before publishing.
- Oracle "out of host capacity" for A1 in popular regions is widely reported anecdotally, but I didn't retrieve a source.
- The Railway free-tier status in 2026 is unresolved: $1/mo credit vs trial-only.
- No source on whether GitHub counts bot-authored or `GITHUB_TOKEN` commits as "repository activity" for the 60-day rule.

## 6. Language/stack comparison (Python vs TypeScript/Node)

### Takeaway
**Python** has the most mature Canvas client (`canvasapi`, UCF, MIT, active in 2026) and two mature async Telegram frameworks. It also has APScheduler 3.x and `zoneinfo` in the stdlib. Its weak spots: `canvasapi` is synchronous (`requests`), and there is no single-binary story. **TypeScript** has grammY (excellent, runs on Node/Deno/Workers), croner, Temporal natively in Node 26, and is the only practical choice if you want the Cloudflare Workers mode. Its Canvas clients are thinner (`@kth/canvas-api` is the best). For a VPS/Docker-first, student-maintained project, **Python is the safer default**. Choose TS if serverless/Workers is the primary deployment target.

### Cited Findings
- `canvasapi`:
  - **3.6.0 (2026-04-16)**. Earlier releases: 3.5.0 (2026-03-12), 3.4.0 (2025-11-10), 3.3.0 (2024-08-27).
  - MIT licensed, maintained by `ucfopen` (University of Central Florida). Python 3.10–3.14.
  - Depends on `arrow`, `pytz`, `requests`, so it's synchronous.
  - Paginated endpoints return a lazily loaded `PaginatedList`.
  — [PyPI canvasapi](https://pypi.org/project/canvasapi/); [canvasapi README](https://github.com/ucfopen/canvasapi)
- `python-telegram-bot` 22.8 (2026-06-12) requires Python ≥3.10. JobQueue uses APScheduler 3.x (`<3.12`). — [PyPI python-telegram-bot](https://pypi.org/project/python-telegram-bot/)
- `aiogram` **3.31.0 (2026-08-26)** requires Python ≥3.10,<3.15. — [PyPI aiogram](https://pypi.org/project/aiogram/)
- `httpx` latest is 0.28.1 (2024-12-06), with no release in about 22 months as of this research. — [PyPI httpx](https://pypi.org/project/httpx/)
- `grammy` **1.46.0 (2026-08-26)**. Its docs cover Node, Deno, and serverless/webhook deployment. — [npm grammy](https://www.npmjs.com/package/grammy); [grammY hosting comparison](https://grammy.dev/hosting/comparison)
- TS/Node Canvas clients:
  - `@kth/canvas-api` **5.1.1 (2025-11-20)**: TypeScript-first, paginated iteration, SIS helpers.
  - `node-canvas-api` (UBC): ESM-only since 2.0, Node ≥20.
  - `canvas-api-ts` describes itself as early-stage, and `gesso` as "UNDER CONSTRUCTION".
  — [npm @kth/canvas-api](https://www.npmjs.com/package/@kth/canvas-api) (version/date from npm registry); [kth/canvas-api](https://github.com/kth/canvas-api); [ubc/node-canvas-api](https://github.com/ubc/node-canvas-api); [canvas-api-ts README](https://cdn.jsdelivr.net/npm/canvas-api-ts@0.6.1/README.md) (via search summary)
- Node schedulers: croner 10.0.1 (2026-02-01, zero deps, Node/Deno/Bun), node-cron 4.6.0 (2026-07-05). BullMQ needs Redis. — [npm croner](https://www.npmjs.com/package/croner); [node-cron](https://www.npmjs.com/package/node-cron); [BullMQ](https://github.com/taskforcesh/bullmq)
- Temporal is default-on in Node 26 (2026-05-05), with LTS slated for October 2026. — [Help Net Security](https://www.helpnetsecurity.com/2026/05/07/node-js-26-released/)
- Cloudflare's docs advise Zod ≥4.5.0 in Workers because earlier versions "use substantially more memory per schema" (relevant to the 128 MB isolate limit). — [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/)

### Inferences
- **Python stack (recommended default):**
  - Python 3.12/3.13, asyncio.
  - `aiogram` 3.x or `python-telegram-bot` 22.x (long polling).
  - A Canvas client: either `canvasapi` run in `asyncio.to_thread()`, or a thin custom `httpx.AsyncClient` wrapper over the few endpoints needed (planner/upcoming assignments + submissions). The custom wrapper avoids the pytz/arrow/requests dependency and gives you control over retries and `Link`-header pagination.
  - Pydantic v2 models for Canvas JSON plus `pydantic-settings` for env config.
  - `zoneinfo` + `tzdata`. SQLite via `sqlite3`/`aiosqlite` or SQLAlchemy + Alembic.
  - Either a tick loop or APScheduler 3.11.3+. Don't use the 4.0 alpha.
  - If using PTB's JobQueue, you're on APScheduler 3.x anyway.
- **TS stack:**
  - Node 24 LTS (or 26 once LTS), grammY, `@kth/canvas-api` or a fetch wrapper, Zod ≥4.5, croner (`protect:true`, `timezone`).
  - Temporal (native or polyfill), Drizzle + better-sqlite3 (VPS) or D1 (Workers).
  - The same core can target **both** Docker and Cloudflare Workers, which is TS's unique advantage.
- **Packaging for self-hosters:**
  - Both languages ship best as a Docker image. Python can't easily produce a single binary (PyInstaller/Nuitka add friction), while Node has Bun/Deno `compile` single-file executables (not researched here).
  - For non-Docker users, `pipx install`/`uvx` (Python) or `npx` (Node) are the simplest paths.
  - Whichever language you pick, keep Canvas I/O behind an interface so the tick logic is unit-testable with frozen time (freezegun/time-machine in Python, fake timers in JS). DST cases need tests.

### Gaps
- Didn't verify Bun/Deno single-binary maturity or Python packaging tools (uv/pipx) against official docs in this session.
- Didn't benchmark memory footprint (Python ~50–100 MB vs Node ~50–80 MB is folklore, not sourced).

## 7. Packaging & distribution for self-hosters

### Takeaway
Publish a **multi-arch (linux/amd64 + linux/arm64) Docker image to GHCR from GitHub Actions** (free for public repos). Ship a `docker-compose.yml` with a named volume for SQLite, a `.env.example` for configuration, `restart: unless-stopped`, a container `HEALTHCHECK`, and JSON logs to stdout. Make **healthchecks.io** (free tier, 20 checks) the documented dead-man's switch, pinged by the bot after each successful tick.

### Cited Findings
- Docker's GitHub Actions guide builds multi-platform images with `docker/setup-qemu-action` + `docker/setup-buildx-action` + `platforms: linux/amd64,linux/arm64`. It also documents splitting platforms across **multiple native runners** because QEMU emulation "can significantly extend build" time. — [Docker Docs: Multi-platform image with GitHub Actions](https://docs.docker.com/build/ci/github-actions/multi-platform/)
- GitHub-hosted **arm64 Linux runners** (`ubuntu-24.04-arm`, `ubuntu-22.04-arm`, `ubuntu-26.04-arm`) are listed among standard runners, which enables native arm64 builds without QEMU. — [GitHub Docs: GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- Standard GitHub-hosted runners are free in public repositories. — [GitHub Docs: Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- GHCR:
  - Publish with `${{ secrets.GITHUB_TOKEN }}`, which auto-links the package to the repo.
  - Docs recommend the `org.opencontainers.image.source` label, plus `org.opencontainers.image.description` (≤512 chars) and `org.opencontainers.image.licenses`.
  - Multi-arch images take their description via manifest annotations.
  — [GitHub Docs: Working with the Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- healthchecks.io:
  - Works as a "dead man's switch". It "listens for HTTP requests ('pings')", "keeps silent as long as pings arrive on time" and "raises an alert as soon as a ping does not arrive on time".
  - Checks support Period + Grace Time, or a cron expression with the server's time zone.
  - Start/success signals measure run time and fail if success doesn't arrive within Grace Time.
  — [healthchecks docs: introduction](https://healthchecks.io/docs/) (source: [templates/docs/introduction.md](https://github.com/healthchecks/healthchecks/blob/master/templates/docs/introduction.md)); [Configuring checks](https://healthchecks.io/docs/configuring_checks/)
- healthchecks.io pricing:
  - Free **Hobbyist** plan: up to **20 checks** and 3 team members.
  - Business $20/mo (100 checks), Business Plus $80/mo (1,000).
  - Business is free for open-source projects and nonprofits on request.
  — (via search summary) [healthchecks.io pricing](https://healthchecks.io/pricing/); [Capterra](https://www.capterra.com/p/249957/Healthchecksio/pricing/)
- healthchecks is open source and self-hostable (repo). — [github.com/healthchecks/healthchecks](https://github.com/healthchecks/healthchecks)

### Inferences
- **Release workflow:**
  - Trigger on tags `v*` + `main`.
  - `docker/metadata-action` for semver tags plus `latest`.
  - Either a build matrix on `ubuntu-latest` (amd64) and `ubuntu-24.04-arm` (arm64) merged with `docker buildx imagetools create`, or a single job with QEMU (simpler but slower).
  - `permissions: packages: write`. Optionally add SBOM/provenance (`provenance: true`, `sbom: true`) and cosign signing. Those are supply-chain items another researcher may cover.
- **Image:**
  - `python:3.13-slim` (or distroless) plus `tzdata`. Run as a non-root user.
  - `WORKDIR /app`, `VOLUME /data`, `ENV TZ` unused (use the per-user tz from config).
  - `HEALTHCHECK CMD python -m bot.healthcheck`. It reads `last_tick_at` from the DB and exits 1 if it's older than 3× the tick interval. It must not call Canvas.
- **Compose example:**
  - `services.bot: image: ghcr.io/<owner>/<repo>:latest`
  - `env_file: .env`, `volumes: [bot-data:/data]`, `restart: unless-stopped`
  - Logging driver `json-file` with `max-size: 10m`, `max-file: 3`, so the Pi's SD card doesn't fill.
  - Optionally Watchtower or a "pull + up -d" cron for updates. Watchtower's status in 2026 wasn't researched.
- **Config surface (`.env.example`):**
  - `CANVAS_BASE_URL`, `CANVAS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (or first-/start-claims-ownership), `TZ_NAME=America/New_York`
  - `DIGEST_HOUR=8`, `REMINDER_INTERVAL_HOURS=2`, `REMINDER_WINDOW_HOURS=24`, `SYNC_INTERVAL_MINUTES=15`
  - `HEALTHCHECKS_PING_URL`, `LOG_LEVEL`, `LOG_FORMAT=json`
  - Validate at startup (pydantic-settings / zod) and fail fast with a clear message.
  - Support `*_FILE` variants for Docker secrets.
- **Heartbeat semantics:**
  - Ping `HEALTHCHECKS_PING_URL` after each **successful** sync (period 15 min, grace 30–60 min).
  - Send `/fail` with the error body on Canvas 401 or repeated errors.
  - Optionally use a second check for "digest sent today" (cron `0 8 * * *` in the user's tz, grace 2 h).
  - The free 20 checks are enough for one user.
- **Structured logging:** Python `structlog` or stdlib `logging` with a JSON formatter. Node: `pino`. Log `tick_id`, `user_id`, `notification_key` and `canvas_request_cost`. **Never log tokens.**

### Gaps
- Didn't verify current Watchtower maintenance status or alternatives (e.g. Diun) in 2026.
- healthchecks.io pricing is from the official page as summarized by search, so exact limits (e.g. log retention, SMS credits) weren't confirmed.

## 8. Observability and resilience (retries, backoff, Canvas downtime, token expiry/401)

### Takeaway
Wrap every Canvas and Telegram call in **capped exponential backoff with full jitter**, honoring server hints (`Retry-After`, Canvas 429). Run Canvas requests **sequentially** (Canvas's throttle penalizes parallelism). Treat a **401 with a `WWW-Authenticate` header** as "token invalid/expired/revoked": stop polling, mark the token bad, and **tell the user via Telegram plus a healthchecks fail ping** instead of retrying forever. Never send "you have nothing due" when the real cause is a failed sync.

### Cited Findings
- Canvas throttling:
  - Each request has a cost deducted from a quota that refills over time. Throttled requests get "**`429 Forbidden (Rate Limit Exceeded)`**".
  - Every response carries `X-Request-Cost`. `X-Rate-Limit-Remaining` appears when throttling applies.
  - "any API client that makes no more than one simultaneous request" is unlikely to be throttled. Parallel requests incur a pre-flight penalty.
  - Each OAuth user token has its own quota.
  — [Canvas API: Throttling](https://canvas.instructure.com/doc/api/file.throttling.html) (source: [canvas-lms doc/api/throttling.md](https://github.com/instructure/canvas-lms/blob/master/doc/api/throttling.md))
- Canvas tokens and 401:
  - "the application will get a 401 Unauthorized error from the API" when a token is deleted or expired.
  - To distinguish an invalid token from a permission denial, check "that the WWW-Authenticate header is set".
  - OAuth access tokens "have a 1 hour lifespan" and refresh without a new refresh token.
  - Manually generated tokens are "password equivalent". The doc doesn't state an expiry for them.
  — [Canvas API: OAuth2](https://canvas.instructure.com/doc/api/file.oauth.html) (source: [canvas-lms doc/api/oauth.md](https://github.com/instructure/canvas-lms/blob/master/doc/api/oauth.md))
- **Canvas API policy:** "asking any other user to manually generate a token and enter it into your application is a violation of Canvas' API Policy". Apps used by multiple users must use OAuth. — [Canvas API: OAuth2](https://canvas.instructure.com/doc/api/file.oauth.html)
- Exponential backoff and jitter (AWS Architecture Blog, Marc Brooker; updated May 2023): capped exponential backoff alone still produces "clusters of calls", and adding jitter spreads them. Full jitter is `sleep = random(0, min(cap, base·2^attempt))`, a formula confirmed via secondary sources in this session. The AWS Well-Architected framework (REL05-BP03) likewise says to "control and limit retry calls". — [AWS Architecture Blog: Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/); [AWS Well-Architected REL05-BP03](https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_mitigate_interaction_failure_limit_retries.html) (via search summary)
- APScheduler 3.x had a bug where `AsyncIOScheduler` "permanently stop[ped] the processing of jobs" after an exception in `_process_jobs()` (fixed in unreleased 3.x). So a scheduler can die silently, which is why an external heartbeat matters. — [APScheduler 3.x versionhistory](https://github.com/agronholm/apscheduler/blob/3.x/docs/versionhistory.rst)
- Cloudflare Workers exceeding CPU/memory limits get Error 1102 "Worker exceeded resource limits". D1 over-limit errors return explicit messages and an email alert. — [Workers limits](https://developers.cloudflare.com/workers/platform/limits/); [D1 changelog](https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/)

### Inferences

**Error-handling matrix:**

| Condition | Action |
|---|---|
| Canvas 429 / 403 throttle, 5xx, timeouts, DNS/connect errors | Retry with full jitter (base 1–2 s, cap 60 s, max 5 attempts). Then mark the sync failed and leave the next tick to retry. Keep requests sequential. Log `X-Request-Cost` |
| Canvas down for a long time (e.g. maintenance) | **Circuit breaker:** after N consecutive failed syncs, back off to e.g. a 30-min sync interval. Keep sending reminders from the **last known DB state**, flagged with "data may be stale (last synced HH:MM)". After >X hours, send one alert. Never send an "all clear" digest from stale or failed data |
| Canvas 401 with `WWW-Authenticate` | Set `token_status='invalid'` and stop Canvas calls. Send one Telegram alert ("Your Canvas token was rejected; generate a new one at …/profile/settings and run /token or update .env"). Send `healthchecks /fail`. Re-check every few hours, or on `/retry` |
| Canvas 401/403 without `WWW-Authenticate` (permission) | Skip that course or endpoint, log it, carry on |
| Telegram 429 / 5xx | Honor `retry_after` and back off. Leave notification rows `pending` for the next tick (at-least-once) |
| Telegram 403 "bot was blocked by the user" | Mark the user inactive and stop sending (behavior not verified in this session) |
| Unhandled exception in a tick | Catch at the tick boundary, log with stack, and continue the loop. Never let one assignment's error kill the loop. The heartbeat will alert if ticks stop |

- **Defense in depth:**
  1. In-process try/except per tick.
  2. Container `restart: unless-stopped` plus HEALTHCHECK.
  3. External dead-man's switch (healthchecks.io). This catches a dead host, a dead Docker daemon or a revoked token, which the bot can't report itself.
  4. An optional weekly "I'm alive" line in the digest.
- **Token expiry:** students' manually generated tokens can have an expiry date set at creation, and some institutions restrict or expire user tokens (general knowledge, **not verified** here). Store and surface `expires_at` if the API exposes it, and warn N days ahead.
- **Multi-tenant implication:** a hosted service for many students **must use OAuth2 developer keys** issued by each institution's Canvas admin. Manual tokens from other users violate Canvas API policy. Self-hosting sidesteps this because each student enters *their own* token into *their own* instance. This is a strong argument for the self-host-first design. With OAuth, quotas are per user token, which helps scaling, but 1-hour access tokens require refresh-token storage and rotation logic.

### Gaps
- Didn't retrieve the Telegram Bot API docs for exact 429 `retry_after` and "blocked by user" error semantics. That's likely covered by another researcher.
- Didn't confirm how Canvas exposes token expiry for user-generated tokens, or institution policies on token lifetimes.
- No source found for a Canvas status/maintenance API. Instructure status pages exist, but weren't checked.
