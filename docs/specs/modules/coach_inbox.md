# coach_inbox
Status: agreed 2026-10-19 (approved by Martin)
Kind: app
Summary: coaches see members' private questions from the questions zone inside the Tickets tab, answer them there, and close them by hand when the question is done

Part of: `docs/specs/INDEX.md` · Deploy: `deploy.sh` (app), `jobs/deploy-alerts.sh` (alert) · Updated: 2026-10-19

## Overview

Coaches see members' private questions (from the questions zone) inside the Tickets tab, answer them there, and close them by hand with the row's `Close` action when the question is done.
Owns: `coach_inbox.py`, the Cloud Run service's BTB_ALERT policies, and `grant_helpdesk.private_thread_workflow`. Both `raillog.py` copies are owned by `docs/specs/modules/raillog.md`.
Reads `lesko-486515.private_chat.private_threads` / `private_messages` (EU, owned by the zone) and `bigtribebuilders.dataform.core_members` for names.
Entry points: `load_member_questions`, `waiting_count`, `merge_into_tickets`, `report_source_failure`, `add_coach_reply`, `set_thread_workflow`, and the answer dialog's `reply_form.render_thread_and_reply`.
*Not in scope:* assigning a thread to a coach or moving it to a lane (the table has the columns; a later task), choosing which standard replies a dialog offers (every dialog offers all of them), telling members of a reply (the zone shows it on next load), emailing coaches, any change to `private_chat`'s schema or grants, a heartbeat (the app is not scheduled).

Who: coaches and the admin · Where: Streamlit, the Tickets tab of the grant-helpdesk app

## Screens

### Tickets tab: member-question rows

- Shows each 1:1 thread as a row among the community tickets, with a `Member question` badge, a `waiting`, `Answered` or `Closed` badge, and an action dropdown offering `Answer` then `Close` (only `Answer` once closed). The tab label counts the waiting threads. A thread the coach has answered stays in the list as `Answered`, above the community tickets' usual ordering only while it is `waiting`; a closed thread shows under Status `closed` and under Status `All` (`merge_into_tickets` R4).
- Reads / Writes: reads `private_threads`, `private_messages`, `core_members` and `private_thread_workflow`; `Close` writes `private_thread_workflow`.
- Error view: threads unreadable -> `st.error` and the community tickets still show; workflow table unreadable -> the threads show, none as closed; a failed `Close` -> `st.error` and the row stays.

### Answer dialog

- Shows the member's thread, an "Insert standard reply" dropdown above the reply box, the reply form, and the member's history (community tickets and other private threads). Sending a reply closes the dialog and leaves the thread open, now `Answered`, in the coach's list, so the next answer is one `Answer` click away.
- Reads / Writes: reads the same tables plus the member's community tickets; a reply inserts one row into `private_messages` and writes nothing to `private_thread_workflow` — only the row's `Close` action writes there.
- Error view: a distinct message per reply result with the typed text kept; "History unavailable" when the history lookup fails, with the reply form still working. No close happens here, so there is no close-failure message.

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
- R4: the sidebar Status filter is applied to member questions by `coach_inbox.filter_questions_by_status` (`coach_inbox.py:452`, called from `app.py:1784`) before the merge: `All` shows every member question, the closed ones included, so a thread a coach closed is still findable where coaches look; `closed` shows only the closed ones; every other Status choice shows the ones that are not closed *(as-built: member questions ignore the rest of the Status filter — a thread has no `answered`/`flagged`/`cancelled` state of its own)*. For a thread, terminal means exactly `closed`: `config.TERMINAL_STATUSES` is `["closed", "cancelled", "archived"]` (`config.py:42`) and `set_thread_workflow` R3 accepts only `"closed"`, so `cancelled` and `archived` can never apply to one. Community tickets still hide `closed` and `archived` under `All` (`bq_reads.get_tickets`, `bq_reads.py:138`); the two kinds differ here on purpose (Decisions, 2026-10-19).
- R3: sidebar filters that have no meaning for a thread (urgency, domain, space) leave member questions out only when the filter is set to something other than "All".

*Examples:* 2 tickets + 1 waiting question -> 3 rows, the question first. 1 waiting + 1 answered + 1 closed question, Status `All` -> all 3 kept; Status `closed` -> only the closed one; Status `open` -> the waiting and the answered one.

*Inputs / Outputs:* two frames -> one frame with a `source` column (`ticket` / `member_question`).

*Errors:* none (pure).

*Test:* `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_coach_inbox.py -q`, fixture frames -> order (R1) and `source` values (R2); a frame of one waiting, one answered and one closed question through `filter_questions_by_status` -> 3 rows under `"All"`, only the closed row under `"closed"`, the two non-closed rows under `"open"` and under `"answered"` (R4); red first against `origin/main`, where `"All"` returns 2 rows and silently drops the closed one. Never bare `pytest tests/` — `tests/smoke_test.py` writes the live `ticket_metadata` table.

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
- R6: each member-question row in the Tickets tab has the regular action dropdown, offering "Answer" and underneath it "Close" (`set_thread_workflow` R5); "Answer" opens a dialog with the member's thread, the standard-reply picker and the reply form (`reply_form.render_thread_and_reply`, below), followed by the member's history: their community tickets and their other private threads (`member_other_threads`), rendered by the same `member_history.render_member_history` the regular ticket dialog uses. A failed history lookup shows "History unavailable" and alerts, and the reply form still works. The form shows a distinct message for each result, keeps the typed text unless the result is `OK`, and on `OK` clears only the `load_member_questions` cache. A failed coach lookup shows `st.error`, alerts `SOURCE_FAILED`, and is not cached.
- R7: a reply never closes the thread. When a reply returns `OK` the form clears the box, clears the `load_member_questions` cache and reruns to shut the dialog; the thread's derived status becomes `answered` (`load_member_questions` R3), the row stays in the coach's list with `Answer` still on it, and the same coach can answer again without waiting for the member. Nothing is written to `private_thread_workflow` on the reply path — a thread closes only through the row's `Close` action (`set_thread_workflow` R5). `reply_form.on_reply_submit` and `reply_form.render_thread_and_reply` therefore take no `close_thread` callable, `app.py`'s Answer dialog passes none, and the "Answer sent, but the thread could not be closed" message no longer exists.

*Examples:* existing thread, body "Thanks, see the link" -> `OK`, one coach row, no `private_thread_workflow` row, the thread now `answered` and still listed. Body of spaces -> `REFUSED`, no query. Thread id not in `private_threads` -> `UNKNOWN_THREAD`, no alert. BigQuery raises `Forbidden` -> `WRITE_FAILED` plus stdout `{"severity": "ERROR", "message": "BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat write failed: Forbidden"}`.

*Inputs:* thread id, coach member id, body text, and an optional BigQuery client (tests pass a fake).

*Outputs:* a `ReplyResult`; on `OK`, one new row in `private_messages`.

*Errors:* BigQuery error or denied access -> `WRITE_FAILED`, UI `st.error` -> `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED`.

*Test:* `/opt/anaconda3/bin/python -m pytest tests/test_coach_inbox_reply.py` with a fake client: SQL shape and parameters (R1), 0/4001-char and None-author refusals send no query (R2), zero affected rows (R3), raising client -> exact alert line with the body absent (R4, R5), two calls -> two different message ids (R1); red first. UI: `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_reply_form.py -q` (AppTest) covers R6's callback and `render_thread_and_reply` (an OK send reruns to close the dialog, counted in script runs); for R7, a fixed script calling `on_reply_submit` with its seven arguments and `coach_inbox.set_thread_workflow` monkeypatched to a recorder -> the recorder stays empty on an `OK` reply, the box clears, and no error shows; and `"could not be closed"` appears nowhere in `reply_form.py`'s source. Red first against `origin/main`, where the seven-argument call raises `TypeError` for the missing `close_thread` and the recorder would hold one call. app.py's dropdown and dialog wiring is not under test and is checked by hand on Streamlit 1.58 after deploy. No live write drill: the unit tests prove the alert line, and the read drill proved the alert path end to end (Martin's decision, 2026-09-29).

### render_thread_and_reply(thread_id, messages, body_key, result_key, current_user, lookup_author, add_reply, clear_cache, std_reply_picker=None)

`def render_thread_and_reply(thread_id, messages, body_key, result_key, current_user, lookup_author, add_reply, clear_cache, std_reply_picker=None) -> None`

It draws the member 1:1 answer dialog's body: the thread, the standard-reply
picker, the reply form, and the outcome of the last send.

*What it does:*
- R1: all three answer dialogs offer the same picker — the ticket dialog (`app.py:752`), the group-comment dialog (`app.py:1084`) and the member 1:1 dialog (here, `app.py:1259`). All three call the one helper `app.py:_std_reply_picker(sel_key, target_key)` (`app.py:566`), which reads the one cached `_cached_standard_replies()` (`app.py:541`). No dialog keeps a picker of its own, so the three cannot drift apart, and the titles offered are always the same list.
- R2: `reply_form` never imports `app`, because it has to stay runnable under `AppTest` (its module docstring's reason). So the picker arrives as an optional callable: when `std_reply_picker` is given, it is called once as `std_reply_picker(f"stdreply_{body_key}", body_key)` before the form; when it is `None`, no dropdown is drawn and the dialog behaves exactly as before.
- R3: the picker is drawn *above* `st.form`, never inside it. Streamlit allows an `on_change` callback only on a form's own submit button, so a selectbox inside the form would raise `StreamlitAPIException` and never fire.
- R4: inserting *appends*: the picked template is added below whatever the reply box has already committed to `session_state`, separated by one blank line, and the dropdown resets to `— insert a standard reply —` so the same template can be picked again. It never replaces and never inserts at the cursor. Why: a coach typically opens with a line of her own and then the template, and a Streamlit text area has no undo, so a replace would silently destroy typed words.
- R5: the reply box stays inside `st.form` (`reply_form.py:100`), and a form commits its text to `session_state` only when the coach presses Send. So the append lands below the last *sent* text, not below whatever is on screen: a coach who types without sending and then picks a template sees the template on its own, and her unsent typing does not come back. The picker's help text therefore reads "Adds the template to the box — pick it first, then edit". Taking the box out of the form is out of scope: it changes the send path `on_reply_submit` is built around.
- R6: the picker draws nothing at all when there are no standard replies, or when loading them raises — the load failure is logged through `bq_client.log_event("ERROR", "std_replies.load", ...)` (`app.py:571`) and the reply form still works. A missing picker never blocks an answer.

*Examples:* three saved replies, nothing committed in the box, "Grant deadline" picked -> the box holds that body, dropdown back on the placeholder. `session_state[body_key]` already `Hi Jane,` from an earlier send, the same pick -> `Hi Jane,\n\n<body>`. No saved replies -> no dropdown, reply form unchanged. `std_reply_picker=None` -> no dropdown.

*Inputs:* the thread id; its messages oldest first; the reply box's and outcome's session_state keys; the coach's email; the three dependency callables `on_reply_submit` needs (author lookup, the write, the cache to clear on success — there is no close callable, `add_coach_reply` R7); and optionally the picker callable (tests pass a fake that records its arguments).

*Outputs:* none — it draws the dialog, and on a successful send calls `st.rerun()` as before.

*Errors:* standard replies unreadable -> no dropdown, one `log_event("ERROR", "std_replies.load", ...)` row, no `BTB_ALERT` (a missing template list costs a coach keystrokes, not a member an answer).

*Test:* `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_reply_form.py -q` from the repo root — never bare `pytest tests/`, `tests/smoke_test.py` writes the live `ticket_metadata` table. Fixtures: the existing `_dialog_script` AppTest harness plus a fake picker that records `(sel_key, target_key)` and the widget order. Observed: the fake called exactly once with `("stdreply_reply_body", "reply_body")` and before the form (R1, R2, R3); `std_reply_picker=None` draws one text_area and no selectbox (R2); a pick with `session_state["reply_body"]` already set gives `typed\n\nbody` and the selectbox back on the placeholder (R4, R5); a picker that raises leaves the form sendable (R6); and an `ast` walk of `app.py` finds exactly three `_std_reply_picker` calls with none in `reply_form.py` (R1). Red first against `origin/main`, where the parameter does not exist and the 1:1 dialog draws no dropdown.

### set_thread_workflow(thread_id, status, updated_by, client=None)

`def set_thread_workflow(thread_id: str, *, status: str, updated_by: str, client: bigquery.Client | None = None) -> WorkflowResult`

`WorkflowResult` is an enum: `OK`, `REFUSED`, `WRITE_FAILED`. The table is `bigtribebuilders.grant_helpdesk.private_thread_workflow (thread_id STRING, status STRING, assignee STRING, lane STRING, closed_at TIMESTAMP, updated_at TIMESTAMP, updated_by STRING)`, one row per `thread_id`, created by `migrations/018_private_thread_workflow.sql`. It is helpdesk-owned, so MERGE is allowed there.

*What it does:*
- R1: when given a thread id, `status="closed"` and who closes, it writes one parameterised `MERGE` into `private_thread_workflow` keyed on `@thread_id`, setting `status = 'closed'`, `closed_at = CURRENT_TIMESTAMP()`, `updated_at = CURRENT_TIMESTAMP()`, `updated_by = @updated_by`. A second close of the same thread updates that one row; it never adds a second.
- R2: `assignee` and `lane` are left NULL on a new row and untouched on an existing one.
- R3: `status` must be exactly `"closed"`, and `thread_id` and `updated_by` must not be empty; otherwise it returns `REFUSED` before any query is sent.
- R4: when the query raises, it calls `report_source_failure("workflow write", err)` and returns `WRITE_FAILED`. The statement never names `private_threads` or `private_messages`, so the insert-only code rule below keeps holding.
- R5: a member-question row's action dropdown offers `Answer`, then `Close`, whether or not a coach has answered. `Close` is the only thing that closes a thread (`add_coach_reply` R7) and asks nothing: it calls R1 with the logged-in coach's email, and on `OK` clears only the `load_member_questions` cache and reruns, so the row leaves the working list but stays visible under Status `All` and Status `closed` (`merge_into_tickets` R4). On `WRITE_FAILED` it shows `st.error` and the row stays. A row that is already `closed` offers only `Answer` and shows a `Closed` badge; answering it leaves it closed, and `load_member_questions` R5 still reopens it when the member writes again.
- R6: any coach may close any thread, and no reason is asked.

*Examples:* thread `t1`, never closed, `status="closed"`, `updated_by="coach@x.org"` -> `OK`, one row with `closed_at` now. The same call an hour later -> `OK`, still one row, `closed_at` moved. `status="open"` -> `REFUSED`, no query. BigQuery raises `NotFound` (migration not run) -> `WRITE_FAILED` plus stdout `{"severity": "ERROR", "message": "BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: private_chat workflow write failed: NotFound"}`.

*Inputs:* thread id, the status to set, the coach's email, and an optional BigQuery client (tests pass a fake).

*Outputs:* a `WorkflowResult`; on `OK`, one new or updated row in `private_thread_workflow`.

*Errors:* BigQuery error, denied access or missing table -> `WRITE_FAILED`, UI `st.error` -> `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED`.

*Test:* `/opt/anaconda3/bin/python -m pytest tests/test_coach_inbox_workflow.py` with a fake client: MERGE shape and parameters, and no `assignee` or `lane` in the SET list (R1, R2); wrong status, empty thread id and empty `updated_by` send no query (R3); raising client -> `WRITE_FAILED` and the exact alert line (R4); `tests/test_private_chat_insert_only.py` still green (R4); red first against `origin/main`, where the function does not exist. UI: `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_reply_form.py -q` (AppTest) — no reply result of any kind reaches `set_thread_workflow`, proven with it monkeypatched to a recorder that must stay empty (`add_coach_reply` R7); the three tests that asserted the old close (`..._success_closes_the_thread_once`, `..._non_ok_never_calls_close_thread`, `..._success_with_failed_close_still_clears_but_warns`) are replaced by it. Red first against `origin/main`, where the first of those recorded one call. The dropdown options (R5) are asserted from the list `app.py` builds; the click-through in `app.py` is checked by hand on the live app after deploy. No live fire drill: the alert line is proven in the unit tests and the alert path end to end by the 2026-09-28 read drill.

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
- 2026-10-05: sending a coach answer closed the thread by itself; a later member message brought it back as waiting. Why: an answered question was taken to be done until the member said otherwise, and coaches were not to close by hand after every answer (Martin). Reversed 2026-10-19, below.
- 2026-10-05: `Close` sits under `Answer` on every member question, answered or not, and asks no reason. Why: a "thanks" or a duplicate needs no answer (Martin).
- 2026-10-05: a closed thread showed only under Status `closed`, like a closed community ticket, with its badge. Why: one rule for both kinds (Martin). Narrowed 2026-10-19, below: Status `All` shows it too.
- 2026-10-05: this task builds close only; assign and lane for threads stay a later task, so `set_thread_workflow` accepts only `status="closed"` for now and returns a `WorkflowResult` instead of the `None` first sketched, for the same reason `add_coach_reply` returns a `ReplyResult`.
- 2026-10-05: an unreadable workflow table shows every thread as not closed rather than hiding the list. Why: a wrongly reopened thread costs a click, a hidden question costs a member an answer.
- 2026-10-05: the close time is the moment of the click (or of the sent answer), not the newest message the coach had on screen. A member message that arrives in the gap before the click — the list is up to 2 minutes old — is filed as closed, unseen; Martin accepted that gap after the review raised it.
- 2026-10-15: the `### raillog.alert` section and the ownership of the root `raillog.py` copy move to `docs/specs/modules/raillog.md`. Why: `jobs/raillog.py` was owned by no spec at all, so the pair of copies had no one place to be described and no owner (the global rule 7, owned or gone). This spec keeps `report_source_failure`, which is what decides when a `private_chat` failure is alerted; the line's shape is the helper's.
- 2026-10-19: the member 1:1 answer dialog gets the standard-reply picker the ticket and group dialogs already had. Why: staff asked for it — a coach answering a private question today types by hand the same answer she can insert with one click two dialogs over.
- 2026-10-19: inserting a standard reply appends below the text already committed in the box and never replaces it, in all three dialogs. Why: a text area has no undo, so a replace can silently destroy a coach's own opening line (this is also what `_insert_std_reply` already does, now written down).
- 2026-10-19: the reply box stays inside `st.form`, so the picker appends below the last *sent* text and its help text says "pick it first, then edit". Why: moving the box out of the form would change the send path `on_reply_submit` is built around, a bigger change than the picker is worth; explicitly out of scope (Martin).
- 2026-10-19: the picker reaches `reply_form` as an optional callable argument instead of an import. Why: `reply_form` must stay importable under `AppTest`, which `app.py` is not, and one shared `_std_reply_picker` in `app.py` keeps the three dialogs from drifting.
- 2026-10-19: a coach's reply no longer closes the thread; `Close` is the only way a thread closes (Martin chose option (a), stop auto-closing, over an age-based close). Why the 2026-10-05 design broke: it assumed one answer ends a question, but a coach answers twice — a correction, a promised link, a reply to their own follow-up — and the safety valve was the *member* writing again, which often never happens, so the coach's own thread left the list with nothing to bring it back.
- 2026-10-19: what keeps the coach's list short is now order and the badge, not rows disappearing: the tab count has always counted `waiting` only (`waiting_count` R1), so the queue of work never grew by this change; `merge_into_tickets` R1 floats `waiting` rows above everything and lets `answered` ones sink by `last_activity_at`; and `Close` stays one click away on every row, now worth using because a closed thread is still findable under `All`. Auto-close was shortening the history, not the queue.
- 2026-10-19: if order and the badge turn out not to be enough, the next lever is display-only — `answered` threads with no member activity for 14 days folded into a collapsed "Settled" group below the live rows — and never another automatic status write, since the write is what made a thread unfindable. Decided on evidence: the count of `answered` threads with no member message for 14+ days, two weeks after landing.
- 2026-10-19: Status `All` shows closed member questions, which gives up the 2026-10-05 "one rule for both kinds" parity — community tickets still hide `closed` and `archived` under `All` (`bq_reads.get_tickets`, `bq_reads.py:138`). Why: a thread is one member's running conversation that a coach must be able to re-read and answer again, and `All` is the only place a coach thinks to look; whether community tickets should follow is a separate task, not this one.
- 2026-10-19: `load_member_questions` R5 (a member message newer than `closed_at` reopens the thread as `waiting`) stays unchanged, now as the valve for hand-closed threads only.
- 2026-10-19: for a private thread, terminal is exactly `closed`. The staff ask claimed `config.TERMINAL_STATUSES` was `['closed','cancelled','not_a_question','confirmed_question']`; `config.py:42` reads `["closed", "cancelled", "archived"]`, and `set_thread_workflow` R3 writes only `"closed"`, so `cancelled` and `archived` are ticket-only. The stale list is still readable in `migrations/010_fold_legacy_status_values.sql`'s header comment, which is where it most likely came from; `not_a_question`/`confirmed_question` are feedback values (`bq_reads.py:799`), not statuses.
- 2026-10-19: `render_thread_and_reply`'s signature above is the end state, and it arrives in two landings: the picker landing adds `std_reply_picker=None` while `close_thread` is still a parameter, then the no-auto-close landing removes `close_thread`. Why written down: between the two, a reader diffing this section against `reply_form.py` finds one argument that does not match, and that is the gap between the landings, not an error in either.
