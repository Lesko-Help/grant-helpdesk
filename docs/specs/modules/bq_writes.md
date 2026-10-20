# bq_writes
Status: agreed
Kind: helper
Summary: every INSERT, UPDATE and MERGE behind a coach's click — one ticket, one follow-up, one coach, one reply at a time
Part of: `docs/specs/INDEX.md` · Deploy: `deploy.sh` (ships inside the app image) · Updated: 2026-10-20
Used by: `bq_client.py` (re-exports it with `from bq_writes import *`), and through it `app.py`
Reads: `grant_helpdesk.grant_tickets`, `grant_helpdesk.ticket_metadata` — only to decide which rows to write
Writes: `grant_helpdesk.ticket_metadata`, `followup_queue`, `standard_replies`, `team_feedback`, and the coach and member lookup tables named in `config.py`

## Overview

*What it is for:* record what a coach did, so the next read shows it — writes
only, one function per action, one ticket per call.
*What it owns:* the write side of `ticket_metadata`, `closed_at` and
`closed_by` included, for single-row writes.
*What it depends on:* `config.py` for every table name.
*Public entry points:* the seventeen below, each writing one row or one small
set of rows for one click.
*Not in scope, though the code sits in this file:* `execute_bulk_close`, the
one function here that writes many tickets per call. It is owned by
`docs/specs/modules/bulk_close.md` together with the two `bq_reads.py`
functions and the `app.py` panel it works with — a task touching it names
`bulk_close` as its `WT_MODULE`, not this spec. That is also where the
`bq_reads.bulk_close_rows_sql` import at the top of this file is explained.
*Also not in scope:* member questions (private 1:1 threads), written by
`coach_inbox.set_thread_workflow` and `add_coach_reply`, never here. Nothing
here deletes a row; `archive_standard_reply` sets a flag.

## Functions

### One ticket at a time

*Signatures:* `update_ticket_meta(content_id, status, assigned_to, domain=None,
feedback_reason=None, closed_by=None)` · `set_ticket_lane(content_id, lane,
feedback_reason=None)` · `set_ticket_assignee(content_id, assigned_to)` ·
`post_comment(content_id, author, body)`

<!-- spec:stub -->

### Follow-ups

*Signatures:* `queue_followup(ticket_id, content_id, content_type, member_id,
member_name, message, days, scheduled_by)` ·
`update_followup_status(followup_id, status, **kwargs)`

<!-- spec:stub -->

### Coaches and assignment

*Signatures:* `add_grant_coach(member_id, full_name, email, added_by)` ·
`remove_grant_coach(member_id)` · `link_coach_login_email(member_id,
login_email)` · `set_member_assignment_override(member_id, assigned_to,
updated_by)` · `trigger_assignment_refresh()`

<!-- spec:stub -->

### Standard replies

*Signatures:* `save_standard_reply(reply_id, title, body, saved_by)` ·
`archive_standard_reply(reply_id)`

<!-- spec:stub -->

### Team feedback

*Signatures:* `submit_team_feedback(submitted_by, feedback_type, title, body)` ·
`reply_team_feedback(feedback_id, reply_text, replied_by, new_status)`

<!-- spec:stub -->

### Settings and events

*Signatures:* `save_mn_api_key(email, api_key)` · `log_rsvp(content_id,
event_id, member_id, rsvped_by)`

<!-- spec:stub -->

### execute_bulk_close(...)

*Lives in this file, specified in `docs/specs/modules/bulk_close.md`.*

## Open check

- `datetime.utcnow()` is deprecated and used at `bq_writes.py:161`, `:226` and
  `:283`; the deploy's own test run prints the warning. Not yet scheduled.

## Decisions

- 2026-10-20: the bulk close sweep moved out to
  `docs/specs/modules/bulk_close.md` (Martin). This file had reached 249 lines
  against STYLE R8's ~150, and nearly all the overage was the sweep: twelve
  invariants on one destructive path, plus the decisions behind them. The split
  also fixes an ownership mismatch rather than only a line count — the sweep is
  four functions across three files (`app.py`, `bq_reads.py`, `bq_writes.py`),
  so a spec named after one of those files was never the right owner, and
  `WT_MODULE` names the spec that owns the function, not the file it sits in.
  What stayed here is what the name means: the single-row writes.
- 2026-10-19: written because `bq_writes.py` was owned by no spec at all
  (global rule 7, owned or gone).
- 2026-10-19: the seventeen functions here are grouped stubs, by what each
  group writes, not seventeen one-line sections. Why: a section each costs ~70
  lines saying nothing, putting the file over STYLE R8's ~150 before a rule is
  written. The groups are the seams a further split would follow, if one is
  ever wanted.
