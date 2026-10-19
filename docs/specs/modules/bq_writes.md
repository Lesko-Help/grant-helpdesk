# bq_writes
Status: draft
Kind: helper
Summary: every INSERT, UPDATE and MERGE the app runs — what a coach's click records, and the one sweep that closes many tickets at once
Part of: `docs/specs/INDEX.md` · Deploy: `deploy.sh` (ships inside the app image) · Updated: 2026-10-19
Used by: `bq_client.py` (re-exports it with `from bq_writes import *`), and through it `app.py`
Reads: `grant_helpdesk.grant_tickets`, `grant_helpdesk.ticket_metadata`, `grant_helpdesk.followup_queue` — only to decide which rows to write
Writes: `grant_helpdesk.ticket_metadata`, `followup_queue`, `standard_replies`, `team_feedback`, and the coach and member lookup tables named in `config.py`

## Overview

*What it is for:* record what a coach did, so the next read shows it — writes
only, one function per action.
*What it owns:* the write side of `ticket_metadata`, `closed_at` and
`closed_by` included, and the bulk close sweep.
*What it depends on:* `config.py` for every table name, `followup_queue` for
the one row class a sweep must never touch, and — since 2026-10-19 —
`bq_reads.bulk_close_rows_sql` (`bq_reads.py:490`) for the shared row
selection. That import is a new edge between the two modules, chosen by Martin
over a third module `bq_base.py`, because R9 wants one copy of the selection
more than it wants a tidy dependency graph.
*Public entry points:* the eighteen below; `execute_bulk_close` is the only one
that writes more than one ticket per call.
*Not in scope:* member questions (private 1:1 threads), written by
`coach_inbox.set_thread_workflow` and `add_coach_reply`, never here. Nothing
here deletes a row; `archive_standard_reply` sets a flag.

## Functions

### execute_bulk_close(status_filter="answered", assigned_to="", before_date="", closed_by="")

- R1: community tickets only. It writes `ticket_metadata` keyed by `content_id`
  from `grant_tickets`, so a member's private thread can never be swept by it,
  whatever the filters say. Private threads close one at a time, through
  `coach_inbox.set_thread_workflow`.
- R2: the three filters AND together, and an empty string means *no constraint
  on that field* — never "match the empty value". All three empty is therefore
  "every open ticket", the widest sweep the function can do, and the one a
  coach reaches by leaving the form alone.
- R3: a ticket with any `pending` row in `followup_queue` is never closed,
  whatever the filters match. Why: that follow-up is a question already sent to
  the member, so closing discards an answer still on its way.
- R4: `closed`, `cancelled` and `archived` are all excluded, by effective
  status. `bq_reads.bulk_close_rows_sql` excludes all three, so neither the
  preview number nor the sweep touches an archived ticket;
  `tests/test_bulk_close.py::test_r4_*` guards it. `archived` was added on
  2026-10-19 (Martin) and was the one rule here whose test went red against
  live behaviour rather than against a missing helper.
- R5: the write is one `MERGE` on `content_id`. Matched, it sets
  `status='closed'`, `updated_at`, `closed_at`, `closed_by`; unmatched, it
  inserts a metadata row, carrying `assigned_to` and `domain` forward.
- R6: returns the rows the MERGE affected. A sweep that matches nothing returns
  0 and writes nothing; that is not an error.
- R7: `closed_by` must name the coach. It defaults to `""`, which writes an
  empty string, and then "who closed these forty?" has no answer. Callers pass
  `current_user`; a future change should make it required.
- R8: effective status here is `tm.status` falling back to `gt.ticket_status`,
  computed **without** the live reopen branch (`bq_reads._live_status_cte`). So
  a reopened ticket — closed metadata, a newer member message — reads `closed`
  here and is never swept, although the coach's list shows it open
  (`bq_reads.md` R1a). For a destructive sweep that is the safe direction, and
  it is deliberate, not an oversight.
- R9: **preview and execute must select the same rows.** Both call
  `bq_reads.bulk_close_rows_sql`, which builds the `base` CTE and the filtered
  SELECT once; the pending-follow-up predicate (R3) stays per caller (execute:
  `NOT IN`; preview: a LEFT JOIN with `COUNTIF`). `test_r9_*` asserts the
  helper's text sits inside what both callers send. `preview_bulk_close`
  (`bq_reads.py:544`, specified with this pair rather than with the reads)
  returns `{"will_close": N, "skipped_followup": M}`. The coach consents to a
  number; if the two drift, the app asks about one thing and does another.
- R10: filter values must reach BigQuery as query parameters. Today all four
  are interpolated into the SQL with ad-hoc quote stripping
  (`.replace("'", "")`) — not a safety boundary, and why the query breaks on a
  name like `O'Brien`. The dormant `bq-writes-params` worktree holds this.

*Examples:* `("answered", "", "", "coach@…")` -> every answered ticket with no
pending follow-up closes, credited to that coach, count returned.
`("", "coach@…", "2026-01-01", "coach@…")` -> only that coach's open tickets
created before 2026-01-01.

*Inputs:* an effective status or `""` for any; a coach's login email or `""`
for all; an ISO date (`YYYY-MM-DD`) or `""` for all dates; the closing coach.

*Outputs:* an `int`, the rows the MERGE affected.

*Errors:* a bad date or unparseable filter raises
`google.api_core.exceptions.BadRequest` and nothing is written, the MERGE being
one statement. No `BTB_ALERT`: this runs behind a coach's click, not on a
schedule, so a human sees the failure at once.

*Test:* `tests/test_bulk_close.py` guards R2, R3 (in both callers), R4 and R9,
on SQL strings with no BigQuery client; R7, R8 and R10 are not tested. 18
tests, run with:

```
PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q
```

Never bare `pytest tests/` — that runs `smoke_test.py`, which writes the live
`ticket_metadata`. R9's strongest guard reads
`tests/fixtures/bulk_close_sql_before.json`, the SQL both functions built
*before* the extraction, and compares line multisets for four filter sets
against both callers, pinning the only differences the extraction was allowed
to have (`'archived'` added, and the nesting). It bites: one extra column added
to the helper's `base` SELECT takes all eight of those cases red.

### preview_bulk_close(status_filter="answered", assigned_to="", before_date="")

*Lives in `bq_reads.py:490`; specified above as half of the pair — see R9.*

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

## Decisions

- 2026-10-19: written because `bq_writes.py` was owned by no spec at all
  (global rule 7, owned or gone), and because helpdesk-05 asks for bulk close
  in Conversations. Writing it established that the community-ticket version is
  **already built** — `execute_bulk_close`, UI at `app.py:1751`, Preview then
  confirm — so helpdesk-05 is an extension, not a new feature, and R7, R8 and
  R10 were found by reading the code, not by a coach hitting them.
- 2026-10-19: a bulk close is confirmed against a count, not a list. Preview,
  read "N will be closed, M skipped", press the button. R9 exists because that
  number is the whole of the consent: nobody re-reads forty rows, so the number
  must be true.
- 2026-10-19: `archived` is excluded from the sweep (Martin). An archived
  ticket is already out of every coach's list, so sweeping it closed changes
  nothing anyone sees and only moves numbers in reports that count by status —
  a silent edit to history. The three terminal-ish states now behave alike,
  which is the asymmetry a reader would otherwise have had to rediscover.
  Carried by R4, and in the code since `be289bf` (landed 2026-10-19).
- 2026-10-19: the Conversations version offers **status only** (Martin). Not
  coach — member questions carry no `assigned_to` and no lane, so there is
  nothing to filter on. Not an age either: "answered and untouched for N days"
  needs the same `closed_at` field the cut "answered 3d ago" age needed
  (`coach_inbox.md`, same date), so it would drag that column onto the thread
  queries before it could offer anything. One filter also keeps the sweep
  small, which is the right default for a destructive action nobody reviews
  row by row (R9).
- 2026-10-19: that version lives in `coach_inbox.py`, not here, and is
  specified in `coach_inbox.md`. R1 is why: a sweep keyed off the ticket tables
  must never be able to reach a private thread, so the thread sweep is a
  separate function closing through `set_thread_workflow`, with its own preview.
  It shares this spec's R2, R3, R6, R9 and R10 by reference rather than by
  copied code. The cost is that `coach_inbox.md` grows while already over
  STYLE R8 — which is an argument for splitting that spec, not for putting the
  function in the wrong module.
- 2026-10-19: the other seventeen functions here are grouped stubs, by what
  each group writes, not seventeen one-line sections. Why: a section each costs
  ~70 lines saying nothing, putting the file over STYLE R8's ~150 before a rule
  is written — and R8's answer to a long spec is to split the module. The
  groups are the seams a split would follow. The file is still well over R8's ~150, the
  excess being the ten invariants on the one destructive path and the decisions
  behind them; cutting those to reach a line count would be the wrong trade, so
  the overage stands and the split is Martin's call.
