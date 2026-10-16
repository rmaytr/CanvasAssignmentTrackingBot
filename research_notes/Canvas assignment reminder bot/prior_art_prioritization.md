# Prior Art and Prioritization for a Canvas Assignment Reminder Bot

Research date: 2026-10-16. GitHub metadata (stars, forks, open issues, created and last-push dates) came from the GitHub search API on that date. Method note: the proxy blocked direct fetches of community.canvaslms.com, canvas.screenstepslive.com, canvas.instructure.com, docs.github.com and the Chrome Web Store. Claims sourced from those sites rely on search-engine result summaries and are marked "(via search summary)". Where possible, Canvas behaviour was checked against Instructure's open-source `canvas-lms` code on GitHub, which is a primary source.

---

## 1. Canvas built-in features (Notification Preferences, Student app reminders, Planner / To Do) and why students find them insufficient

### Takeaway
Canvas web notifications have no "assignment is due soon" reminder. The "Due Date" notification fires when a due date is created or changed, and many schools set it to a weekly summary by default. The only built-in pre-deadline reminder is a manual, per-assignment, per-device reminder in the Canvas Student mobile app. It is not prioritized, not batched, and does not repeat until you submit. The To Do list and Planner APIs do expose submission status and "mark complete" overrides, which a bot can use to detect what is done.

### Cited Findings
**Notification Preferences**
- Each notification type can be delivered as "Notify immediately", "Daily Summary", "Weekly Summary" or "Notifications Off". Course-level settings override account-level ones. — [Yale Canvas help](https://help.canvas.yale.edu/a/1290439-modifying-your-canvas-course-notification-settings); [Indiana University KB](https://www.kb.indiana.edu/d/bfdl) (via search summary)
- The "Due Date" notification covers "Assignment due date change" ([Yale](https://help.canvas.yale.edu/a/914669-how-do-i-modify-the-default-notification-settings)). FSU's list says it also fires when an assignment, quiz or discussion is created, and when a non-graded assignment becomes graded ([FSU Canvas support](https://support.canvas.fsu.edu/kb/article/923)). (via search summary)
- Several schools default "Due Date" to weekly: Indiana lists "Due date | Weekly" ([IU](https://www.kb.indiana.edu/d/bfdl)) and SJSU lists "Due Dates | Emailed weekly" ([SJSU](https://gcp-web.sjsu.edu/cfeti/software/canvas/student-resources/canvas-notifications-default-settings.php)). Canvas can hold immediate notices for up to an hour, and holds Due Date about 5 minutes so that further instructor edits don't trigger extra messages. (via search summary)
- Canvas sends notifications only when due dates change, not when they approach. The Idea Conversation "[Notifications] Automatic due date reminder notifications" (posted 2018, still open for voting) asks for a reminder 24 hours before a quiz or assignment is due, sent to students who haven't submitted. A 2025-era forum answer says automatic reminders are "not a current function of Canvas". — [Canvas Idea](https://community.canvaslms.com/t5/Canvas-Ideas/Notifications-Automatic-due-date-reminder-notifications/idc-p/488024); [Forum: Notifications for Upcoming Assignment Deadlines](https://community.canvaslms.com/t5/Canvas-Question-Forum/Canvas-Notifications-for-Upcoming-Assignment-Deadlines/m-p/643716) (via search summary)
- Instructor workarounds are manual: messaging non-submitters from SpeedGrader or the Gradebook, or scheduling a delayed Announcement. Some third-party tools, including one from a Canvas partner, send reminders. — [Canvas Idea thread](https://community.canvaslms.com/t5/Canvas-Ideas/Notifications-Automatic-due-date-reminder-notifications/idc-p/535467) (via search summary)
- Push notifications in the Student app can only be "right away or not at all"; daily and weekly summaries are not supported for push. A 2021 Canvas post said push would support only a narrowed list of types (e.g., New Announcement, Announcement Reply, Assignment Created). — [Streamlining Canvas Push Notifications](https://community.canvaslms.com/t5/The-Product-Blog/Streamlining-Canvas-Push-Notifications/bc-p/426145); [UPenn guide](https://infocanvas.upenn.edu/guides/canvas-for-students/canvas-profiles-for-students/notification-preferences-for-students/); [MIT Sloan EdTech](https://mitsloanedtech.mit.edu/2021/07/11/canvas-update-push-notifications/) (via search summary; the 2021 list may be out of date)
- Instructure's own product blog reported that 50% of students "don't always read emails from academic departments", and that overload "ultimately leads us to ignoring all messages on a device". — [Streamlining Canvas Push Notifications](https://community.canvaslms.com/t5/The-Product-Blog/Streamlining-Canvas-Push-Notifications/bc-p/426145) (via search summary)

**Canvas Student app assignment reminders**
- Students can add a reminder from an assignment or quiz details page ("Add Reminder"), and it arrives as a push notification. Presets are 5, 15 or 30 minutes, 1 hour, 1 day or 1 week before the due date, plus a custom value. Only one reminder per preset type is allowed, up to a maximum of 10 per assignment. Reminders are device-specific, need iOS notification permission, can be deleted with a trash icon, and overdue reminders don't display. The feature arrived in Canvas Student 7.2. — [Canvas Guide (Android)](https://canvas.screenstepslive.com/m/18555/l/1786419-how-do-i-create-a-reminder-for-an-assignment-or-quiz-in-the-canvas-student-app-on-my-android-device); [Canvas Student Release Notes iOS 7.2](https://community.canvaslms.com/t5/Canvas-Mobile-Releases/Canvas-Student-Release-Notes-iOS-7-2/ta-p/598232); [Tacoma CC KB](https://tacomacc.teamdynamix.com/TDClient/1903/Portal/KB/Article/34382/How-do-I-schedule-a-reminder-for-an-assignment-on-my-iPhone) (via search summary; Tacoma lists a different preset set: 5 min / 1 h / 1 day / 3 days)

**To Do list / Planner (UI and API, from canvas-lms source)**
- In the UI, checking an item's box marks it complete. Non-graded items generally have to be checked by hand, and completed items stay viewable via "Show completed items". — [Canvas Community: List View To Do](https://community.canvaslms.com/docs/DOC-15243-4212947391) (via search summary). A University of Minnesota guide says the course-home To Do list shows items due in the next 7 days. — [UMN CCAPS](https://ccaps.umn.edu/academic-technology-and-design/instructors/tutorials-course-activities/due-and-do-dates)
- Known issue LX-3310 (documented 2025-09-15, open): students with more than 50 completed items in the past two weeks see "Nothing for now" in the Card View To Do list even when they have unfinished work. Canvas says there is no workaround. — [Canvas Known Issues](https://community.canvaslms.com/t5/Known-Issues/OPEN-Students-with-more-than-50-completed-items-in-the-past-two/m-p/656708) (via search summary)
- `GET /api/v1/users/self/todo` ("List the TODO items") returns `submitting` items. It supports `include[]=ungraded_quizzes`, and the docs say "There is a limit to the number of items returned". Each item has `ignore` and `ignore_permanently` URLs for hiding it. — [canvas-lms users_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/users_controller.rb)
- The To Do "submitting" scope defaults to `due_after: 4.weeks.ago` and `due_before: 1.week.from_now` and is cached for 15 minutes. Ungraded quizzes default to due between now and 1 week ahead, with `ULOS_DEFAULT_LIMIT = 15`. — [canvas-lms user_learning_object_scopes.rb](https://github.com/instructure/canvas-lms/blob/master/app/models/user_learning_object_scopes.rb)
- `GET /api/v1/planner/items` accepts `start_date`, `end_date`, `context_codes[]` and `filter` (`new_activity`, `incomplete_items`, `complete_items`). `incomplete_items` "excludes items with planner_override.marked_complete = true or submitted assignments". Items carry `plannable_type` (assignment, quiz, discussion_topic, planner_note, …), `html_url`, a `planner_override` (`marked_complete`, `dismissed`) and a `submissions` object (`excused`, `graded`, `late`, `missing`, `needs_grading`, `with_feedback`). Students can create `planner_note` items with a `todo_date`. — [canvas-lms planner_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/planner_controller.rb)
- `GET /api/v1/users/:user_id/missing_submissions` returns past-due assignments with no submission, with `filter[]=submittable` (drop locked items) and `filter[]=current_grading_period`. — [canvas-lms users_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/users_controller.rb)
- The Assignments API supports `bucket` = past, overdue, undated, ungraded, unsubmitted, upcoming or future, and exposes `points_possible`, `submission_types`, `omit_from_final_grade`, among others. Assignment groups expose `group_weight`, and courses expose `apply_assignment_group_weights`. — [assignments_api_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/assignments_api_controller.rb); [assignment_groups_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/assignment_groups_controller.rb); [courses_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/courses_controller.rb)

**Calendar feed (iCal)**
- Google Calendar can take up to 24 hours to refresh a subscribed Canvas calendar feed. — [Canvas Idea: Dynamically Sync with Google](https://community.canvaslms.com/t5/Canvas-Ideas/Calendar-Dynamically-Sync-the-Canvas-Calendar-with-Google/idi-p/591194) (via search summary)
- The ICS feed "has no submission state, grades, points, availability windows… It cannot tell whether an assignment is complete or submitted." — [aaroncchung/ICS-Canvas-Notion-Sync README](https://github.com/aaroncchung/ICS-Canvas-Notion-Sync). This conflicts with [DEVLlN/canvas-todoist-sync](https://github.com/DEVLlN/canvas-todoist-sync), which claims a submitted assignment "disappears from your calendar feed" and uses that to auto-complete tasks. Unresolved; the claim needs testing.

**Token access**
- Canvas added an account-level checkbox that stops student-only accounts from generating personal access tokens; it was extended to observers in the 2025-11-05 release. The older "Admin Manage Access Tokens" option was removed (2025-09-10 deploy notes). — [Deploy Notes 2025-09-10](https://community.canvaslms.com/t5/Canvas-Releases/Canvas-Deploy-Notes-2025-09-10/ta-p/654577); [Deploy Notes 2025-11-05](https://community.canvaslms.com/t5/Canvas-Releases/Canvas-Deploy-Notes-2025-11-05/ta-p/661038) (via search summary)
- Ohio State: as of August 2026 instructors regained token creation, but "students will still not be able to generate personal access tokens". — [OSU IT news](https://it.osu.edu/news/2026/08/11/carmencanvas-personal-access-tokens). Other schools use request processes or token policies. — [BYU-I](https://td.byui.edu/TDClient/79/ITHelpCenter/KB/Article/18367/Canvas-API-Token-Request-Process); [UM System](https://tdx.umsystem.edu/TDClient/66/MOOnline/KB/ArticleDet?ID=2193)

### Inferences
- The new bot's core value (an automatic, prioritized daily digest plus repeated reminders that stop on submission) is exactly the gap described in the long-open 2018 Canvas Idea. Canvas offers nothing similar natively.
- The Planner API (`filter=incomplete_items` plus the `submissions` object plus `planner_override.marked_complete`) is a better source than `/users/self/todo`. The To Do endpoint has a capped item count, a fixed 1-week look-ahead and a 15-minute cache, all of which make it unsuitable for a 14-day digest or prompt submission detection.
- Because the To Do scope is cached for 15 minutes, "stop reminding after submission" can lag by up to that long unless the bot also checks the specific submission (inferred from the `cache_timeout` in source).
- Token restrictions at some schools mean the bot should support an ICS-only fallback mode (dates only, manual "mark done"). It should also handle token revocation or expiry gracefully.

### Gaps
- I could not confirm whether Canvas still offers SMS as a notification channel in 2026 (the official notifications PDF and community pages were unreachable).
- I could not confirm whether Student app reminders are cancelled automatically after submission.
- I could not get the current vote count or status on the 2018 Idea, or an official complete list of push-supported notification types for 2026.

---

## 2. Open-source projects (Canvas → Telegram / Discord / WhatsApp / SMS / Todoist / Notion / Google Calendar)

### Takeaway
The OSS landscape is large but fragmented. Most projects are single-school or hackathon repos with 0 to 5 stars, many archived or idle. The most-starred sync tools (Todoist script ~50★, Notion extension 47★ and 19k+ users, Chalmers calendar sync 59★) sync tasks rather than send reminders. No surveyed project combines all of: a prioritized daily digest, repeated reminders inside the final 24 hours that stop on submission, manual done/snooze, and quiet hours.

### Cited Findings
Survey table (metadata from the GitHub API, 2026-10-16; features from each README):

| Repo | Lang | ★ / forks / open issues | Created → last push | Data access | Channel | Notable features | Known problems |
|---|---|---|---|---|---|---|---|
| [scottquach/Canvas-Assignments-Transfer-For-Todoist](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist) | Python | 50 / 25 / 7 | 2018-04 → 2024-05-17 (idle) | API token | Todoist | Projects per course, due-date update rules (only moves dates earlier), filters for ungraded, locked and unsubmittable items | README: duplicate tasks when an assignment is renamed; ignores graded items (a "0" grade hides it); doesn't handle resubmissions. Issues: [#36 No Quizzes](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist/issues?q=is%3Aissue), #34 100-item pagination limit, #37 courses past 100, #16 external-tool assignments, #18 locked, #12 due-date changes not synced, #19 "BROKEN AS OF NOV 2022", #40 Todoist 410 error, #54 Todoist API v1 deprecation, #55 sync error (open, Mar 2026) — [issue list](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist/issues?q=is%3Aissue) |
| [JamesNZL/notion-assignment-import](https://github.com/JamesNZL/notion-assignment-import) | TypeScript | 47 / 6 / 9 | 2022-02 → 2024-12-14 | Browser extension; content script reads the signed-in Canvas tab | Notion | "19k+ unique users", no duplicates, updates changed assignments, Chromium/Firefox/Safari | README "Wrong Timezone" section: offsets are applied at copy time, so a fix needs Clear and re-copy; [#252 time-zone validation mismatch](https://github.com/JamesNZL/notion-assignment-import/issues/252) |
| [marigarey/canvas-notion-integration](https://github.com/marigarey/canvas-notion-integration) | JavaScript | 25 / 10 / 7 | 2024-06 → 2026-10-14 (active) | API token | Notion | Docker images | README: "you will have to run the script every time there is a change in Canvas" (no scheduler) |
| [xieyanran/chalmers-calendar-sync](https://github.com/xieyanran/chalmers-calendar-sync) | Python | 59 / 1 / 0 | 2026-08 → 2026-09-23 | Canvas ICS + TimeEdit ICS | Google Calendar | Runs every 4 h on GitHub Actions, dry-run mode, dedicated calendar | Google OAuth refresh token expires after about 6 months of inactivity; Google disables service-account keys by default (README) |
| [mctantwerp/Canvas-LMS-Discord-BOT](https://github.com/mctantwerp/Canvas-LMS-Discord-BOT) | JavaScript | 4 / 1 / 0 | 2024-09 → 2025-01-14 (idle) | API token + SQL DB | Discord (channel per course) | Posts new assignments and announcements; reminders at 7, 3 and 1 day; slash commands for upcoming work | Needs admin bot permissions and a DB |
| [mctantwerp/Canvas-Student-Announcement-Discord-Bot](https://github.com/mctantwerp/Canvas-Student-Announcement-Discord-Bot) | JavaScript | 28 / 11 / 11 | 2020-12 → 2023-03 (archived) | API token | Discord | Announcements only | Archived |
| [jnarezo/canvas-discord-bot](https://github.com/jnarezo/canvas-discord-bot) ("Atelier") | JavaScript | 2 / 3 / 8 | 2020-07 → 2022-08 (archived) | API token (self-host) or institution approval | Discord | Community reminders and subscriptions | README: a reminder due while the bot was offline "will NOT be sent at all" |
| [shodievSA/canvas-deadline-notifier](https://github.com/shodievSA/canvas-deadline-notifier) | JavaScript | 2 / 0 / 0 | 2024-03 → 2025-02-24 (idle) | API token (user pastes it into the bot) | Telegram | Choice of 6, 12 or 24 h before deadline; daily "today's deadlines" summary; daily token-expiry check and prompt to update | Single lead time only; needs Postgres + Redis |
| [kaveengoswami-sketch/canvas-sync](https://github.com/kaveengoswami-sketch/canvas-sync) | Python | 0 / 0 / 0 | 2026-06 → 2026-06-29 | API tokens (multi-school) | Todoist + ntfy push | Tracks discussion posts and owed replies; push the day before and the day of; grade-posted alerts; token-expiry pushes at 14/7/3/1 days; 14-day look-ahead, 7-day overdue window; runs 3×/day | README: GitHub cron is UTC-only, so a utc_offset must be set by hand (DST pitfalls) |
| [DEVLlN/canvas-todoist-sync](https://github.com/DEVLlN/canvas-todoist-sync) | Python | 0 / 0 / 0 | → 2026-05-21 | ICS feed | Todoist | Priority by due date (P1 ≤1 day, P2 ≤3 days, P3 ≤7 days); reminder 1 day before; dedupe by Canvas ID; runs every 5 minutes | Submission detection relies on items vanishing from the ICS feed (disputed, see §1); README has a "Duplicate Tasks" troubleshooting section |
| [aaroncchung/ICS-Canvas-Notion-Sync](https://github.com/aaroncchung/ICS-Canvas-Notion-Sync) | TypeScript | 0 / 0 / 2 | 2026-07 → 2026-10-16 (active) | ICS ("for institutions that do not permit students to create Canvas API tokens") + optional Chrome companion that uses the Canvas session to mark items Done | Notion | Never overwrites user-owned Status, Priority or Override Due Date; assignment-type inference; quarantines duplicate UIDs; guarded removal logic | README: GitHub disables scheduled workflows in public repos after 60 days without a commit, so it uses a private runner repo; ICS has no submission state |
| [rrong12/canvas-todoist-public](https://github.com/rrong12/canvas-todoist-public) | Python | 0 / 0 / 0 | 2026-09 → 2026-09-26 | ICS | Todoist + weekly email (Resend) | Weekly overview Sunday after 17:00 Chicago with Monday catch-up; includes overdue work; idempotent email retries; preserves personal planning dates | ICS "cannot prove that no work is assigned and do[es] not provide submission status" |
| [yashk812/lbs-canvas-telegram-agent](https://github.com/yashk812/lbs-canvas-telegram-agent) | Python | 0 / 0 / 0 | 2026-08 → 2026-10-01 | API token + school ICS | Telegram | Morning and evening brief (6 am and 6 pm); statuses `submitted` / `OVERDUE` / `due today 14:00` / `in 3d`; 🔴🟠🟢 markers; "Bigger assignments are flagged earlier"; runs free on GitHub Actions | Single-school (LBS) |
| [Zab-17/ical-whatsapp-reminder-](https://github.com/Zab-17/ical-whatsapp-reminder-) | Python | 1 / 0 / 0 | 2026-03 → 2026-03-26 | Description says iCal, but the README shows Playwright login with cached session cookies (2FA) | WhatsApp (Meta Cloud API) | Fixed reminders at 10, 13, 17 and 21 h (Cairo); change detection every 3 h; "mark items as done" | README: "When cookies expire, re-run auth_setup" |
| [AlirezaRazmahang1/smart-assignment-assistant](https://github.com/AlirezaRazmahang1/smart-assignment-assistant) | n8n JSON | 0 / 0 / 0 | 2026-05 | API token | Telegram | Gemini LLM assigns HIGH (≤3 d) / MEDIUM (4–7 d) / LOW (8+ d) and estimates hours by type (essays 3–8 h, coding 4–10 h, readings 1–3 h, quizzes 1–2 h); daily 24 h alert | Priority depends on an LLM (not deterministic) |
| [deeedaniel/studybuddy](https://github.com/deeedaniel/studybuddy) | TypeScript | 3 / 0 / 0 | 2025-09 | Canvas (details not verified; README not retrievable) | SMS | Daily SMS reminders; won 1st place at SJSU SCE Hacks | — |
| [Chris-Kau/CanvasBot](https://github.com/Chris-Kau/CanvasBot) | Python | 0 / 2 / 0 | 2024-04 (hackathon, abandoned) | Canvas API | Discord | To-do list with check-off; reminders for work due within 3 days | — |

Adjacent projects worth knowing about:
- [DMontgomery40/mcp-canvas-lms](https://github.com/DMontgomery40/mcp-canvas-lms) (104★, an MCP server with 54 tools) and [X-isdoingreat/canvas-pilot](https://github.com/X-isdoingreat/canvas-pilot) (125★, a local-first Canvas AI agent) are AI/agent tooling.
- [perslev/CanvasSync](https://github.com/perslev/CanvasSync) (96★) syncs files.
- [Ducksss/canvas-calendar-sync](https://github.com/Ducksss/canvas-calendar-sync) is a macOS launchd daily sync to Google Calendar.
- [khokharzain/canvas-dates](https://github.com/khokharzain/canvas-dates) is a menu-bar tracker that uses "grade weightings".

All of these come from GitHub search, 2026-10-16.

### Inferences
- Data-access methods split three ways:
  - API token: the richest option, with submission state, points and weights, but it is blocked at some schools.
  - ICS feed: works everywhere, but has no submission or points data and lags.
  - Session or cookie scraping: fragile, breaks with 2FA and cookie expiry.

  The new bot can differentiate by supporting token mode as the primary path and ICS as a degraded fallback.
- Reminder cadences in prior art are fixed lead times (7/3/1 days; 6/12/24 h; day-before and day-of; one reminder 1 day before) or fixed clock times. None of the surveyed projects nags repeatedly until submission inside the last 24 h, so this is a differentiator.
- Only two projects attempt deterministic prioritization: DEVLlN (due-date buckets) and yashk812 ("bigger assignments flagged earlier"). Only khokharzain/canvas-dates mentions grade weightings. Using `group_weight` and `points_possible` is largely unexplored in OSS.
- Free GitHub Actions hosting is popular but brings UTC-only cron, the 60-day disable rule, and possible delays (see §6). A bot that sends 2-hourly reminders needs a reliable scheduler.

### Gaps
- Issue trackers for the small bots are mostly empty, so failure data for reminder bots specifically is thin. Most failure evidence comes from the sync tools (Todoist, Notion) and the browser extensions.
- I could not read the README for studybuddy (no README at the root) or confirm its data-access method.
- GitHub search may miss repos that lack "canvas" in the name or description, for example those named only after a school.

---

## 3. Commercial and third-party apps for students

### Takeaway
The most widely used tools are browser extensions: Better Canvas (~1M Chrome users) and Tasks for Canvas, which have now merged into "CanvasU". They improve the in-Canvas To Do view but only work while the browser is open on Canvas. Planner apps either need manual entry (MyStudyLife, Power Planner) or are paid AI planners whose Canvas sync claims are vendor-written (Shovel, DormWay, Coursicle, Tivity). No official Todoist–Canvas integration was found.

### Cited Findings
- **Better Canvas** (ksucpea; repo now [UseBetterCanvas/bettercanvas](https://github.com/UseBetterCanvas/bettercanvas), 254★, 286 forks, 92 open issues). Features include a "Better todo list", an "Assignments due list", a "Browser wide popup assignment reminder", a GPA calculator, dashboard grades and dark mode. — [README](https://github.com/UseBetterCanvas/bettercanvas). The Chrome listing shows about 1,000,000 users and 5.0 stars from 7.2K ratings. — [Chrome Web Store](https://chrome.google.com/webstore/detail/better-canvas/cndibmoanboadcifjkjbdpjgfedanolh?hl=en) (via search summary)
- **Tasks for Canvas** (Jeff Cheng) features:
  - A sidebar grouping work by due date, per-course weekly progress bars, manual mark-done (x button), a completed list showing grading status, custom tasks, and filtering by course. v1.4.0, January 2025. — [Firefox Add-ons](https://addons.mozilla.org/en-US/firefox/addon/tasks-for-canvas/); [firefox-stats](https://firefox-stats.com/d/tasks-for-canvas) (via search summary)
  - The "Unfinished" list shows assignments that are "both unsubmitted and ungraded or have a grade of 0", and the sidebar works only in Card View and Recent Activity. — [README](https://github.com/jtcheng26/canvas-task-extension)
  - A school guide notes that checking a task off does not submit it, and graded work drops off. — [Georgia Cyber support](https://support.georgiacyber.org/hc/en-us/articles/19566194966423-Tasks-for-Canvas-Chrome-Browser-Extension)
  - The repo now resolves to UseBetterCanvas/canvas-task-extension (10★, 463 commits, MIT). — [GitHub](https://github.com/jtcheng26/canvas-task-extension)
  - Open feature requests that show unmet needs: #149 "Feature: Task Priority", #108 "Reminders section and Exams and quiz countdown", #175 "Option to see 2 weeks out", #151 "how many assignments to show", #156 "Allow hiding of specific classes", #142 "Gradescope late submission dates". — [Issues](https://github.com/jtcheng26/canvas-task-extension/issues?q=is%3Aissue); [page 2](https://github.com/jtcheng26/canvas-task-extension/issues?page=2&q=is%3Aissue)
- **CanvasU** (Tinkly LLC, ~Jan 2026) merges BetterCanvas and Tasks for Canvas. Adoption is tiny so far: 83 Chrome users per a third-party aggregator, and 12–23 Firefox users. — [Chromeboard](https://chromeboard.com/extension/canvasu-cejbaalbcgimpkfcebigabdojfldlglp); [Firefox Add-ons](https://addons.mozilla.org/firefox/addon/canvasu/) (via search summary)
- **Power+** is a separate extension that adds a dashboard of assignments due today, upcoming work, announcements, a calendar and recent grades. — [Chrome Web Store](https://chrome.google.com/webstore/detail/power+/pakgdifknldaiglefmpkkgfjndemfapo?hl=en-US) (via search summary)
- **Notion Assignment Import**: a free extension with "19k+ unique users". — [GitHub](https://github.com/JamesNZL/notion-assignment-import)
- **Todoist**: no official Canvas integration found. Options are third-party scripts, an iCal → Google Calendar → IFTTT chain that needed manual tagging, and ETL vendors. — [naleo fork of Canvas→Todoist](https://github.com/naleo/canvas-assignments-transfer-for-todoist); [Automators forum](https://talk.automators.fm/t/a-starter-task-automation-for-students-using-lms-gcal-ifttt-and-todoist/2287); [Acho](https://acho.io/integrations/connect/Canvas/Todoist) (via search summary)
- **MyStudyLife**: a free cross-device student planner; its sync is between its own devices, and no Canvas integration was documented. — [Warwick Library](https://warwick.ac.uk/services/library/using/productivity-tools/my-study-life) (via search summary)
- **Power Planner**: automatic homework reminders and GPA tracking, with Windows and Google Calendar integration but no evidence of Canvas import. A competitor groups MyStudyLife, myHomework and Power Planner as "manual entry". — [Microsoft Store](https://apps.microsoft.com/detail/9WZDNCRFJ25V); [DormWay blog (competitor, biased)](https://dormway.app/blog/best-free-student-planner-apps-2026) (via search summary)
- **Shovel**: a paid time-blocking planner. It imports coursework, estimates study time per task, uses a "Time Cushion" to show whether you have enough free time, and supports drag-and-drop timeboxing. Setup must happen on a computer. Competitors quote $9.79/mo or $35/yr; it is free to Purdue students. LMS coverage claims vary (Purdue: Brightspace; competitors: Canvas, Brightspace, Moodle and Classroom, ~24 h sync). — [Purdue overview](https://purdue.edu/teaching-learning/programs/sst/assets/Shovel%20-%20Overview.pdf); [DormWay vs Shovel (biased)](https://dormway.app/blog/dormway-vs-shovel); [Coursicle vs Shovel (biased)](https://www.coursicle.com/blog/shovel-vs-coursicle/) (via search summary)
- **Coursicle** claims Canvas, Classroom, Brightspace, Blackboard and Moodle sync into tasks and reminders. **Tivity** (Macmillan Learning, iPhone only) supports "only Canvas LMS". **TaskSync** claims Canvas and Google Calendar import. **DormWay** claims read-only Canvas, Blackboard and Moodle sync. — [Coursicle blog](https://www.coursicle.com/blog/best-free-assignment-tracker/); [Tivity App Store](https://apps.apple.com/us/app/-/id6737785246); [TaskSync](https://mwm.ai/apps/tasksync-ai-voice-to-do/6758976174); [DormWay](https://dormway.app/blog/best-apps-that-sync-with-canvas-lms-2026) (vendor-written; via search summary)

### Inferences
- The extensions cannot push reminders when the browser is closed, and they live inside Canvas, where students already experience overload. A chat-channel bot (Telegram, Discord or similar) that pushes a digest fills a different niche.
- The most-requested features in the popular extension (task priority, reminders and exam countdown, longer look-ahead, hiding courses) map directly onto the new bot's scope.
- Paid planners compete on effort estimation and time-blocking (Shovel's Time Cushion). A free bot can borrow a lightweight version: per-type default effort, user-overridable, plus a "start by" time.

### Gaps
- I could not get current Chrome Web Store user counts or ratings for Tasks for Canvas, or verify the CanvasU numbers first-hand (Chrome Web Store unreachable).
- I could not independently verify the Canvas-sync claims of Shovel, Coursicle, TaskSync or DormWay. Most comparisons are written by competitors.

---

## 4. Prioritization approaches, research on reminders and procrastination, and a recommended scoring formula

### Takeaway
The evidence supports three design choices: batched, well-timed reminders rather than constant pings; prompts that turn intentions into concrete plans; and a simple, explainable priority that combines urgency (time to due), importance (share of final grade), and effort or slack. Reminder RCTs in education show mixed effects, so the bot should not over-promise, and it should guard against notification fatigue.

### Cited Findings
**Prioritization frameworks**
- Eisenhower matrix quadrants: Do (urgent and important), Schedule or Decide (important, not urgent), Delegate (urgent, not important), Delete (neither). The four-quadrant form was popularized by Stephen Covey. — [Asana](https://asana.com/resources/eisenhower-matrix); [Training Industry](https://trainingindustry.com/articles/strategy-alignment-and-planning/what-is-the-eisenhower-matrix-and-how-can-it-help-with-time-management/)
- WSJF = Cost of Delay / Job Size. SAFe computes Cost of Delay as the sum of business value, time criticality and risk reduction, each scored on a relative scale such as 1–10. The model originated with Reinertsen. — [ProductPlan](https://www.productplan.com/glossary/weighted-shortest-job-first); [SAFe WSJF (archived)](https://webarchive.library.unt.edu/web/20161225132214mp_/http://www.scaledagileframework.com/wsjf)
- Temporal Motivation Theory (Steel 2007, *Psychological Bulletin* 133(1):65–94, 691 correlations) models utility roughly as Expectancy × Value / (Impulsiveness-like sensitivity × Delay). Task aversiveness, task delay, self-efficacy, impulsiveness and conscientiousness facets are the strongest predictors of procrastination. — [Steel 2007 (U Calgary)](https://prism.ucalgary.ca/handle/1880/47914); [ScienceDaily summary](https://www.sciencedaily.com/releases/2007/01/070110090851.htm)
- Procrastination correlates with lower academic performance. Kim & Seo (2015) report a weighted mean r ≈ −.13 (33 studies, 38,529 participants), stronger for objective performance measures. — [Secondary citations summarized in IJEM meta-analysis page](https://ijem.com/the-effect-of-procrastination-on-academic-achievement-a-meta-analysis-study) (figure not verified against the original)
- Simple deterministic schemes in prior art include:
  - Due-date buckets mapped to Todoist P1 (≤1 day), P2 (≤3 days) and P3 (≤7 days). — [DEVLlN/canvas-todoist-sync](https://github.com/DEVLlN/canvas-todoist-sync)
  - An LLM-prompted HIGH ≤3 d / MEDIUM 4–7 d / LOW 8+ d scheme with per-type hour estimates. — [AlirezaRazmahang1/smart-assignment-assistant](https://github.com/AlirezaRazmahang1/smart-assignment-assistant)
  - "Bigger assignments are flagged earlier". — [yashk812/lbs-canvas-telegram-agent](https://github.com/yashk812/lbs-canvas-telegram-agent)
  - Effort-aware planning: Shovel's "Time Cushion". — [Purdue overview](https://purdue.edu/teaching-learning/programs/sst/assets/Shovel%20-%20Overview.pdf)

**Reminders, nudges, notification fatigue**
- Implementation intentions (if-then plans) have a medium-to-large effect on goal attainment: d = 0.65 across 94 tests (Gollwitzer & Sheeran 2006). A later 642-test meta-analysis found d = .27–.66, larger when plans were in if-then format, motivation was high, and plans were rehearsed. — [Gollwitzer & Sheeran (Konstanz repository)](https://kops.uni-konstanz.de/signposting/describedby/cf394f1f-49d8-4256-bf24-df7af124514a); [summary of 642-test review](https://goalsandprogress.com/implementation-intentions-research/) (secondary blog; verify before citing)
- Patterson (2018, *JEBO*; 657 MOOC students): a commitment device raised course time by 24%, grades by 0.29 SD and completion by 40% (11 pp). A "reminder" tool (an on-screen alert when browsing distracting sites) and a site-blocking "focusing" tool were not distinguishable from control. — [Cornell eCommons](https://ecommons.cornell.edu/entities/publication/0ccc8fbd-c323-4536-b4a3-dd587b4f643c); [working paper](https://archive.ilr.cornell.edu/sites/default/files/cheri_wp165_0.pdf)
- Text-message nudges in higher education give mixed results:
  - A randomized Norwegian math-course study found no effect on problem-set submission or exam performance. — [NIKT/NTNU](https://www.ntnu.no/ojs/index.php/nikt/article/view/5714)
  - A two-section marketing course comparison associated opt-in text reminders with more on-time submissions (not randomized). — [Journal of Marketing Education](https://https-sage-cnpereading-com-443.webvpn1.xju.edu.cn/doi/10.1177/0273475319836271)
  - WGU's "Boost" app trial was too small to conclude (41 survey respondents). — [WGU Labs](https://wgulabs.org/posts/research-brief-boost-nudging-report)
  - A commentator notes that texting effects may fade with repetition, and that SMS can cost students on prepaid plans. — [Inside Higher Ed](https://www.insidehighered.com/blogs/confessions-community-college-dean/nudges-and-parable-email)
- Repeated reminders keep working while they are sent: in Calzolari & Nardotto (2017, *Management Science*), weekly gym reminders produced an "immediate (within hours) and recurrent" response to every reminder, explained by limited attention, with smaller post-treatment habit effects. — [DIW summary](https://www.diw.de/de/diw_01.c.533841.de/publikationen/externe_referierte_aufsaetze/2017_0009/effective_reminders.html); [CEPR DP8571](https://repec.cepr.org/repec/cpr/ceprdp/DP8571.pdf). A replication (~2,500 members) found significant during- and post-period effects. — [Experimental Economics](https://link.springer.com/article/10.1007/s10683-020-09693-5)
- Batching helps; hourly does not. In Fitz et al. (2019, *Computers in Human Behavior*; 237 participants), notifications batched three times a day made people feel more attentive, productive, in better mood and in more control, with lower stress. Hourly batching showed little change versus control, and no notifications at all raised anxiety and FoMO. — [Duke Scholars](https://scholars.duke.edu/publication/1402953); [Springer Nature community post](https://communities.springernature.com/posts/batching-notifications-can-improve-attention-well-being-and-productivity)
- Competition for attention: people receive about 63.5 notifications per day (Pielot et al. 2014, n = 15), with a median of 56 per day in a 278-user, 795k-notification dataset (Pielot et al. 2018). People click promptly when the sender or content seems important, urgent or useful (Mehrotra et al., as cited). — [Pielot 2014 PDF](https://ic.unicamp.br/~oliveira/doc/MHCI2014_An-in-situ-study-of-mobile-phone-notifications.pdf); [Pielot 2018 PDF](https://www.interruptions.net/literature/Pielot-MobileHCI18.pdf); [arXiv 1712.07120](https://arxiv.org/pdf/1712.07120)
- Timing: in an Australian tax field experiment, earlier reminders sped up payment without changing the eventual payment rate. — [Austaxpolicy / TTPI](https://www.austaxpolicy.com/nudging-businesses-pay-taxes-timing-matter/). In a charitable-task experiment, one-week and no-deadline conditions produced many early responses, while a one-month deadline "seemed to give people permission to procrastinate". — [IZA DP 11599](https://docs.iza.org/dp11599.pdf)
- Students tune out mass messages: almost a quarter of students say they receive too many emails (Middlesex survey), and messages from course instructors are more welcome than generic ones. — [Sussex TEL blog](https://blogs.sussex.ac.uk/tel/2023/05/02/tips-to-avoid-death-by-announcement); [Times Higher Education](https://timeshighereducation.com/news/students-feel-spammed-overload-university-emails)

### Inferences — recommended transparent scoring formula
The guiding idea is to rank by urgency × importance with an effort-based slack check, in the spirit of TMT (value / delay) and WSJF (cost of delay / size). The formula uses additive points so that every digest line can explain itself.

**Canvas data that feeds it**
- **Due time**: `plannable_date` or `due_at`, from Planner items or Assignments.
- **Status**:
  - `submissions.submitted`, `excused`, `graded`, `missing` and `late`, plus `planner_override.marked_complete`, from the Planner API.
  - Past-due unsubmitted work from `missing_submissions?filter[]=submittable`.
  - `lock_at` for whether late work is still accepted.
- **Importance**:
  - `points_possible`, `omit_from_final_grade`, and the assignment group's `group_weight` when the course has `apply_assignment_group_weights = true`.
  - Otherwise, points as a share of the course's total graded points.
  - `submission_types` (`online_quiz`, `discussion_topic`, `external_tool`, `on_paper`, `none`) and title keywords (exam, midterm, final, project, essay, reading).
- **Effort** (optional): per-type defaults, which the user can override.
- **Course grade risk** (optional, phase 2): current course score from enrollments. Add points when the course is near a grade boundary.

**Computation**
1. `hours_left = due_at − now`.
2. Estimated share of final grade:
   - In weighted courses: `w% = group_weight × points_possible / Σ points_possible(group, excluding omit_from_final_grade)`.
   - Otherwise: `w% = points_possible / Σ points_possible(course) × 100`.
   - If unknown, show "weight unknown" and use the type default.
3. `effort_h`: user value, or the default (discussion 1, quiz 1, reading 1, homework 2, lab 3, essay or project 6, exam prep 8). `slack_h = hours_left − 1.5 × effort_h`.
4. Points:
   - **Urgency U (0–50)**: overdue but still accepting = 50; ≤24 h = 45; ≤48 h = 35; ≤72 h = 25; ≤7 d = 12; >7 d = 4.
   - **Importance I (0–35)**: w ≥ 15% → 35; ≥ 8% → 28; ≥ 4% → 20; ≥ 1.5% → 12; > 0 → 6; ungraded or 0 points → 2. Add +5 for exam or major keywords (cap 35).
   - **Effort pressure E (0–15)**: slack ≤ 0 → 15; ≤ 24 h → 10; ≤ 72 h → 5; else 0.
   - **Score** = U + I + E (0–100).
5. Tiers. Rules are applied first, then score:
   - **URGENT**: not done and due within 24 h, or overdue and still accepting submissions. Only this tier gets reminders every 2 hours.
   - **HIGH**: score ≥ 55, or (due ≤ 72 h and w ≥ 8%), or (due ≤ 7 d and w ≥ 10%), or slack ≤ 24 h.
   - **MEDIUM**: score 30–54.
   - **LOW**: score < 30.
   - Within a tier, sort by `due_at` ascending, then score descending.
6. Explanation line per item. Example: "URGENT · due in 5 h 20 m (Tue 11:59 PM) · ≈12% of grade · quiz · est. 1 h". For HIGH items, add "start by Mon 6 PM" (derived from slack).

**Rationale, cadence and caveats**
- Additive points with rule-based tiers are easier to explain than an LLM or a multiplicative TMT score. Prior art that delegated priority to an LLM (AlirezaRazmahang1) loses determinism and testability.
- Earliest-deadline ordering within a tier matches students' mental model. Deadline-first rules are a standard scheduling-theory heuristic for minimizing lateness (general knowledge; not re-verified in this research).
- Pure WSJF (divide by effort) would push quick trivial tasks above big, heavily weighted work. For a student digest, use effort only as a slack check, not as a divisor.
- Cadence implications from the evidence:
  - An 8 AM daily digest is a batch, consistent with Fitz et al.'s three-batches-a-day benefit.
  - Reminders every 2 hours apply only to URGENT items, and every URGENT item should be combined into one message per cycle so the bot never sends one message per assignment. That cadence is close to the hourly batching that showed no benefit, so add quiet hours and a snooze to limit fatigue. Because Calzolari and Nardotto saw responses repeat with every reminder, repetition can still work near the deadline.
  - Add an implementation-intention prompt to HIGH items ("When will you start? Reply 'tonight 8pm'"), since if-then plans have medium-to-large effects. Patterson suggests a self-set commitment, such as "I'll submit by", may help more than passive alerts.

### Gaps
- I found no study that tests reminders every 2 hours within the final 24 hours for coursework, and no direct comparison of reminders one day versus one week before an academic deadline.
- I found no published evaluation of how a priority score (points, weight, effort) affects student outcomes. The formula's thresholds are design choices that need tuning with real users.
- I could not verify the Kim & Seo effect size or the 642-test implementation-intentions figures against the original papers (secondary sources only).

---

## 5. UX ideas from prior art worth adopting

### Takeaway
Adopt:
- Manual "mark done" and custom tasks.
- Course grouping and color, with human-readable time left plus an absolute local time.
- Overdue and missing sections, and links back to Canvas.
- Configurable lead times, a weekly overview, token-expiry warnings, and respect for user overrides.

Snooze and quiet hours were largely absent from the OSS surveyed, so they are clear differentiators.

### Cited Findings
- **Manual mark-done for items Canvas can't detect**:
  - Tasks for Canvas has an "x" button and a completed list. — [Firefox Add-ons](https://addons.mozilla.org/en-US/firefox/addon/tasks-for-canvas/)
  - The Canvas Planner checkbox and `planner_override.marked_complete` are readable and writable via the API. — [planner_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/planner_controller.rb)
  - The WhatsApp bot offers "mark items as done". — [Zab-17](https://github.com/Zab-17/ical-whatsapp-reminder-)
  - The Discord hackathon bot lets users check off items. — [Chris-Kau/CanvasBot](https://github.com/Chris-Kau/CanvasBot)
  - Canvas `submission_types` includes `on_paper`, `none` and `external_tool`, which signal items whose submission Canvas may not see. — [assignments_api_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/assignments_api_controller.rb)
- **Custom tasks**: Tasks for Canvas offers custom task creation. — [firefox-stats](https://firefox-stats.com/d/tasks-for-canvas). Canvas planner notes (`planner_note` with `todo_date`) can carry them. — [planner_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/planner_controller.rb)
- **Grouping by course**:
  - Todoist projects per course. — [scottquach](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist)
  - Labels per course. — [DEVLlN](https://github.com/DEVLlN/canvas-todoist-sync)
  - A Discord channel per course. — [mctantwerp](https://github.com/mctantwerp/Canvas-LMS-Discord-BOT)
  - Per-course weekly progress bars using dashboard colors. — [Tasks for Canvas README](https://github.com/jtcheng26/canvas-task-extension)
- **Human time remaining plus status icons**: "🔴 … OVERDUE — was due 08:15", "🟠 … due tomorrow 12:00", "🟢 … due Wed 16:00 · in 3d · Major". — [yashk812](https://github.com/yashk812/lbs-canvas-telegram-agent)
- **Configurable lead time**:
  - 6, 12 or 24 h. — [shodievSA](https://github.com/shodievSA/canvas-deadline-notifier)
  - 7, 3 and 1 day. — [mctantwerp](https://github.com/mctantwerp/Canvas-LMS-Discord-BOT)
  - Presets from 5 minutes to 1 week, a custom value, max 10 per assignment. — [Canvas Guide](https://canvas.screenstepslive.com/m/18555/l/1786419-how-do-i-create-a-reminder-for-an-assignment-or-quiz-in-the-canvas-student-app-on-my-android-device) (via search summary)
- **Daily, twice-daily and weekly digests**:
  - "Today's deadlines" daily summary. — [shodievSA](https://github.com/shodievSA/canvas-deadline-notifier)
  - Morning and evening brief. — [yashk812](https://github.com/yashk812/lbs-canvas-telegram-agent)
  - Sunday weekly overview with Monday catch-up, including overdue work. — [rrong12](https://github.com/rrong12/canvas-todoist-public)
- **Overdue and missing**: a recent-overdue window of 7 days. — [kaveengoswami](https://github.com/kaveengoswami-sketch/canvas-sync). Canvas `missing_submissions` endpoint. — [users_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/users_controller.rb). Users asked for "Show Overdue Tasks" (#109) and reported "Show old overdue assignments not working" (#152). — [Tasks for Canvas issues](https://github.com/jtcheng26/canvas-task-extension/issues?q=is%3Aissue)
- **Discussion nuance**: track whether the student still owes a reply, not only the initial post. — [kaveengoswami](https://github.com/kaveengoswami-sketch/canvas-sync)
- **Change detection**: alerts when new assignments, quizzes or modules appear, checked every 3 h. — [Zab-17](https://github.com/Zab-17/ical-whatsapp-reminder-). The Canvas "Due Date" notification exists precisely for due-date changes. — [FSU](https://support.canvas.fsu.edu/kb/article/923) (via search summary)
- **Respect user overrides**:
  - Never overwrite personal Status, Priority, Notes or Override Due Date. — [aaroncchung](https://github.com/aaroncchung/ICS-Canvas-Notion-Sync)
  - Keep personal planning dates. — [rrong12](https://github.com/rrong12/canvas-todoist-public)
  - Allow moving dates earlier but never later. — [scottquach](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist)
- **Token-expiry warnings**: a daily check with a prompt to update. — [shodievSA](https://github.com/shodievSA/canvas-deadline-notifier). Pushes at 14, 7, 3 and 1 days. — [kaveengoswami](https://github.com/kaveengoswami-sketch/canvas-sync)
- **Grade-posted alerts** as a secondary feature. — [kaveengoswami](https://github.com/kaveengoswami-sketch/canvas-sync)
- **Course filtering**: ignore lists and name patterns (e.g., "Orientation", "Advising"). — [kaveengoswami](https://github.com/kaveengoswami-sketch/canvas-sync). Users asked to "Allow hiding of specific classes" (#156). — [Tasks for Canvas issues](https://github.com/jtcheng26/canvas-task-extension/issues?q=is%3Aissue)
- **Links back to Canvas**: Planner and To Do items include `html_url`. — [planner_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/planner_controller.rb)
- **Batching** (three times a day) beats constant or hourly notifications. — [Fitz et al. 2019](https://scholars.duke.edu/publication/1402953)

### Inferences
- **Recommended digest layout**:
  - Header: counts by tier.
  - Sections: URGENT, then HIGH, then MEDIUM and LOW (collapsed), then Overdue/Missing, then "Done yesterday" for positive feedback.
  - Each line: course tag, title (linked to `html_url`), human time left plus absolute local time, ≈% of grade, type icon, and a reason chip.
  - Buttons: Done, Snooze 2 h / until tonight / tomorrow, Not mine / hide course, "Plan start time".
- **Reminder messages**: one consolidated message per 2-hour cycle listing all URGENT items. Escalate the wording at T−6 h and T−2 h. Before quiet hours begin, send a final "due overnight" warning for anything due during them.
- **Weekly overview**: send one on Sunday evening, following rrong12's pattern. It is low-noise and helps students plan big, distant items, which reduces the long-deadline procrastination effect seen in the IZA study.
- **Snooze, quiet hours, per-item reminder opt-out and a reminder count cap** were not found in any surveyed OSS bot. Adding them differentiates the bot and addresses fatigue.

### Gaps
- I found no user research on preferred snooze lengths or quiet-hour defaults for students specifically.

---

## 6. Common failure modes reported by users of similar tools

### Takeaway
The recurring failures are:
- Auth breakage: tokens expiring or being blocked, cookies expiring, OAuth refresh tokens going stale.
- Missing item types: quizzes, external-tool and ungraded items, or anything past the first 100 because of pagination.
- Duplicates when items are renamed or the sync state is lost.
- Time-zone and DST errors.
- Stale data from ICS lag and API caching.
- Scheduler unreliability: GitHub Actions cron delays and the 60-day disable rule, plus bots that skip reminders missed while offline.
- Reminders or lists that are wrong about submission state: graded-as-0 items hidden, resubmissions ignored, and the Canvas To Do known issue.

### Cited Findings
- **Token and credential expiry**:
  - Bots add explicit token-expiry checks and warnings. — [shodievSA](https://github.com/shodievSA/canvas-deadline-notifier); [kaveengoswami](https://github.com/kaveengoswami-sketch/canvas-sync)
  - Cookie-based scraping needs manual re-auth "when cookies expire". — [Zab-17](https://github.com/Zab-17/ical-whatsapp-reminder-)
  - Google OAuth refresh tokens expire after about 6 months of inactivity. — [chalmers-calendar-sync](https://github.com/xieyanran/chalmers-calendar-sync)
  - Schools can block student tokens entirely. — [Canvas Deploy Notes 2025-09-10](https://community.canvaslms.com/t5/Canvas-Releases/Canvas-Deploy-Notes-2025-09-10/ta-p/654577) (via search summary); [OSU](https://it.osu.edu/news/2026/08/11/carmencanvas-personal-access-tokens)
- **Missing item types and pagination**: "No Quizzes" (#36), "No Pagination – 100 item limit" (#34), "Does not display courses past 100" (#37), "External Tool Submission Assignments" (#16), "Locked assignments" (#18), "Not gradeable assignments" (#17). — [scottquach issues](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist/issues?q=is%3Aissue). The Canvas To Do API includes ungraded quizzes only with `include[]=ungraded_quizzes` and limits the number of items. — [users_controller.rb](https://github.com/instructure/canvas-lms/blob/master/app/controllers/users_controller.rb)
- **Duplicates**: renamed assignments create a second task. — [scottquach README](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist). One project's README has a "Duplicate Tasks" troubleshooting section for lost cached state. — [DEVLlN](https://github.com/DEVLlN/canvas-todoist-sync). Another quarantines duplicate ICS UIDs and has guarded removal logic. — [aaroncchung](https://github.com/aaroncchung/ICS-Canvas-Notion-Sync)
- **Time zones and DST**:
  - "Wrong Timezone" troubleshooting; offsets are applied at copy time. — [JamesNZL README](https://github.com/JamesNZL/notion-assignment-import); [#252](https://github.com/JamesNZL/notion-assignment-import/issues/252)
  - GitHub cron is UTC-only, so users must set a UTC offset by hand. — [kaveengoswami](https://github.com/kaveengoswami-sketch/canvas-sync)
  - Hard-coded zones appear in prior art: America/Chicago ([rrong12](https://github.com/rrong12/canvas-todoist-public)), Cairo time ([Zab-17](https://github.com/Zab-17/ical-whatsapp-reminder-)), America/Los_Angeles ([aaroncchung](https://github.com/aaroncchung/ICS-Canvas-Notion-Sync)).
- **Due-date change handling**: "Due date changes not synced" (#12) and "Fix updating due dates" (#23). — [scottquach issues](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist/issues?q=is%3Aissue). One tool needs manual re-runs to pick up changes. — [marigarey](https://github.com/marigarey/canvas-notion-integration)
- **Submission-state errors**:
  - A tool ignores items once graded, so a "0" hides work that can still be submitted, and resubmissions show as already submitted. — [scottquach README](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist)
  - Tasks for Canvas treats "grade of 0" items as unfinished. — [README](https://github.com/jtcheng26/canvas-task-extension)
  - ICS feeds carry no submission state. — [aaroncchung](https://github.com/aaroncchung/ICS-Canvas-Notion-Sync)
  - Canvas caches the To Do "submitting" scope for 15 minutes. — [user_learning_object_scopes.rb](https://github.com/instructure/canvas-lms/blob/master/app/models/user_learning_object_scopes.rb)
  - Canvas Known Issue LX-3310: students with more than 50 completed items see an empty To Do. — [Canvas Known Issues](https://community.canvaslms.com/t5/Known-Issues/OPEN-Students-with-more-than-50-completed-items-in-the-past-two/m-p/656708) (via search summary)
- **Look-ahead and window bugs**: "End of the month unable to see upcoming assignments" (#153) and "Show old overdue assignments not working" (#152). — [Tasks for Canvas issues](https://github.com/jtcheng26/canvas-task-extension/issues?q=is%3Aissue)
- **Third-party API churn**: "Does not support Todoist API v1 – will stop working" (#54), "Todoist API requests don't send, 410 error" (#40), "BROKEN AS OF NOV 2022" (#19). — [scottquach issues](https://github.com/scottquach/Canvas-Assignments-Transfer-For-Todoist/issues?q=is%3Aissue). Firefox packaging broke the layout (#178). — [Tasks for Canvas issues](https://github.com/jtcheng26/canvas-task-extension/issues?q=is%3Aissue)
- **Scheduler reliability**:
  - GitHub disables scheduled workflows in public repos after 60 days without a commit. — [aaroncchung README](https://github.com/aaroncchung/ICS-Canvas-Notion-Sync)
  - Scheduled runs can be delayed (reports of ~15–30 min, worst at the top of the hour) or dropped under load. — [runhooks blog](https://runhooks.app/blog/github-actions-scheduled-workflows-unreliable/); [GitHub community discussion #185355](https://github.com/orgs/community/discussions/185355) (secondary; official docs unreachable)
  - A reminder that should have fired while the bot was offline "will NOT be sent at all". — [jnarezo/Atelier](https://github.com/jnarezo/canvas-discord-bot)
- **Calendar-feed lag**: Google Calendar may take up to 24 h to refresh the Canvas feed. — [Canvas Idea](https://community.canvaslms.com/t5/Canvas-Ideas/Calendar-Dynamically-Sync-the-Canvas-Calendar-with-Google/idi-p/591194) (via search summary)
- **Over-notification and channel abandonment**: students mark Canvas messages as spam or ignore them. — [Canvas Idea: Don't have all Notifications on by Default](https://community.canvaslms.com/t5/Canvas-Ideas/Notifications-Don-t-have-all-Notifications-on-by-Default/m-p/582485); [Instructure blog](https://community.canvaslms.com/t5/The-Product-Blog/Streamlining-Canvas-Push-Notifications/bc-p/426145) (via search summary)

### Inferences
- **Mitigations to build in from day one**:
  - Paginate every Canvas call by following Link headers.
  - Include quizzes, graded discussions and ungraded quizzes explicitly.
  - Key items by stable Canvas IDs (`plannable_type` + `plannable_id`), not titles.
  - Store every time in UTC, render in the user's IANA time zone (taken from the Canvas profile or set by the user), and test DST transitions.
  - Before each reminder, re-check that specific item's submission and override state, so the bot never nags about work that is already submitted.
  - Treat "graded 0 but still open" and "resubmission allowed" as not done.
  - Make reminders idempotent: record a sent-log per (item, reminder slot) to prevent duplicates after restarts.
  - On startup, send a single catch-up for missed slots instead of dropping them or spamming them all.
  - Detect 401 errors (token revoked or expired) and DM the user immediately.
  - Use a real scheduler or an always-on process instead of public-repo GitHub Actions cron if 2-hour reminders must be dependable.

### Gaps
- I found no quantitative data on how often these failures occur. The evidence is anecdotal, from issues and READMEs.
- I could not confirm GitHub's official current wording on schedule delays and time-zone support (docs.github.com unreachable). One secondary source claims a per-schedule `timezone:` field was added in March 2026, which I could not verify.
