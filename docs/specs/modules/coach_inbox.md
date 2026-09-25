# coach_inbox
Status: agreed 2026-09-25 (approved by Martin)
Kind: app

Part of: `docs/specs/INDEX.md` · Deploy: `deploy.sh` (app), `jobs/deploy-alerts.sh` (alert) · Updated: 2026-09-25

## Overview

Coaches see members' private questions (from the questions zone) inside the Tickets tab, and later answer them.
Owns: `coach_inbox.py`, the root `raillog.py` copy, the Cloud Run service's BTB_ALERT policies, and (later) `grant_helpdesk.private_thread_workflow`.
Reads `lesko-486515.private_chat.private_threads` / `private_messages` (EU, owned by the zone) and `bigtribebuilders.dataform.core_members` for names.
Entry points: `load_member_questions`, `waiting_count`, `merge_into_tickets`, `report_source_failure`, `raillog.alert`; later `add_coach_reply`, `set_thread_workflow`.
*Not in scope:* telling members of a reply (the zone shows it on next load), emailing coaches, any change to `private_chat`'s schema or grants, a heartbeat (the app is not scheduled).

## Functions

### load_member_questions(client=None)

`def load_member_questions(client: bigquery.Client | None = None) -> pd.DataFrame`

*What it does:*
- R1: when called, it reads every thread with its messages in one parameterised query (tables named from `config.PRIVATE_CHAT_DATASET`, default `lesko-486515.private_chat`) and returns one row per thread.
- R2: each row carries `content_id = "pc:" + thread_id`, `source = "member_question"`, `member_id`, `member_name` (from `core_members`, else `"Member <id>"`), `topic`, `subject`, `created_at`, `last_activity_at`, `messages` (list, oldest first), `status`.
- R3: `status` is derived, never stored: newest message by `created_at` is `member` -> `waiting`, `coach` -> `answered`.
- R4: when the read raises, it calls `report_source_failure("read", err)` and returns an empty frame with the same columns, so the Tickets tab still renders its MN tickets.

*Examples:* one thread, messages member then coach -> one row, `status="answered"`. Empty tables -> empty frame, no alert.

*Inputs:* an optional BigQuery client (tests pass a fake).

*Outputs:* a DataFrame, one row per thread.

*Errors:* BigQuery error or denied access -> empty frame, UI shows `st.error` -> `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED`.

*Test:* `/opt/anaconda3/bin/pytest tests/test_coach_inbox.py` in `.claude/worktrees/coach-inbox-list`, fake client seeded with two threads -> R1-R3 rows asserted; fake client that raises -> R4 empty frame and one captured `BTB_ALERT` line; red first against `origin/main`.

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
- R2: member-question rows render with a `Member question` badge, their messages HTML-escaped, and no action dropdown until the workflow slice lands.
- R3: sidebar filters that have no meaning for a thread (urgency, domain, space) leave member questions out only when the filter is set to something other than "All".

*Examples:* 2 tickets + 1 waiting question -> 3 rows, the question first.

*Inputs / Outputs:* two frames -> one frame with a `source` column (`ticket` / `member_question`).

*Errors:* none (pure).

*Test:* same command and file, fixture frames -> order (R1) and `source` values (R2); red first against `origin/main`.

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

<!-- spec:stub -->

### deploy-alerts.sh (service policies)

`jobs/deploy-alerts.sh` gains a log-match policy and a metric + threshold policy scoped to `resource.type="cloud_run_revision" AND resource.labels.service_name="grant-helpdesk"`, titles starting `BTB-ALERT bigtribebuilders`, the threshold one re-notifying every 24h.

<!-- spec:stub -->

### add_coach_reply(thread_id, author_member_id, body)

`def add_coach_reply(thread_id: str, author_member_id: int, body: str) -> bool`

<!-- spec:stub -->

Agreed rules, to be filled into R-lines by the reply slice: INSERT only, as `INSERT private_messages (...) SELECT @message_id, thread_id, 'coach', @author_member_id, @body, CURRENT_TIMESTAMP() FROM private_threads WHERE thread_id = @thread_id`; `message_id` is a new uuid4; body stripped, 1-4000 chars, else refused before any query; returns False when zero rows were written (unknown thread); `author_member_id` always from `grant_coaches` (the admin has a row there too); any coach may reply in any thread; never logs the body.

### set_thread_workflow(thread_id, status, assignee, lane)

`def set_thread_workflow(thread_id: str, *, status=None, assignee=None, lane=None) -> None`

<!-- spec:stub -->

Agreed shape: one row per `thread_id` in `bigtribebuilders.grant_helpdesk.private_thread_workflow (thread_id STRING, status STRING, assignee STRING, lane STRING, closed_at TIMESTAMP, updated_at TIMESTAMP, updated_by STRING)`, created by a file in `migrations/`. It is helpdesk-owned, so MERGE is allowed there. A member message newer than `closed_at` shows the thread as waiting again.

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
