# coach_inbox
Status: agreed 2026-09-25 (approved by Martin)
Kind: app
Summary: coaches see members' private questions from the questions zone inside the Tickets tab, answer them there and close them

Part of: `docs/specs/INDEX.md` · Deploy: `deploy.sh` (app), `jobs/deploy-alerts.sh` (alert) · Updated: 2026-10-05

## Overview

Coaches see members' private questions (from the questions zone) inside the Tickets tab, answer them there and close them.
Owns: `coach_inbox.py`, the root `raillog.py` copy, the Cloud Run service's BTB_ALERT policies, and `grant_helpdesk.private_thread_workflow`.
Reads `lesko-486515.private_chat.private_threads` / `private_messages` (EU, owned by the zone) and `bigtribebuilders.dataform.core_members` for names.
Entry points: `load_member_questions`, `waiting_count`, `merge_into_tickets`, `report_source_failure`, `raillog.alert`, `add_coach_reply`, `set_thread_workflow`.
*Not in scope:* assigning a thread to a coach or moving it to a lane (the table has the columns; a later task), telling members of a reply (the zone shows it on next load), emailing coaches, any change to `private_chat`'s schema or grants, a heartbeat (the app is not scheduled).

Who: coaches and the admin · Where: Streamlit, the Tickets tab of the grant-helpdesk app

## Screens

### Tickets tab: member-question rows

- Shows each 1:1 thread as a row among the community tickets, with a `Member question` badge, a `waiting`, `Answered` or `Closed` badge, and an action dropdown offering `Answer` then `Close` (only `Answer` once closed). The tab label counts the waiting threads.
- Reads / Writes: reads `private_threads`, `private_messages`, `core_members` and `private_thread_workflow`; `Close` writes `private_thread_workflow`.
- Error view: threads unreadable -> `st.error` and the community tickets still show; workflow table unreadable -> the threads show, none as closed; a failed `Close` -> `st.error` and the row stays.

### Answer dialog

- Shows the member's thread, a reply form, and the member's history (community tickets and other private threads). Sending a reply closes the thread and closes the dialog.
- Reads / Writes: reads the same tables plus the member's community tickets; a reply inserts one row into `private_messages` and closes the thread in `private_thread_workflow`.
- Error view: a distinct message per reply result with the typed text kept; "Answer sent, but the thread could not be closed" when only the close fails; "History unavailable" when the history lookup fails, with the reply form still working.

## Functions

### load_member_questions(client=None)

`def load_member_questions(client: bigquery.Client | None = None) -> pd.DataFrame`

*What it does:*
- R1: when called, it reads every thread with its messages in one parameterised query (tables named from `config.PRIVATE_CHAT_DATASET`, default `lesko-486515.private_chat`) and returns one row per thread.
- R2: each row carries `content_id = "pc:" + thread_id`, `source = "member_question"`, `member_id`, `member_name` (from `core_members`, else `"Member <id>"`), `topic`, `subject`, `created_at`, `last_activity_at`, `messages` (list, oldest first), `status`.
- R3: `status` is derived on every read, never stored as such: when the thread has a `closed_at` in `private_thread_workflow` and no member message with a `created_at` after it -> `closed`; otherwise the newest message by `created_at` is `member` -> `waiting`, `coach` -> `answered`.
- R5: a member message newer than `closed_at` brings a closed thread back as `waiting`, with nothing written; closing it again later moves `closed_at` forward.
- R6: when only the `private_thread_workflow` read raises, it calls `report_source_failure("workflow read", err)` and still returns the threads, with no thread shown as `closed`, so an outage of the workflow table never hides a member's question.
- R4: when the read raises, it calls `report_source_failure("read", err)` and returns an empty frame with the same columns, so the Tickets tab still renders its MN tickets.

*Examples:* one thread, messages member then coach, no workflow row -> one row, `status="answered"`. The same thread closed at 10:00 -> `closed`; the member writes at 10:05 -> `waiting`. Empty tables -> empty frame, no alert.

*Inputs:* an optional BigQuery client (tests pass a fake).

*Outputs:* a DataFrame, one row per thread.

*Errors:* BigQuery error or denied access -> empty frame, UI shows `st.error` -> `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED`. Workflow table unreadable or missing -> threads still returned, none closed -> `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat workflow read failed: ...`.

*Test:* `/opt/anaconda3/bin/pytest tests/test_coach_inbox.py` in `.claude/worktrees/coach-inbox-list`, fake client seeded with two threads -> R1-R3 rows asserted; fake client that raises -> R4 empty frame and one captured `BTB_ALERT` line; red first against `origin/main`. Closing: same file, fake client seeded with a closed thread, a closed thread with a newer member message, and a workflow read that raises -> `closed`, `waiting`, and all threads returned with one captured `BTB_ALERT` line (R3, R5, R6); red first against `origin/main`, where no row is ever `closed`.

### waiting_count(questions)

`def waiting_count(questions: pd.DataFrame) -> int`

*What it does:*
- R1: when given the frame from `load_member_questions`, it returns the number of rows with `status == "waiting"`.
- R2: the Tickets tab label shows it as `🎫 Tickets (N new)` when N > 0, plain `🎫 Tickets` otherwise.

*Examples:* 3 waiting + 2 answered -> 3. Empty frame -> 0.

*Inputs / Outputs:* the questions frame -> an int.

*Errors:* none (pure).

*Test:* same command and file, a frame of 3 waiting + 2 answered -> 3 (R1), label string built for 0 and 3 (R2); red first against `origin/main`.

### merge_into_tickets(tickets, questions)

`def merge_into_tickets(tickets: pd.DataFrame, questions: pd.DataFrame) -> pd.DataFrame`

*What it does:*
- R1: when given the Tickets-lane frame and the questions frame, it returns one frame: waiting member questions first, then everything by `last_activity_at` newest first.
- R2: member-question rows render with a `Member question` badge, their messages HTML-escaped, and the action dropdown described under `set_thread_workflow` R5.
- R4: closed member questions follow the sidebar Status filter the way closed community tickets do: they show only when Status is `closed`, and then they are the only member questions shown. Under every other Status choice, including "All", the member questions shown are the ones not closed *(as-built: member questions ignore the rest of the Status filter)*.
- R3: sidebar filters that have no meaning for a thread (urgency, domain, space) leave member questions out only when the filter is set to something other than "All".

*Examples:* 2 tickets + 1 waiting question -> 3 rows, the question first.

*Inputs / Outputs:* two frames -> one frame with a `source` column (`ticket` / `member_question`).

*Errors:* none (pure).

*Test:* same command and file, fixture frames -> order (R1) and `source` values (R2); red first against `origin/main`.

### member_other_threads(questions, member_id, exclude_content_id)

`def member_other_threads(questions: pd.DataFrame, member_id: str, exclude_content_id: str) -> pd.DataFrame`

*What it does:*
- R1: given the frame `load_member_questions` already returned, it returns only that member's private threads, minus the thread whose `content_id` is `exclude_content_id`, newest activity first.
- R2: it runs no BigQuery read of its own; it filters the cached frame the Tickets tab already loaded.

*Examples:* a member with 3 threads, one of them open -> the other 2; an unknown member -> an empty frame.

*Inputs / Outputs:* the questions frame, a member id and the open thread's content id -> a frame with the same columns.

*Errors:* none (pure).

*Test:* `tests/test_coach_inbox.py` (member_other_threads section), plain pandas fixtures; red first.

### report_source_failure(operation, err)

`def report_source_failure(operation: str, err: Exception) -> None`

*What it does:*
- R1: when a `private_chat` read or write fails, it calls `raillog.alert("coach-inbox", "SOURCE_FAILED", f"private_chat {operation} failed: {type(err).__name__}")`.
- R2: it never puts a message body, subject or query parameter into the line.

*Examples:* `("read", Forbidden(...))` -> stdout `{"severity": "ERROR", "message": "BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat read failed: Forbidden"}`.

*Inputs / Outputs:* operation name and the exception -> one JSON line on stdout.

*Errors:* none; it is the failure path and never raises.

*Test:* same command and file, capsys -> exact line (R1), a body string absent from it (R2); red first against `origin/main`.

### raillog.alert(runnable, code, message)

`def alert(runnable, code, message)` in root `raillog.py`, a copy of `jobs/raillog.py` so the Streamlit container imports it from the app path.

*What it does:*
- R1: it behaves exactly like `jobs/raillog.py`: same `REPO = "grant-helpdesk"`, same `CODES` set, same one-line JSON shape.
- R2: an unknown code falls back to `UNEXPECTED`.
- R3: it is a separate file, not an import: each job's Dockerfile copies only its own script plus `jobs/raillog.py`, and the app's Dockerfile builds from the repo root, so only a root copy makes `import raillog` work from `app.py`.

*Examples:* `("coach-inbox", "SOURCE_FAILED", "private_chat read failed: Forbidden")` -> stdout `{"severity": "ERROR", "message": "BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat read failed: Forbidden"}`.

*Inputs / Outputs:* runnable, code, message -> one JSON line on stdout.

*Errors:* none; it is the failure path and never raises.

*Test:* `tests/test_raillog_app.py`, capsys -> the exact line for a known code (R1) and the `UNEXPECTED` fallback (R2); red first.

### deploy-alerts.sh (service policies)

`jobs/deploy-alerts.sh` gains a log-match policy and a metric + threshold policy scoped to `resource.type="cloud_run_revision" AND resource.labels.service_name="grant-helpdesk"`, titles starting `BTB-ALERT bigtribebuilders`, the threshold one re-notifying every 24h.

*What it does:*
- R1: `jobs/alert_payloads.py` has `service_metric_log_filter(service)`, `service_log_match_policy(title, service, project, channel)` and `service_threshold_policy(title, service, project, channel, metric_name)`, shaped like the job ones but on `resource.type="cloud_run_revision"` + `resource.labels.service_name`.
- R2: the service log filter also requires the `BTB_ALERT grant-helpdesk/` prefix, because a service's logs are not scoped to one repo the way a job's are.
- R3: `jobs/deploy-alerts.sh` has a second block (`SERVICE="${SERVICE:-grant-helpdesk}"`) using the same create-or-update flow as the job block; metric `grant_helpdesk_btb_alert_count`. Re-running it changes nothing when the policies already match.

*Examples:* a `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: ...` line from the `grant-helpdesk` service -> one email with subject `BTB-ALERT bigtribebuilders ...`, again every 24h while open.

*Inputs / Outputs:* project, service, channel -> 1 log metric + 2 alert policies in Cloud Monitoring.

*Errors:* a policy on a brand-new metric may fail with "Cannot find metric(s)" for up to 10 minutes; re-run.

*Test:* `tests/test_deploy_alerts_payloads.py`, offline payload shapes (R1, R2); `bash -n jobs/deploy-alerts.sh`; red first. Live proof: a second run shows "exists and matches", then the fire drill.

### add_coach_reply(thread_id, author_member_id, body, client=None)

`def add_coach_reply(thread_id: str, author_member_id: int | None, body: str, client: bigquery.Client | None = None) -> ReplyResult`

`ReplyResult` is an enum: `OK`, `REFUSED`, `UNKNOWN_THREAD`, `WRITE_FAILED`. It replaces the bool agreed at the gate (changed 2026-09-28 after review: a bool could not tell a stale page from an outage).

*What it does:*
- R1: when given a thread id, the replying coach's MN member id and a body, it writes one row with a single parameterised `INSERT private_messages (...) SELECT @message_id, thread_id, 'coach', @author_member_id, @body, CURRENT_TIMESTAMP() FROM private_threads WHERE thread_id = @thread_id` (tables named from `config.PRIVATE_CHAT_DATASET`). `message_id` is a new uuid4 per call; `author_role` is the literal `'coach'`.
- R2: the body is stripped and must be 1-4000 chars, and `author_member_id` must not be None; otherwise it returns `REFUSED` before any query is sent.
- R3: when the query runs but writes zero rows (the thread does not exist), it returns `UNKNOWN_THREAD` and raises no alert.
- R4: when the query raises, it calls `report_source_failure("write", err)` and returns `WRITE_FAILED`.
- R5: `author_member_id` always comes from `grant_coaches` via the logged-in email (the admin has a row there too). Any coach may reply in any thread. The body never appears in any log line.
- R6: each member-question row in the Tickets tab has the regular action dropdown, offering "Answer" and underneath it "Close" (`set_thread_workflow` R5); "Answer" opens a dialog with the member's thread and the reply form (`reply_form.render_thread_and_reply`), followed by the member's history: their community tickets and their other private threads (`member_other_threads`), rendered by the same `member_history.render_member_history` the regular ticket dialog uses. A failed history lookup shows "History unavailable" and alerts, and the reply form still works. The form shows a distinct message for each result, keeps the typed text unless the result is `OK`, and on `OK` clears only the `load_member_questions` cache. A failed coach lookup shows `st.error`, alerts `SOURCE_FAILED`, and is not cached.
- R7: when a reply returns `OK`, the form closes the thread at once with `set_thread_workflow(thread_id, status="closed", updated_by=<the coach's email>)`. When that close does not return `OK`, the reply stays sent, the typed text is cleared, the thread shows as `answered`, and the coach reads "Answer sent, but the thread could not be closed". No reply result other than `OK` closes anything.

*Examples:* existing thread, body "Thanks, see the link" -> `OK`, one coach row. Body of spaces -> `REFUSED`, no query. Thread id not in `private_threads` -> `UNKNOWN_THREAD`, no alert. BigQuery raises `Forbidden` -> `WRITE_FAILED` plus stdout `{"severity": "ERROR", "message": "BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat write failed: Forbidden"}`.

*Inputs:* thread id, coach member id, body text, and an optional BigQuery client (tests pass a fake).

*Outputs:* a `ReplyResult`; on `OK`, one new row in `private_messages`.

*Errors:* BigQuery error or denied access -> `WRITE_FAILED`, UI `st.error` -> `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED`.

*Test:* `/opt/anaconda3/bin/python -m pytest tests/test_coach_inbox_reply.py` with a fake client: SQL shape and parameters (R1), 0/4001-char and None-author refusals send no query (R2), zero affected rows (R3), raising client -> exact alert line with the body absent (R4, R5), two calls -> two different message ids (R1); red first. UI: `tests/test_reply_form.py` (AppTest) covers R6's callback and `render_thread_and_reply` (an OK send reruns to close the dialog, counted in script runs); app.py's dropdown and dialog wiring is not under test and is checked by hand on Streamlit 1.58 after deploy. No live write drill: the unit tests prove the alert line, and the read drill proved the alert path end to end (Martin's decision, 2026-09-29).

### set_thread_workflow(thread_id, status, updated_by, client=None)

`def set_thread_workflow(thread_id: str, *, status: str, updated_by: str, client: bigquery.Client | None = None) -> WorkflowResult`

`WorkflowResult` is an enum: `OK`, `REFUSED`, `WRITE_FAILED`. The table is `bigtribebuilders.grant_helpdesk.private_thread_workflow (thread_id STRING, status STRING, assignee STRING, lane STRING, closed_at TIMESTAMP, updated_at TIMESTAMP, updated_by STRING)`, one row per `thread_id`, created by `migrations/018_private_thread_workflow.sql`. It is helpdesk-owned, so MERGE is allowed there.

*What it does:*
- R1: when given a thread id, `status="closed"` and who closes, it writes one parameterised `MERGE` into `private_thread_workflow` keyed on `@thread_id`, setting `status = 'closed'`, `closed_at = CURRENT_TIMESTAMP()`, `updated_at = CURRENT_TIMESTAMP()`, `updated_by = @updated_by`. A second close of the same thread updates that one row; it never adds a second.
- R2: `assignee` and `lane` are left NULL on a new row and untouched on an existing one.
- R3: `status` must be exactly `"closed"`, and `thread_id` and `updated_by` must not be empty; otherwise it returns `REFUSED` before any query is sent.
- R4: when the query raises, it calls `report_source_failure("workflow write", err)` and returns `WRITE_FAILED`. The statement never names `private_threads` or `private_messages`, so the insert-only code rule below keeps holding.
- R5: a member-question row's action dropdown offers `Answer`, then `Close`, whether or not a coach has answered. `Close` asks nothing: it calls R1 with the logged-in coach's email, and on `OK` clears only the `load_member_questions` cache and reruns, so the row leaves the open list. On `WRITE_FAILED` it shows `st.error` and the row stays. A row that is already `closed` offers only `Answer` and shows a `Closed` badge.
- R6: any coach may close any thread, and no reason is asked.

*Examples:* thread `t1`, never closed, `status="closed"`, `updated_by="coach@x.org"` -> `OK`, one row with `closed_at` now. The same call an hour later -> `OK`, still one row, `closed_at` moved. `status="open"` -> `REFUSED`, no query. BigQuery raises `NotFound` (migration not run) -> `WRITE_FAILED` plus stdout `{"severity": "ERROR", "message": "BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat workflow write failed: NotFound"}`.

*Inputs:* thread id, the status to set, the coach's email, and an optional BigQuery client (tests pass a fake).

*Outputs:* a `WorkflowResult`; on `OK`, one new or updated row in `private_thread_workflow`.

*Errors:* BigQuery error, denied access or missing table -> `WRITE_FAILED`, UI `st.error` -> `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED`.

*Test:* `/opt/anaconda3/bin/python -m pytest tests/test_coach_inbox_workflow.py` with a fake client: MERGE shape and parameters, and no `assignee` or `lane` in the SET list (R1, R2); wrong status, empty thread id and empty `updated_by` send no query (R3); raising client -> `WRITE_FAILED` and the exact alert line (R4); `tests/test_private_chat_insert_only.py` still green (R4); red first against `origin/main`, where the function does not exist. UI: `tests/test_reply_form.py` (AppTest) — an `OK` reply calls the close once, a non-`OK` reply never calls it, and a failed close after an `OK` reply shows the "could not be closed" message (`add_coach_reply` R7). The dropdown options (R5) are asserted from the list `app.py` builds; the click-through in `app.py` is checked by hand on the live app after deploy. No live fire drill: the alert line is proven in the unit tests and the alert path end to end by the 2026-09-28 read drill.

## Code rule: private_chat is insert-only

No source file in the repo may contain SQL that runs UPDATE, DELETE, MERGE, TRUNCATE, ALTER, DROP or CREATE against `private_chat`. `tests/test_private_chat_insert_only.py` scans every tracked `.py` for those keywords within a statement that names `private_messages` or `private_threads`, and fails naming file and line. Proven red first with a fixture file holding one `UPDATE ... private_messages`.

## Open check

1. Martin wrote that "any coach can react to a specific message". Check whether that means replying to one particular message inside a thread (the zone's `private_messages` has no reply-to column) or only to the thread. The design assumes the thread until he says otherwise.

## Decisions

- 2026-09-25: member questions live inside Tickets as a mixed list with a badge, not a separate tab (one place to work; "Inbox" is already the team-feedback tab).
- 2026-09-25: workflow (assign, lane, close) lives in a helpdesk-owned table keyed by `thread_id`; the zone tables stay insert-only and status-free.
- 2026-09-25: members hear of replies through the zone page; coaches through the tab count; no email either way.
- 2026-09-25: the admin may answer, as `author_role='coach'`; his MN member id comes from his own row in `grant_coaches`, and he shows in coach lists and assign dropdowns (accepted).
- 2026-09-25: a thread is private towards other members only; every coach sees every thread and any coach may reply in any thread, whoever it is assigned to.
- 2026-09-25: the unread badge counts waiting threads (the member wrote last), the same for all coaches, with nothing stored.
- 2026-09-25: every `private_chat` failure logs `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED`; no landing of list or reply box without the alert and a fire drill.
- 2026-09-25: re-notify needs a metric + threshold policy; a log-match policy rejects `notificationChannelStrategy` (found live 2026-09-24).
- 2026-09-28: `add_coach_reply` returns a `ReplyResult` enum instead of a bool, so the coach sees a different message for a refused body, a thread that no longer exists, and a real outage (review finding; Martin chose fix-and-re-review).
- 2026-09-28: read fire drill passed: a missing dataset gave `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat read failed: Forbidden` (13:25:21Z, revision 00065) and the email arrived. A missing dataset surfaces as `Forbidden`, not `NotFound`.
- 2026-09-29: no live write fire drill. Breaking `PRIVATE_CHAT_DATASET` breaks the read too, so no question row shows to reply to. Martin accepted the unit-test proof of the write alert over revoking the append role for a drill.
- 2026-09-29: the Answer dialog shows the member's history (community tickets, capped at the newest 20, plus their other private threads) through one shared `member_history.render_member_history`, the same code as the regular ticket dialog. The slow open was `get_followup_statuses` running on every rerun; it is now cached for 300 s and cleared after a follow-up is queued (Martin's request; landed 98ce387).
- 2026-10-05: sending a coach answer closes the thread by itself; a later member message brings it back as waiting. Why: an answered question is done until the member says otherwise, and coaches should not have to close by hand after every answer (Martin).
- 2026-10-05: `Close` sits under `Answer` on every member question, answered or not, and asks no reason. Why: a "thanks" or a duplicate needs no answer (Martin).
- 2026-10-05: a closed thread shows only under Status `closed`, like a closed community ticket, with its badge. Why: one rule for both kinds (Martin).
- 2026-10-05: this task builds close only; assign and lane for threads stay a later task, so `set_thread_workflow` accepts only `status="closed"` for now and returns a `WorkflowResult` instead of the `None` first sketched, for the same reason `add_coach_reply` returns a `ReplyResult`.
- 2026-10-05: an unreadable workflow table shows every thread as not closed rather than hiding the list. Why: a wrongly reopened thread costs a click, a hidden question costs a member an answer.
- 2026-10-05: the close time is the moment of the click (or of the sent answer), not the newest message the coach had on screen. A member message that arrives in the gap before the click — the list is up to 2 minutes old — is filed as closed, unseen; Martin accepted that gap after the review raised it.
