# Canvas LMS data access for a student-run assignment reminder bot (state as of Oct 2026)

> **Method note for the report writer.** `canvas.instructure.com/doc/api/*`, `developerdocs.instructure.com`, `community.instructure.com`, `instructure.com` and the university sites could not be fetched from this research environment (DNS/proxy refusal). Instead, every API behavior below was checked against the **open-source canvas-lms `master` branch as of 2026-10-16**, downloaded from raw.githubusercontent.com. The rendered REST docs at canvas.instructure.com/doc/api are generated from the `@API`/`@argument` comment blocks in these same controller files, so the doc text quoted here is the source of those pages. Instructure-hosted production can differ from `master` because of feature flags and deploy timing. Where only WebSearch summaries were available (policy pages, community posts, university pages), the claim is cited to that URL and marked as coming from search snippets. Canonical rendered-doc URLs, for readers: planner https://canvas.instructure.com/doc/api/planner.html, users https://canvas.instructure.com/doc/api/users.html, assignments https://canvas.instructure.com/doc/api/assignments.html, submissions https://canvas.instructure.com/doc/api/submissions.html, throttling https://canvas.instructure.com/doc/api/file.throttling.html, OAuth https://canvas.instructure.com/doc/api/file.oauth.html, pagination https://canvas.instructure.com/doc/api/file.pagination.html, GraphQL https://canvas.instructure.com/doc/api/file.graphql.html. Instructure has also moved its docs to https://developerdocs.instructure.com/services/canvas (seen in search results).

## 1. REST endpoints for a student's to-do: what each returns, how each represents "submitted/complete", and which one matches the UI

### Takeaway
`GET /api/v1/planner/items` is the right primary source. The Canvas UI's own student To Do sidebar calls it (`filter=incomplete_items`, `order=asc`, `start_date=now-2 weeks`, `per_page=14`). It also carries per-item submission status (`submissions.submitted/excused/graded/late/missing/...`) and the `planner_override.marked_complete` flag. Treat `/users/self/todo`, `/users/self/upcoming_events` and `/users/:id/missing_submissions` as narrower legacy or auxiliary views. They have hard-coded time windows and item caps. Pull `/courses/:id/assignments?include[]=submission` for full metadata: points, assignment group, submission types, undated items.

### Cited Findings

**Which endpoint the UI uses**
- The Canvas planner/To Do sidebar front-end loads its items with `GET /api/v1/planner/items` and params `{start_date: currentMoment - 2 weeks, order: 'asc', filter: 'incomplete_items', per_page: 14}`. In a course view it adds `context_codes=[course_<id>, user_<self>]`, and it follows the `next` link for more. — [canvas-lms ui/shared/planner/actions/sidebar-actions.js](https://raw.githubusercontent.com/instructure/canvas-lms/master/ui/shared/planner/actions/sidebar-actions.js)
- The server-side dashboard sidebar code skips legacy upcoming-events preparation for students. The code comment says, "it's not even using any of this for students/observers observing students - it's just using planner now". — [canvas-lms app/controllers/users_controller.rb (dashboard_sidebar)](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/users_controller.rb)

**`GET /api/v1/planner/items` (also `GET /api/v1/users/:user_id/planner/items`)**
- Routes: `get "planner/items"` and `get "users/:user_id/planner/items"`. Overrides are at `GET/POST /api/v1/planner/overrides` and `GET/PUT/DELETE /api/v1/planner/overrides/:id`. Notes are at `GET/POST /api/v1/planner_notes` and `GET/PUT/DELETE /api/v1/planner_notes/:id`. — [canvas-lms config/routes.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/config/routes.rb)
- Doc text: "Retrieve the paginated list of objects to be shown on the planner for the current user with the associated planner override to override an item's visibility if set." Arguments are `start_date`, `end_date` ("yyyy-mm-dd or ISO 8601 YYYY-MM-DDTHH:MM:SSZ"), `context_codes[]` (e.g. `course_42`, `group_123`; defaults to all of the user's contexts; "concluded courses will be ignored unless specified in the includes[] parameter"), `observed_user_id`, and `filter`. — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- Documented `filter` values: `new_activity` ("items that have new or unread activity"), `incomplete_items` ("excludes items with planner_override.marked_complete = true or submitted assignments"), and `complete_items` ("includes items with planner_override.marked_complete = true or submitted assignments"). The code also accepts undocumented `ungraded_todo_items` (pages plus ungraded discussions) and `all_ungraded_todo_items` (the only filter that allows unauthenticated public-syllabus access). — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- Default window: if neither `start_date` nor `end_date` is given, the range is `2.weeks.ago.beginning_of_day` to `2.weeks.from_now.beginning_of_day`. If only one is given, the other defaults to 10 years ago or 10 years ahead. `per_page` defaults to 50. `include[]=concluded` adds concluded courses and `include[]=all_courses` is for observers. `order=desc` is supported. — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- Collections merged into one sorted stream: assignments, ungraded quizzes, planner notes, wiki pages with to-do dates, ungraded discussions with to-do dates, calendar events, peer reviews (AssessmentRequests), discussion-checkpoint sub-assignments, and peer-review sub-assignments. Locked items are included (`include_locked: true`), and items the user "ignored" in the old To Do are included (`include_ignored: true`). — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- `plannable_type` values map to `discussion_topic`, `announcement`, `quiz`, `assignment`, `wiki_page`, `planner_note`, `calendar_event`, `assessment_request`, `sub_assignment`, `peer_review_sub_assignment`. — [canvas-lms lib/planner_helper.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/planner_helper.rb)
- Item JSON keys: context data (`context_type`, `course_id`, ...), `plannable_id`, `planner_override`, `plannable_type`, `new_activity`, `submissions`, `plannable_date`, `plannable`, `html_url`, `context_name`, `context_image`. `plannable` is a whitelisted subset: `id, title, course_id, location_name, todo_date, details, url, unread_count, read_state, created_at, updated_at`, plus `assignment_id, points_possible, due_at` for gradables, `start_at/end_at/all_day/...` for calendar events, and `workflow_state` for assessment requests. The per-user due date (`user_due_date`) is exposed as `due_at`. — [canvas-lms lib/api/v1/planner_item.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/api/v1/planner_item.rb)
- `submissions` is `false` for non-gradable items. Otherwise it is a hash: `submitted` (= `submission.has_submission?`, i.e. `submission_type` non-null), `excused`, `graded`, `posted_at`, `late`, `missing`, `needs_grading`, `has_feedback`, `redo_request`, and `feedback` (when there is a teacher comment). The doc example's older names (`with_feedback`) don't match the code (`has_feedback`); trust the live response. — [planner_item.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/api/v1/planner_item.rb); [planner_controller.rb doc example](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- `plannable_date` per type: Assignment/Quiz use `cached_due_date || user_due_date || due_at` (the student-specific due date after overrides). DiscussionTopic uses `cached_due_date || todo_date || posted_at || created_at`. WikiPage and PlannerNote use `todo_date || created_at`. CalendarEvent uses `start_at`. Announcement uses `posted_at`. AssessmentRequest (peer review) uses `assignment.peer_reviews_due_at || assessor_asset.cached_due_date`. — [planner_item.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/api/v1/planner_item.rb)
- How "complete" is computed (`lib/plannable.rb` code comment): an item is complete if "(1) It has a PlannerOverride with marked_complete: true, OR (2) For Assignments/SubAssignments: it has a submission (submitted_at present) AND (no redo_request OR redo_request is false) AND (no PlannerOverride OR PlannerOverride.marked_complete is not explicitly false)…". Also, "PlannerOverride.marked_complete: false … can override submission status, allowing users to mark submitted assignments as incomplete". — [canvas-lms lib/plannable.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/plannable.rb)
- When a student submits (workflow_state changes to `submitted`, or an auto-graded quiz goes from `unsubmitted` to `graded`), Canvas sets `marked_complete: true` on an *existing* planner override for that item. It uses `find_by`, so it does not create one. — [canvas-lms app/models/submission.rb (update_planner_override)](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/submission.rb); [planner_helper.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/planner_helper.rb)
- Ungraded surveys are submitted as a `Quizzes::QuizSubmission` with no real Submission. For these, Canvas uses `find_or_create_by` on a quiz planner override and marks it complete. — [planner_helper.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/planner_helper.rb)
- Server caching: the planner response is cached for 1 week. The key is built from a per-user planner meta key, the page, the filter, an options digest, context codes, and `contexts_cache_key`, which is the latest `updated_at` across the user's courses, groups, user and accounts. It also uses `stale?(etag: ...)`, so conditional GETs (`If-None-Match`) can return 304. The meta key is cleared when overrides or notes change and when submission read-state changes. — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb); [planner_helper.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/planner_helper.rb); [submission.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/submission.rb); [context.rb last_updated_at](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/context.rb)
- Saving a Submission runs an `after_save :touch_user` callback. Saving an Assignment runs `touch_context` and `touch_assignment_group`. — [submission.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/submission.rb); [abstract_assignment.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb)

**Planner overrides ("mark as done") and planner notes**
- PlannerOverride model fields: `id`, `plannable_type`, `plannable_id`, `user_id`, `assignment_id`, `workflow_state`, `marked_complete` ("Controls whether or not the associated plannable item is marked complete on the planner"), `dismissed` ("shows up in the opportunities list"), and `created_at`/`updated_at`/`deleted_at`. Create takes `plannable_type` (required; one of announcement, assignment, discussion_topic, quiz, wiki_page, planner_note, calendar_event, assessment_request, sub_assignment, peer_review_sub_assignment), `plannable_id` (required), and the optional `marked_complete` and `dismissed`. Update takes `marked_complete` and `dismissed`. — [canvas-lms app/controllers/planner_overrides_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_overrides_controller.rb)
- Planner notes (student-created personal to-dos): list with `start_date`, `end_date`, `context_codes[]`. Create or update with `title`, `details`, `todo_date`, `course_id`, and on create `linked_object_type`/`linked_object_id`. — [canvas-lms app/controllers/planner_notes_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_notes_controller.rb)

**`GET /api/v1/users/self/todo` (legacy dashboard To Do)**
- Doc: "A paginated list of the current user's list of todo items." `include[]` accepts `ungraded_quizzes` (returned under a `quiz` key) and `grading_counts` (teachers). `course_ids[]` is also accepted. "There is a limit to the number of items returned." Each item has `type` (`grading` | `submitting`), `assignment` or `quiz`, `ignore`, `ignore_permanently`, `html_url`, `context_type`, `course_id`. A `DELETE` on `ignore` hides the item "until the item changes", and `ignore_permanently` hides it forever. — [users_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/users_controller.rb)
- What "submitting" means in code. `assignments_needing_submitting` defaults to `due_after: 4.weeks.ago, due_before: 1.week.from_now`, cached for 15 minutes. It excludes assignments where the user has a submission (`submission_type IS NOT NULL OR excused = true`). It keeps only `submittable` types, or anything whose `cached_due_date > now`. It excludes locked (`not_locked`) and suppressed assignments, and drops items the user ignored. The underlying `assignments_for_student` default `limit` is `ULOS_DEFAULT_LIMIT = 15`. — [canvas-lms app/models/user_learning_object_scopes.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/user_learning_object_scopes.rb); [abstract_assignment.rb (need_submitting_info, submittable, not_locked)](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb)
- `submittable` excludes `OFFLINE_SUBMISSION_TYPES = on_paper, external_tool, none, not_graded, wiki_page, peer_review`. — [abstract_assignment.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb)
- Ungraded quizzes in `/todo` are limited to due between now and 1 week from now. — [user_learning_object_scopes.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/user_learning_object_scopes.rb)
- `GET /api/v1/users/self/todo_item_count` "will only look at the first 100 todo items… The largest reliable number for both counts is 100." — [users_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/users_controller.rb)

**`GET /api/v1/users/self/upcoming_events`**
- Doc: "A paginated list of the current user's upcoming events." In code it returns calendar events plus published assignments due between now and `1.week.from_now`, with `limit` defaulting to 20. It is cached for 3 minutes per user (`cached_user_upcoming_events`) and rendered without `Api.paginate`. Assignment entries look like `{"id":"assignment_9729", ..., "assignment":{...}}`. — [users_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/users_controller.rb); [canvas-lms app/models/user.rb (upcoming_events, select_upcoming_assignments)](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/user.rb)

**`GET /api/v1/users/:user_id/missing_submissions` (use `self`)**
- Doc: "A paginated list of past-due assignments for which the student does not have a submission." Args: `include[]` = `planner_overrides` | `course`; `filter[]` = `submittable` (exclude locked) | `current_grading_period`; `course_ids[]`; `observed_user_id`. Returns `[Assignment]` ordered by `cached_due_date`. In code it uses `Submission.missing` on published assignments and excludes `late_policy_status = 'none'`. — [users_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/users_controller.rb)
- The `Submission.missing` scope excludes excused submissions, submissions with a custom grade status, and `late_policy_status = 'extended'`. It includes anything a teacher explicitly marked `missing`. The instance `missing?` method returns false if the submission is excused, has a custom status, was graded with no late-policy status, or has `submitted_at`. Otherwise it is missing only if past due and (`for_new_quiz?` or `assignment.expects_submission?`). — [submission.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/submission.rb)

**`GET /api/v1/courses/:course_id/assignments` (and `/users/:user_id/courses/:course_id/assignments`)**
- `include[]` accepts `submission` ("The current user's current Submission"), `assignment_visibility`, `all_dates`, `overrides`, `observed_users`, `can_edit`, `score_statistics`, `ab_guid`. Other args: `override_assignment_dates` (default true), `bucket` (`past|overdue|undated|ungraded|unsubmitted|upcoming|future`), `assignment_ids[]`, `order_by` (`position|name|due_at`), `search_term`, `new_quizzes`. — [canvas-lms app/controllers/assignments_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/assignments_api_controller.rb)
- Bucket semantics, all based on the student's `submissions.cached_due_date`:
  - `upcoming`: has a date and is due between now and 1 week from now. It does not filter on submission status.
  - `future`: due date is null or ≥ now.
  - `undated`: no date.
  - `unsubmitted`: expects a submission (external_tool excluded) and is not submitted or graded.
  - `overdue`: has a date, is past due, expects a submission (excluding `external_tool`, `online_quiz`, `attendance`), is not submitted or graded, and can be submitted.
  — [canvas-lms lib/sorts_assignments.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/sorts_assignments.rb)
- Assignment fields from the model docs: `due_at`, `lock_at` and `unlock_at`, each described as "the due date…as it applies to the user requesting information from the API". Also `assignment_group_id`, `submission_types` ("'discussion_topic', 'online_quiz', 'on_paper', 'none', 'external_tool', 'online_text_entry', 'online_url', 'online_upload', 'media_recording', 'student_annotation'"), `has_submitted_submissions` ("If true, the assignment has been submitted to by at least one student"), `locked_for_user`, `lock_explanation`, `omit_from_final_grade`, `allowed_attempts`, `published`, `points_possible`. — [assignments_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/assignments_api_controller.rb)

**Submission objects (`GET /api/v1/courses/:id/students/submissions`)**
- "List submissions for multiple assignments": "If this argument [student_ids[]] is omitted, return submissions for the calling user. Students may only list their own submissions." Args: `assignment_ids[]`, `submitted_since`, `graded_since`, `workflow_state` (`submitted|unsubmitted|graded|pending_review`), `grading_period_id`, `order` (`id|graded_at`), `include[]` (incl. `assignment`, `submission_comments`, `sub_assignment_submissions`). — [canvas-lms app/controllers/submissions_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/submissions_api_controller.rb); route `courses/:course_id/students/submissions` in [routes.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/config/routes.rb)
- Submission model fields: `attempt`, `submission_type`, `submitted_at`, `late`, `excused` ("Excused assignments have no impact on a user's grade"), `missing`, `late_policy_status` ("late, missing, extended, none, or null"), `seconds_late`, `workflow_state` ("The current state of the submission"), `posted_at`, `redo_request` ("whether the submission has been reassigned by the instructor"). — [submissions_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/submissions_api_controller.rb)

### Inferences
- **Recommended "is it done?" logic, mirroring Canvas.** Treat an item as done if `planner_override.marked_complete == true`, or if (`submissions.submitted == true` and `redo_request != true` and `planner_override?.marked_complete != false`), or if `submissions.excused == true`. Planner's own completion treats excused items as incomplete; the bot should still suppress reminders for them.
- **Planner vs. assignments API.** Planner gives cross-course, per-student, override-applied dates plus completion. It does not give the assignment group, group weight, or full `submission_types`. Planner items can be joined to `/courses/:id/assignments?include[]=submission` (keyed by `plannable.assignment_id`/`plannable_id`) and `/courses/:id/assignment_groups` (group weights; not verified in this pass — see Gaps) for prioritization.
- **Don't use `has_submitted_submissions` for "has the student submitted".** It is course-wide: true if *any* student submitted. Use `submission.submitted_at`, `submission.workflow_state`, or planner `submissions.submitted`.
- **`/users/self/todo` drops items by design**, so it is a poor primary source. It is capped (default scope limit 15), limited to 4 weeks back and 1 week ahead, and hides past-due paper/external-tool items and anything the user clicked "ignore".
- **`upcoming_events` is effectively capped at 20 items and 7 days** despite the "paginated" wording.
- **Polling is cheap.** Because a submission save touches the user and an assignment save touches the course, the planner cache key should change on both. An ETag-aware client (If-None-Match) can poll planner cheaply and still see changes promptly.

### Gaps
- I didn't verify the exact JSON of `GET /api/v1/courses/:course_id/assignment_groups` (`group_weight`, `include[]=assignments`) from source. The GraphQL `AssignmentGroup.groupWeight` field exists (see section 4). The REST doc is at https://canvas.instructure.com/doc/api/assignment_groups.html.
- I found no official statement on whether Instructure Cloud has `planner_submittable_completion_filter` (a site-admin feature flag in `lib/plannable.rb`) turned on. It changes whether marking a quiz/discussion complete also completes the linked assignment.

## 2. Quizzes, discussions, ungraded to-dos, planner notes, peer reviews; due-date representation; overrides, lock dates and late policies

### Takeaway
Every item type the student sees in Planner comes through `/planner/items`, each with a `plannable_type` and a student-specific `plannable_date`. All API timestamps are ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`). Due dates in the API are already resolved for the requesting student's overrides (`cached_due_date`). Lock dates and late-policy status change what counts as "missing" or "submittable", but they do not change the due date.

### Cited Findings
- "With either encoding, all timestamps are sent and returned in ISO 8601 format (UTC time zone): YYYY-MM-DDTHH:MM:SSZ". — [canvas-lms doc/api/README.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/README.md)
- Canvas stores times in UTC (`config.time_zone = "UTC"`). Each request sets `Time.zone` to the user's profile time zone, or the account default. — [config/application.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/config/application.rb); [application_controller.rb set_time_zone](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/application_controller.rb)
- Some doc examples still show offset form (e.g. `"due_at": "2020-08-29T23:59:00-06:00"`), which contradicts the README's "UTC" statement. Parse both. — [assignments_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/assignments_api_controller.rb) vs [README.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/README.md)
- Per-student overrides: the assignment API's `due_at/lock_at/unlock_at` reflect overrides "as it applies to the user requesting information" (default `override_assignment_dates=true`). `include[]=all_dates` returns every override date. Planner, todo and bucket queries all filter on the per-student `submissions.cached_due_date`. — [assignments_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/assignments_api_controller.rb); [abstract_assignment.rb (due_between_for_user uses submissions.cached_due_date)](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb); [sorts_assignments.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/sorts_assignments.rb)
- Lock dates: `lock_at` is "the lock date (assignment is locked after this date)". `/todo` and `missing_submissions?filter[]=submittable` exclude locked assignments (`unlock_at < now` and `lock_at > now` required). Planner includes locked items. — [assignments_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/assignments_api_controller.rb); [abstract_assignment.rb not_locked](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb); [planner_controller.rb default_opts include_locked: true](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- Late policy and status: `late?` returns `late_policy_status == "late"` if a status is set, otherwise `submitted_at.present? && past_due?`. `missing?` honors teacher-set `missing`/`extended`/`none` statuses and custom grade statuses. — [submission.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/submission.rb)
- Quizzes:
  - Graded Classic Quizzes are Assignments with `submission_types` `online_quiz` and appear as assignment items.
  - Ungraded (practice/survey) quizzes appear as `plannable_type: quiz` in planner, and in `/todo` only with `include[]=ungraded_quizzes`.
  - A quiz `plannable_date` uses `cached_due_date || user_due_date || due_at`.
  — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb); [users_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/users_controller.rb); [planner_item.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/api/v1/planner_item.rb)
- Discussions:
  - Graded discussions are Assignments with `submission_types` `discussion_topic`.
  - Ungraded discussions with a "to-do date" appear as `discussion_topic` items.
  - Checkpointed discussions (required reply counts) appear as `sub_assignment` items, with `details.reply_to_entry_required_count`.
  — [planner_item.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/api/v1/planner_item.rb); [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- Ungraded to-do items: wiki pages and ungraded discussions with a `todo_date` come through `page_collection`/`ungraded_discussion_collection`, also available alone via `filter=ungraded_todo_items`. — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- Peer reviews come in two shapes. Classic AssessmentRequests appear as `assessment_request`, dated by `peer_reviews_due_at`. In courses with the `peer_review_allocation_and_grading` feature they appear instead as `peer_review_sub_assignment`. — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb); [planner_item.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/api/v1/planner_item.rb)
- Peer reviews are not in `/users/self/todo`: that endpoint only merges grading, submitting, checkpoint and ungraded-quiz collections. — [users_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/users_controller.rb)
- `submissions_needing_peer_review` window defaults to 2 weeks ago through 2 weeks ahead. — [user_learning_object_scopes.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/user_learning_object_scopes.rb)
- Planner notes appear as `planner_note`, dated by `todo_date`. They have no `html_url`; the code has a TODO for it. — [planner_item.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/api/v1/planner_item.rb)
- Canvas treats an assignment due at 23:59 or 00:00 as `all_day` for new records. In ICS this becomes a DATE value. — [abstract_assignment.rb all_day](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb); [calendar_event.rb IcalEvent](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/calendar_event.rb)
- A school help desk describes the sidebar behavior: "Assignments submitted through Canvas disappear automatically from the To Do List after they are submitted or remain on the To List for four weeks after the due date". Assignments "that are not graded or do not require an online submission only display until the due date". (search snippet) — [Illinois State / Seton Hall To Do guides via search](https://help.illinoisstate.edu/technology/support-topics/canvas/canvas-student-resources/to-do-list-access-in-canvas); [Seton Hall KB](https://setonhall.atlassian.net/wiki/spaces/PUBLICKBA/pages/3773988872)

### Inferences
- Convert UTC to the student's time zone for display. The user's profile time zone is available from `GET /api/v1/users/self` (`time_zone`; not verified in this pass) or GraphQL.
- "Available until" (`lock_at`) is a second, harder deadline. Remind before `due_at`, then warn again before `lock_at` if it is unsubmitted and late submissions are allowed.

### Gaps
- New Quizzes (LTI, `submission_types: ["external_tool"]`): I didn't verify from source exactly when `submitted_at` is set on the Canvas Submission. The `missing?` code special-cases `for_new_quiz?`, which suggests Canvas tracks New Quiz submissions.

## 3. Authentication options for a student

### Takeaway
Personal access tokens (Account › Settings › "+ New Access Token") are the only self-service option. In current Canvas core, users with only student roles must set an expiry of 120 days or less. Admins have dedicated switches to block student token creation entirely, and some large universities (e.g. UW-Madison since Nov 14 2025) have turned them on. OAuth2 needs a developer key issued by the school's Canvas admin, which schools generally don't grant students. Expect a token-renewal UX (at least every 120 days) and plan a fallback.

### Cited Findings
- Manual token generation in Instructure's own words: "For testing your application before you've implemented OAuth, the simplest option is to generate an access token on your user's profile page. Note that asking any other user to manually generate a token and enter it into your application is a violation of Canvas' API Policy. Applications in use by multiple users MUST use OAuth to obtain tokens." Steps: profile › "Approved Integrations" › generate. "Once the token is generated, you cannot view it again… access tokens are password equivalent." — [canvas-lms doc/api/oauth.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/oauth.md)
- Token create API (`POST /api/v1/users/:user_id/tokens`): `token[purpose]` is now **required** ("token[purpose] is missing" error), and `token[expires_at]` is optional for non-students. `token[scopes][]` is "Ignored if the default developer key does not have the 'enable scopes' option enabled. In such cases, the token will inherit the user's permissions instead." — [canvas-lms app/controllers/tokens_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/tokens_controller.rb)
- Student expiry rule in core code: `# Force an expiration date for students` / `if user_has_only_student_enrollments?(@current_user)` → "Expiration date is required"; `MAXIMUM_EXPIRATION_DURATION = 120.days` → "Expiration date cannot be more than 120 days in the future". — [tokens_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/tokens_controller.rb)
- Admin restrictions in core (AccessToken policy):
  - `root_account.limit_personal_access_tokens?` stops non-admins creating their own tokens.
  - `root_account.restrict_personal_access_tokens_from_students?` blocks users whose only roles are student, observer, or both ("a teacher that is a student/observer will still be allowed to").
  - Admins with `create_access_tokens` can still create tokens for users. These are "pending" until the user activates them.
  — [canvas-lms app/models/access_token.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/access_token.rb); [tokens_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/tokens_controller.rb)
- Release-note mirrors list "Restrict Student Personal Access Token Creation" (Account, Admin). The Canvas deploy notes of 2025-11-05 list "Restrict Personal Access Tokens Includes Observers" and "Access Token Expiration Date Required – Student". (search snippet) — [UC Riverside Canvas Features & Releases](https://canvas.ucr.edu/canvas-features-releases)
- An Instructure Community announcement covers User-Agent enforcement and "Additional Updates to User Access Tokens": purposes are required on all user tokens, student-only tokens must expire within 120 days of creation, and admins can block student token creation. User-Agent enforcement was postponed to production on **June 20, 2026**. (search snippet) — [Instructure Community: Enforcing User-Agent Header for Canvas API Requests](https://community.instructure.com/en/discussion/658205/enforcing-user-agent-header-for-canvas-api-requests/p1); [Univ. of Melbourne update](https://lms.unimelb.edu.au/updates/features-and-improvements/feature-update-enforcing-user-agent-header-for-canvas-api-requests)
- Melbourne says scripts without an explicit User-Agent are denied with 403 after June 20, 2026. (search snippet) — [Univ. of Melbourne](https://lms.unimelb.edu.au/updates/features-and-improvements/feature-update-enforcing-user-agent-header-for-canvas-api-requests)
- canvasapi 3.5.0 (2026-03-12) "Add a default User-Agent header". — [canvasapi CHANGELOG](https://raw.githubusercontent.com/ucfopen/canvasapi/develop/CHANGELOG.md)
- School variations (all from search snippets):
  - UW-Madison: "as of November 14th, 2025, student users … can no longer manually generate Access Tokens"; students must request one through a form, max 120 days. — [UW-Madison KB 156712](https://kb.wisc.edu/luwmad/156712); [UW-Madison IT news](https://it.wisc.edu/academic-technology/learn-uw-news/change-to-student-access-tokens-in-canvas/)
  - Stanford: "Previously, only student tokens were required to expire (30 days)". Instructor tokens moved to 90 days on 8/12/26. — [Stanford gocanvas Summer 2026](https://gocanvas.stanford.edu/news/canvas-update-summer-2026)
  - St. Edward's: "Students are not allowed to generate tokens." — [St. Edward's KB](https://support.stedwards.edu/TDClient/96/Portal/KB/Article/6479/Canvas-API-Access-Tokens)
  - Univ. of Missouri System: student tokens "are not approved", and user tokens "circumvent multi-factor authentication and university SSO authentication requirements". — [UM System token policy](https://tdx.umsystem.edu/TDClient/66/MOOnline/KB/ArticleDet?ID=2193); [UM justification](https://tdx.umsystem.edu/TDClient/66/MOOnline/KB/ArticleDet?ID=2302)
  - Texas A&M limits API tokens to course staff for teaching purposes: "not available for students". — [TAMU Canvas API token policy](https://lms.tamu.edu/support-resources/canvas-api-access-token-request.html)
  - Other schools with their own student-token policies: [UNH/PSU](https://td.usnh.edu/TDClient/60/Portal/KB/Article/5520/Canvas-User-API-Token-Access-UNH-PSU), [UW (Seattle)](https://ois.uw.edu/learn/tools/canvas/canvas-policies/integration-development-data-access/api-access-tokens), [Cornell](https://learn.canvas.cornell.edu/canvas-api-access-tokens)
- Token scope: unless an admin enabled scopes on the default developer key, a manual token "will inherit the user's permissions" — i.e., full access as the student. — [tokens_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/tokens_controller.rb)
- Scoped developer keys limit endpoints; "unscoped keys … will have access to all Canvas resources available to the authorizing user". (search snippet) — [Instructure Developer Keys doc](https://developerdocs.instructure.com/services/canvas/oauth2/file.developer_keys)
- OAuth2:
  - "For Canvas Cloud (hosted by Instructure), developer keys are issued by the admin of the institution."
  - "Developer keys issued after Oct 2015 generate tokens with a 1 hour expiration. Applications must use refresh tokens."
  - The refresh response "will not contain a new refresh token; the same refresh token is to be reused."
  - A deleted or expired token returns 401, with a `WWW-Authenticate` header that tells it apart from permission 401s.
  — [oauth.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/oauth.md)
- UW says "students cannot access the API, as it contains confidential data". Developer keys there are for UW employees and departments. (search snippet) — [UW developer keys policy](https://ois.uw.edu/tools-services-support/teaching-learning/canvas/canvas-policies/integration-development-data-access/developer-keys); [UW API access](https://uwconnect.uw.edu/it?id=kb_article_view&sysparm_article=KB0034590)
- Token storage guidance from Instructure: "Storing a token is in many ways equivalent to storing the user's password". Don't embed tokens in web pages or pass them in URLs, and secure the store. Native apps should use OS keychains. — [oauth.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/oauth.md)

### Inferences
- A student's personal token is "testing"-sanctioned self-use. The policy bar is against *asking other users* to paste tokens into an app. So a single-user, self-hosted bot that holds the student's own token is the most defensible design. A multi-user hosted service would need OAuth and a developer key from each school.
- Build expiry handling: track `expires_at` from the token JSON, warn about 7 days ahead, and detect 401 plus `WWW-Authenticate`. Always send a descriptive `User-Agent` (required since June 2026).
- Developer keys are realistic only if a faculty sponsor or department requests one, so don't plan the product around OAuth.

### Gaps
- I couldn't retrieve the full Instructure API Policy or Acceptable Use text (pages unreachable); see section 7 for snippet-level content.
- I couldn't confirm the exact Instructure release date when the 120-day student rule reached all production instances. The 2025-11-05 deploy-note mirror is the best evidence found.

## 4. Canvas GraphQL API (/api/graphql)

### Takeaway
GraphQL is available to any authenticated user (same token, `POST /api/graphql`), with permissions mirroring REST. It can fetch all courses, assignments, the student's own submission state and assignment-group weights in one round trip. There is no planner or to-do equivalent of `/planner/items` with `marked_complete` overrides. So GraphQL complements Planner but doesn't replace it. A new `User.courseWorkSubmissionsConnection` (for the new dashboard "course work" widget) is a near-to-do query, but it is new and undocumented as stable.

### Cited Findings
- "GraphQL endpoint permissions mirror permissions for the REST API… a student cannot view grades for another student." The endpoint is `POST /api/graphql` with `query` and `variables`, using `Authorization: Bearer <ACCESS_TOKEN>`. GraphiQL is at `/graphiql`. "The GraphQL API does not include everything that is currently in the REST API." It uses Relay connections (`first`/`after`, `pageInfo.endCursor/hasNextPage`): "Request reasonable page sizes to avoid being limited." — [canvas-lms doc/api/graphql.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/graphql.md)
- Route: `post "/api/graphql", to: "graphql#execute"`. — [routes.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/config/routes.rb)
- Root fields include `allCourses` ("All courses viewable by the current user"), `course(id)`, `assignment(id)`, `submission`, `user`, `legacyNode`. — [canvas-lms app/graphql/types/query_type.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/graphql/types/query_type.rb)
- Assignment fields:
  - Per-user overridden `dueAt`, `lockAt`, `unlockAt` ("overridden_field").
  - `pointsPossible`, `submissionTypes`, `assignmentGroup`, `htmlUrl`, `omitFromFinalGrade`, `gradingType`, `state`, `lockInfo`, `hasSubmittedSubmissions`, `assessmentRequestsForCurrentUser`.
  - `submissionsConnection(filter: SubmissionSearchFilterInput)`. If `includeUnsubmitted` is set, "unsubmitted" is added to the default states.
  - `mySubAssignmentSubmissionsConnection` for checkpoints.
  — [canvas-lms app/graphql/types/assignment_type.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/graphql/types/assignment_type.rb)
- The submission search filter accepts `includeUnsubmitted`, `states`, `userId`, `late`, `gradingStatus`, and others. — [submission_search_filter_input_type.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/graphql/types/submission_search_filter_input_type.rb)
- Submission fields include `state`, `submittedAt`, `cachedDueDate`, `excused`, `late`, `missing`, `latePolicyStatus`, `secondsLate`, `redoRequest`, `attempt`, `submissionType`, `submissionStatus`, `gradingStatus`, `postedAt`, `customGradeStatus`. — [canvas-lms app/graphql/interfaces/submission_interface.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/graphql/interfaces/submission_interface.rb)
- `AssignmentGroup` has `groupWeight`, `name`, `position`, `rules`, `state`. `Course` has `applyGroupWeights`. — [assignment_group_type.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/graphql/types/assignment_group_type.rb); [course_type.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/graphql/types/course_type.rb)
- `User.courseWorkSubmissionsConnection` is described as "All actionable submissions for the current user across enrolled courses, for course work widget". Args: `startDate`, `endDate`, `includeOverdue`, `includeNoDueDate`, `onlySubmitted`, `onlyCurrentGradingPeriod` (default true), `courseFilter`, `orderBy`, `observedUserId`. It returns `[]` unless the queried user is the current user. — [canvas-lms app/graphql/types/user_type.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/graphql/types/user_type.rb)
- canvasapi exposes `Canvas.graphql(query, variables)`, which POSTs JSON to `graphql`. — [canvasapi canvas.py](https://raw.githubusercontent.com/ucfopen/canvasapi/develop/canvasapi/canvas.py)

### Inferences
- A good sync design is to use GraphQL for a once-per-few-hours metadata snapshot and Planner REST for frequent to-do and completion polling. The GraphQL snapshot is a single query: `allCourses { assignmentGroups { groupWeight } assignmentsConnection { nodes { dueAt lockAt pointsPossible submissionTypes assignmentGroup { groupWeight } submissionsConnection(filter:{includeUnsubmitted:true}) { nodes { state submittedAt missing late excused } } } } }`. Field names follow the Ruby snake_case → GraphQL camelCase convention (inferred).
- Don't depend on `courseWorkSubmissionsConnection`. Its description ties it to a new dashboard widget, so it may change without notice.
- GraphQL requests go through the same Rack throttle middleware (see section 6). Large nested queries are expensive because cost is based on CPU and DB time.

### Gaps
- I couldn't confirm the default value of `DEFAULT_SUBMISSION_STATES`, or whether Instructure applies GraphQL-specific complexity limits beyond the generic throttle.

## 5. Calendar iCal feed (unauthenticated feed URL)

### Takeaway
The per-user feed (`/feeds/calendars/<feed_code>.ics`) contains dated assignments, with per-student override dates applied, and calendar events from 30 days back to 366 days ahead. It has no submission status, undated items, planner notes, ungraded to-do pages, or completion state. It works with no token, which makes it a solid degraded fallback for "what is due when". But the URL is a bearer secret, and no officially documented way to rotate it was found.

### Cited Findings
- Routes: `get "calendars/:feed_code"` and `"calendars/:feed_code.:format"` → `calendar_events_api#public_feed`, under the `/feeds` scope. — [routes.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/config/routes.rb)
- When the feed code identifies a user: `@start_date = 30.days.ago`, `@end_date = 366.days.from_now`. It adds assignments (`assignment_scope(@current_user).paginate(per_page: 1000, max: 1000)`) with `apply_assignment_overrides`, checkpoint sub-assignments, calendar events (also capped at 1000), and reserved appointment groups. Without a user it falls back to a generic course feed with no overrides. — [canvas-lms app/controllers/calendar_events_api_controller.rb (public_feed)](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/calendar_events_api_controller.rb)
- ICS event fields:
  - `DTSTART`/`DTEND` = assignment `due_at` in UTC, or a DATE value for all-day.
  - `SUMMARY` = title plus ` [course_code]`.
  - `DESCRIPTION` (only if the user can view the item and it isn't module-locked), `X-ALT-DESC` (HTML).
  - `UID` = `event-assignment-<id>`, or `event-assignment-override-<id>` for an override.
  - `URL` = a calendar link, and `DTSTAMP` = `updated_at`.
  - The calendar is `METHOD: PUBLISH`.
  — [canvas-lms app/models/calendar_event.rb (IcalEvent)](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/calendar_event.rb); [calendar_events_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/calendar_events_api_controller.rb)
- University guides (search snippets) say the feed includes events and assignments across your calendars, up to 1,000 items, future items up to 366 days and past items within 30 days. They also say "To Do items are NOT included". — [USNH iCal feed KB](https://td.usnh.edu/TDClient/60/Portal/KB/ArticleDet?ID=932); [Instructure: subscribe with Outlook.com](https://community.instructure.com/en/kb/articles/662801-how-do-i-subscribe-to-the-calendar-feed-using-outlook-com)
- Refresh lag sits mostly in consumer apps: "Outlook.com may take up to 24 hours", and Google Calendar refreshes about every 24 hours. Canvas-side delay was described as about an hour by one help desk. (search snippet; some sources are vendor blogs) — [MIT Sloan EdTech](https://mitsloanedtech.mit.edu/support/how-to-sync-your-canvas-calendar-feed-to-outlook-in-office-365); [La Salle KB](https://lasalle.teamdynamix.com/TDClient/2615/Portal/KB/ArticleDet?ID=165761)
- Search found no official Instructure documentation of a "reset/regenerate feed URL" control. Only low-quality third-party pages claim a password reset changes it (unverified). — search results summarized in this session; no reliable source

### Inferences
- If the bot fetches the `.ics` URL directly, there is no consumer-app lag. It can be polled hourly, since it is generated per request. Diff by `UID` plus `DTSTART`/`DTSTAMP` to detect new assignments and due-date changes.
- Without a submission signal, iCal-only mode must fall back to "remind until due, and let the user tell the bot 'done'". Store done-state locally keyed by UID.
- Treat the feed URL like a password: store it encrypted and never log it. It exposes course names and assignment titles and descriptions to anyone who has it.

### Gaps
- I couldn't confirm exactly how `feed_code` is derived for users, or whether it can be rotated. The routes file comment says ":feed_code attribute is keyed" (details not retrieved).

## 6. Throttling, pagination, per_page, polling cadence

### Takeaway
Canvas throttles each access token with a leaky bucket. The open-source defaults are high-water mark 600, max 800, leak 10 units/sec, and a pre-flight cost of 50 per in-flight request. Responses carry `X-Request-Cost` and `X-Rate-Limit-Remaining`. Throttled requests get 429 on Instructure Cloud: the current docs say so and canvasapi switched from 403 to 429 in March 2026. Self-hosted Canvas still defaults to 403. Pagination uses opaque `Link` headers (default 10 per page; planner defaults to 50). A single-threaded personal bot polling every 5–15 minutes is far below any limit.

### Cited Findings
- "Canvas includes a built in dynamic throttling mechanism… Each request subtracts from your quota, and the quota is automatically replenished over time. In the event that your API request is throttled, you will receive a `429 Forbidden (Rate Limit Exceeded)` response."
  - "every request will return a `X-Request-Cost` header… If throttling is applicable… `X-Rate-Limit-Remaining`."
  - "any API client that makes no more than one simultaneous request is unlikely to be throttled. Parallel requests are subject to an additional pre-flight penalty."
  - "each access token has its own quota."
  — [canvas-lms doc/api/throttling.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/throttling.md)
- Middleware defaults: `maximum: 800, hwm: 600, outflow: 10, up_front_cost: 50`. Cost is weighted CPU plus DB time. The response status is `403` unless `Setting request_throttle.send_429_response == "true"`, in which case it is `429`. The body is "<code> … (Rate Limit Exceeded)" with `X-Rate-Limit-Remaining: 0.0`. Buckets are keyed by the token hash, then user, then session. — [canvas-lms app/middleware/request_throttle.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/middleware/request_throttle.rb)
- canvasapi 3.5.0 (2026-03-12): "Updated `RateLimitExceeded` exception to trigger on HTTP 429 instead of old 403." — [canvasapi CHANGELOG](https://raw.githubusercontent.com/ucfopen/canvasapi/develop/CHANGELOG.md); [canvasapi requester.py](https://raw.githubusercontent.com/ucfopen/canvasapi/develop/canvasapi/requester.py)
- Older community threads describe a 403 "Rate Limit Exceeded" and a ~700 figure. These are anecdotal. — [Instructure Community API Rate Limiting](https://community.canvaslms.com/t5/Developers-Group/API-Rate-Limiting/td-p/211140); [canvas-lms-users group](https://groups.google.com/g/canvas-lms-users/c/9yIYaL9CLrE/m/7sDqs2__3S4J)
- Pagination: "Requests that return multiple items will be paginated to 10 items by default"; "There is an unspecified limit to how big you can set per_page to." `Link` rels are `current`, `next`, `prev`, `first`, `last`, and `last` may be omitted. "These links should be treated as opaque." An `access_token` query param is stripped from links. Parse the header case-insensitively. — [canvas-lms doc/api/pagination.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/pagination.md)
- Planner uses bookmark pagination (`page` defaults to "first"; it fetches `per_page+1` to detect more). — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- Server-side caches bound freshness: planner is effectively uncached across changes (see section 1), upcoming_events is cached 3 min, and todo scopes 15 min. — [users_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/users_controller.rb); [user_learning_object_scopes.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/user_learning_object_scopes.rb)

### Inferences
- Cadence suggestion:
  - Planner (`start_date=now-28d`, `end_date=now+21d`, `per_page=100`), with ETag and `If-None-Match`, every 5–10 min during waking hours and every 30–60 min overnight.
  - Course and assignment-group metadata every 6–24 h.
  - One request at a time.
  - On 429 or 403-with-"Rate Limit Exceeded", back off exponentially. Treat both codes as possible throttles, and check the body text before treating a 403 as an auth failure.
- Log `X-Request-Cost` to tune polling.

### Gaps
- Instructure Cloud's actual production throttle values (they can be overridden per account or client) aren't published.

## 7. Instructure API Policy / Terms and university IT policies

### Takeaway
Instructure's policies prohibit sharing your API token with any third party and accessing the service "by any means other than publicly supported interfaces" (scraping is named). They also make apps used by multiple users go through OAuth. A student using their own token in their own self-hosted bot fits the "manual token for your own use" pattern. A hosted service that collects students' tokens, or scrapes the UI, falls into prohibited territory. Many universities add stricter local rules.

### Cited Findings
- "asking any other user to manually generate a token and enter it into your application is a violation of Canvas' API Policy. Applications in use by multiple users MUST use OAuth". — [oauth.md](https://raw.githubusercontent.com/instructure/canvas-lms/master/doc/api/oauth.md)
- The Instructure Canvas API Policy is effective 12 Aug 2025 and covers the Canvas API and DAP Query API. It covers:
  - principles (don't impersonate, be transparent, don't overload),
  - "User information, including course enrollments, grades, and profile information, retrieved through the API should be considered and treated private information",
  - rate limiting per user access token,
  - prohibited uses including using the APIs "on behalf of any third party" and probing systems.
  (search snippets; full text not retrieved) — [Instructure Canvas API Policy](https://www.instructure.com/policies/canvas-api-policy)
- The Instructure Acceptable Use Policy prohibits "sharing your API tokens, login, or other access credentials with any third party". It also bars accessing the service "by any means other than publicly supported interfaces", with "scraping" given as an example. (search snippets) — [Instructure Acceptable Use](https://www.instructure.com/policies/acceptable-use)
- Instructure is tightening controls on automation: User-Agent is required (production enforcement June 20, 2026) because requests without one "can signal scraping or other unwanted behaviors". There is also a new "APIs Missing User-Agents Report" for admins. (search snippets) — [Instructure Community UA post](https://community.instructure.com/en/discussion/658205/enforcing-user-agent-header-for-canvas-api-requests/p1); [UCR release mirror](https://canvas.ucr.edu/canvas-features-releases)
- University examples:
  - Texas A&M lists "content scraping" as prohibited and says tokens are "not available for students". — [TAMU](https://lms.tamu.edu/support-resources/canvas-api-access-token-request.html)
  - UM System says tokens bypass MFA and are not approved for students. — [UM System](https://tdx.umsystem.edu/TDClient/66/MOOnline/KB/ArticleDet?ID=2302)
  - UW-Madison cites FERPA exposure from token sharing. — [UW-Madison KB](https://kb.wisc.edu/luwmad/156712)

### Inferences
- Lowest-risk posture: single user, self-hosted, the student's own token, read-mostly (with optional planner-override writes), and a descriptive User-Agent. Don't share tokens with a third-party SaaS. Check the school's acceptable-use policy. If the school blocks student tokens, any workaround (cookies, browser automation) arguably circumvents an institutional control, so recommend asking IT first.
- Sending Canvas data (titles, grades) to a third-party LLM or vision API is "treat as private information" territory. Prefer local processing or minimize what is sent.

### Gaps
- The verbatim text of the API Policy and AUP, and any explicit carve-out for personal or student use, wasn't retrieved. No Instructure statement found that specifically addresses students running personal scripts.

## 8. Fallback approaches if tokens are blocked

### Takeaway
Ranked by reliability and ToS risk:
1. iCal feed: no token needed, official, but no submission state.
2. Reuse the browser session to call the same JSON endpoints the UI calls (`/api/v1/planner/items`): high fidelity, but fragile auth and policy-grey.
3. Canvas notification emails: official, but sparse — no "due soon" reminder type exists.
4. Full browser automation or screenshots + OCR/vision-LLM: highest effort, most brittle, and closest to the AUP's "scraping" prohibition.

### Cited Findings
- iCal: see section 5 (assignments and dates, no status). — [calendar_events_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/calendar_events_api_controller.rb)
- The UI is a client of the same JSON API: the To Do sidebar GETs `/api/v1/planner/items` with the browser's session. Canvas controllers use `protect_from_forgery with: :exception`, a Rails CSRF check that applies to state-changing (non-GET) requests. — [sidebar-actions.js](https://raw.githubusercontent.com/instructure/canvas-lms/master/ui/shared/planner/actions/sidebar-actions.js); [application_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/application_controller.rb)
- Community tools already do this. A Canvas MCP server uses "the browser session cookie instead of a token, so an admin policy blocking token generation cannot stop it". Another opens headless Chromium for SSO plus a Duo push and captures tokens. A canvas-cli issue notes schools that disable student tokens push users to "session-cookie auth (experimental)". (search snippets) — [glama.ai MCP listing](https://glama.ai/mcp/servers/kl1lsam9ig); [glama.ai MCP listing 2](https://glama.ai/mcp/servers/hblrf1qkyv); [thedavidweng/canvas-cli issue #16](https://github.com/thedavidweng/canvas-cli/issues/16)
- Notification emails: frequency is immediate, daily, weekly, or off. Yale says immediate emails are held about 1 hour to batch edits, daily summaries go out around 6pm, and weekly summaries on Saturday 4–6pm. The "Due Date" notification fires when a due date is *changed* ("Receive an email when the due date on an Assignment is changed"), not as a pre-deadline reminder. Defaults vary (SJSU and IU: Due Date weekly). (search snippets) — [Yale Canvas help](https://help.canvas.yale.edu/a/914669-how-do-i-modify-the-default-notification-settings); [Tufts](https://tuftsedtech.screenstepslive.com/s/18992/m/73355/l/810714-how-do-i-set-my-canvas-notification-preferences); [SJSU defaults](https://sjsu.edu/cfeti/teaching-resources/software/canvas/student-resources/canvas-notifications-default-settings.php); [IU defaults](https://www.kb.indiana.edu/d/bfdl); [FSU guide](https://support.canvas.fsu.edu/kb/article/923)
- Policy risk for scraping and automation: the AUP bars non-public interfaces and scraping (section 7). — [Instructure AUP](https://www.instructure.com/policies/acceptable-use)

### Inferences
- **Session-cookie reuse.** Log in once in a real browser (SSO + Duo), export cookies, then call `/api/v1/planner/items` with `Accept: application/json`. GETs shouldn't need a CSRF token, but planner-override writes would need `X-CSRF-Token` (from the `_csrf_token` cookie; not verified).
  - Effort: medium.
  - Reliability: sessions expire on school-set policies, and Duo "remember me" duration is set by the school, so the user must re-auth periodically.
  - Risk: policy-grey, since it's the same data the student sees, but arguably circumvents a token ban.
- **Headless browser automation (Playwright).** MFA blocks unattended login, so it needs a human-in-the-loop Duo approval or long-lived cookies. Brittle against SSO page changes; high effort; highest ToS and IT-security risk (credential storage).
- **Screenshot + OCR/vision-LLM of the To Do list.** Lowest fidelity: truncated lists (the sidebar loads 14 at a time), no stable IDs, time-zone and relative-date parsing. Useful only as a manual "paste a screenshot" assist. Sends possibly FERPA data to an LLM.
- **Email parsing (Gmail/Outlook API).** Good for "new assignment created", "due date changed", "submission comment" and "graded" events if set to *immediate*, but there is no "submitted" confirmation for most types and no "due soon". Pair it with iCal for dates.
- Recommended stack: primary is a personal token plus the Planner REST API (and GraphQL for metadata). Fallback A (no token) is the iCal feed plus a manual "done" button in the bot, optionally enriched by notification emails. Fallback B (opt-in, advanced) is session-cookie reuse.

### Gaps
- No official Instructure statement found on session-cookie API use by end-user scripts. Duo and SSO session lifetimes are institution-specific, and no source was gathered.

## 9. Client libraries

### Takeaway
Python `canvasapi` (UCF Open) is actively maintained: v3.6.0 on 2026-04-16. Its changelog adds Python 3.14 and drops 3.9, which implies Python 3.10–3.14 support. It also has 429 handling and a default User-Agent. It wraps `/users/self/todo`, `/upcoming_events`, missing submissions, planner notes and overrides, and `graphql()`. It has no method for `GET /api/v1/planner/items`, so call that through the requester or plain HTTP. No official Instructure JS/TS client exists; community options include `@kth/canvas-api`.

### Cited Findings
- PyPI: canvasapi latest is 3.6.0, uploaded 2026-04-16. Earlier releases: 3.5.0 on 2026-03-12, 3.4.0 on 2025-11-10, 3.3.0 on 2024-08-27. Homepage is github.com/ucfopen/canvasapi. — [PyPI canvasapi JSON](https://pypi.org/pypi/canvasapi/json)
- The CHANGELOG lists:
  - 3.6.0: added Python 3.14, dropped 3.9.
  - 3.5.0: 429 `RateLimitExceeded`, default User-Agent.
  - 3.4.0: LTI Resource Links, Smart Search, New Quizzes Accommodations, a type-aware `PaginatedList`, and a reworked JSON POST used by GraphQL.
  — [canvasapi CHANGELOG](https://raw.githubusercontent.com/ucfopen/canvasapi/develop/CHANGELOG.md)
- Methods on `Canvas`: `get_todo_items()` → `GET users/self/todo`, `get_upcoming_events()`, `get_planner_notes()/get_planner_note()/create_planner_note()`, `get_planner_overrides()/get_planner_override()/create_planner_override()`, `get_calendar_events()`, `graphql(query, variables)`. `User.get_missing_submissions()`. A grep of the develop branch found no `planner/items` call. — [canvasapi canvas.py](https://raw.githubusercontent.com/ucfopen/canvasapi/develop/canvasapi/canvas.py); [canvasapi user.py](https://raw.githubusercontent.com/ucfopen/canvasapi/develop/canvasapi/user.py)
- canvasapi issue "User-Agent needed from January 2026" (#706). — [ucfopen/canvasapi#706](https://github.com/ucfopen/canvasapi/issues/706)
- npm (community, unofficial):
  - `@kth/canvas-api` 5.1.1 (2025-11-20, KTH)
  - `@groton/canvas-api` 0.3.10 (2026-04-06, "Typed access to Canvas LMS API")
  - `canvas-lms-api` 1.0.6 (2026-01-29)
  - `@atomicjolt/canvas-api-client` 0.0.2 (2025-05-19)
  - `canvas-api-ts` 0.6.1 (2020, stale)
  — [npm @kth/canvas-api](https://registry.npmjs.org/@kth%2Fcanvas-api); [npm @groton/canvas-api](https://registry.npmjs.org/@groton%2Fcanvas-api); [npm canvas-lms-api](https://registry.npmjs.org/canvas-lms-api); [npm search](https://registry.npmjs.org/-/v1/search?text=canvas%20lms%20api&size=12)

### Inferences
- In Python, use canvasapi for most calls and `canvas._Canvas__requester.request("GET", "planner/items", ...)` (name-mangled private attribute; fragile) or plain `httpx`/`requests` for planner. The endpoint is simple enough that a thin custom client with Link-header pagination is reasonable.
- In TS, a thin `fetch` wrapper is probably safer than any community client.

### Gaps
- I didn't evaluate `@kth/canvas-api` API surface or maintenance cadence beyond the npm metadata.

## 10. Detecting submissions quickly, and edge cases

### Takeaway
Canvas has no push or webhook available to students. Live Events/Caliper need admin setup. Detect submission by polling Planner (`submissions.submitted` / `filter=complete_items`) or `students/submissions?submitted_since=`. Polling every 5–10 minutes gives near-real-time suppression of reminders. Several cases never produce a Canvas submission and need manual "done" or override handling: paper, external tool/LTI without passback, `none`/`not_graded`, and planner-only to-dos.

### Cited Findings
- `submitted_since` param: "only include submissions that were submitted after the specified date_time… exclude submissions that do not have a submitted_at". Students can list only their own. — [submissions_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/submissions_api_controller.rb)
- Planner completion is based on `submitted_at` present and no `redo_request`. A user override `marked_complete:false` can re-open a submitted item. — [lib/plannable.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/plannable.rb)
- Resubmissions and redo: `redo_request` marks "the submission has been reassigned by the instructor". Planner then treats it as incomplete. `attempt` increments per submission, and `allowed_attempts` (-1 = unlimited) is on the assignment. — [submissions_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/submissions_api_controller.rb); [plannable.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/plannable.rb); [assignments_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/assignments_api_controller.rb)
- Undated assignments never appear in Planner, `/todo`, `upcoming_events`, or the iCal feed. All of these filter on a due-date range: `due_between_for_user` and `cached_due_date` ranges; the iCal feed uses a dated scope. Use `/courses/:id/assignments?bucket=undated`. — [abstract_assignment.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb); [sorts_assignments.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/sorts_assignments.rb)
- Paper, external-tool and none-type assignments are `OFFLINE_SUBMISSION_TYPES` (`on_paper, external_tool, none, not_graded, wiki_page, peer_review`). `/todo` drops them once past due. `missing?` only flags assignments that `expects_submission?` (or New Quizzes). The `overdue` bucket excludes `external_tool` and `online_quiz`. A teacher can grade without a submission, giving `workflow_state: graded` with null `submitted_at`. — [abstract_assignment.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb); [submission.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/submission.rb); [sorts_assignments.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/lib/sorts_assignments.rb)
- Excused: `excused` means "no impact on a user's grade". Excused submissions are never `missing`. `/todo` treats excused as not needing submission. — [submissions_api_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/submissions_api_controller.rb); [submission.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/submission.rb); [abstract_assignment.rb need_submitting_info](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/abstract_assignment.rb)
- Multiple sections and overrides: dates are resolved per student (`cached_due_date`). Section-specific calendar events are filtered by the user's section context codes. — [planner_controller.rb calendar_events_collection](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb); [user.rb upcoming_events](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/user.rb)
- Group assignments: Planner and todo include group contexts (`group_ids`/`context_codes` like `group_123`). — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- Concluded courses are excluded unless `include[]=concluded`. — [planner_controller.rb](https://raw.githubusercontent.com/instructure/canvas-lms/master/app/controllers/planner_controller.rb)
- LTI grade passback can mark complete/incomplete grading in odd ways: a complete/incomplete assignment is marked complete only at 100%. — [canvas-lms issue #1719](https://github.com/instructure/canvas-lms/issues/1719)

### Inferences
- Reminder suppression rule: suppress if planner-complete (section 1 logic) or `excused` or `workflow_state == graded`, including graded-without-submission for paper work. For `on_paper`/`external_tool`/`none` items with no submission, ask the user, then write a planner override (`POST /api/v1/planner/overrides {plannable_type:"assignment", plannable_id, marked_complete:true}`). This keeps the bot and the Canvas UI in sync.
- Handle time zones by always storing UTC. Compute "due in N hours" against UTC. Render in the user's profile time zone, not the server's. Watch for all-day (23:59 local) semantics in iCal DATE values.
- Detection latency is roughly equal to the poll interval. Planner's cache key changes on submission (user touch), so no extra server-side delay is expected beyond the poll interval; `/todo` scopes may lag up to 15 minutes.

### Gaps
- No student-accessible webhook or push mechanism was found. Canvas Live Events / Data Services need admin configuration (not researched in depth here).
- How LTI 1.3 AGS score passback sets `submitted_at` for third-party tools wasn't verified from source. Behavior likely varies by tool.
