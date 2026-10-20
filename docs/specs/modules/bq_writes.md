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

### execute_bulk_close(status_filter="answered", assigned_to="", before_date="", closed_by="", *, lane)

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
- R9: **preview and execute must select the same rows**, lane included (R11).
  Both call
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

- R11: **one lane per sweep.** Preview and execute each take a `lane` and
  constrain the selection to it, through the same live-lane expression the
  lists use (`bq_reads._live_lane_expr`: `tm.lane` when set, else `gt.lane`,
  else `question`), so the rows counted are the rows that tab shows. There is
  no default and no value meaning "both lanes": the button sits on a tab, the
  tab shows one lane, so a sweep that crosses lanes closes rows the coach never
  saw and never consented to. Today `bulk_close_rows_sql` carries no lane
  condition at all, so the Tickets-tab sweep already closes Conversations rows
  (`app.py:1880`, lane `general`) — making this, after R4, the second rule here
  whose test goes red against live behaviour rather than against a missing
  helper. `app.py` passes `config.LANE_QUESTION` from the Tickets tab and
  `config.LANE_GENERAL` from Conversations.
- R12: **the panel exists once.** The two tabs' bulk-close panels are one
  renderer taking the lane, not two copies, and every widget key plus the
  preview's session-state key carries the lane in it — both tabs render on the
  same Streamlit run, so a bare key like `bc_status` would be registered twice
  and Streamlit raises a duplicate-key error (the same reason `lane` is
  threaded through `render_ticket_table`, `app.py:1387`). Why one renderer: two
  copies drift, and R9's whole promise is that the number and the sweep agree.

*Examples:* `("answered", "", "", "coach@…", lane="question")` -> every
answered Tickets-lane ticket with no pending follow-up closes, credited to that
coach, count returned. `("", "coach@…", "2026-01-01", "coach@…",
lane="general")` -> only that coach's open Conversations-lane rows created
before 2026-01-01.

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

### preview_bulk_close(status_filter="answered", assigned_to="", before_date="", *, lane)

*Lives in `bq_reads.py:544`; specified above as half of the pair — see R9.*

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
- 2026-10-20: **the two 2026-10-19 decisions below were wrong about what
  "Conversations" is, and are replaced by this one and the next.** The app's
  Conversations tab (`app.py:1880`) is `load_tickets(lane=config.LANE_GENERAL)`
  — community posts and comments that are not grant questions, in *these same*
  tables, carrying status, `assigned_to`, domain and urgency like any ticket.
  The Tickets tab is the same code with `lane="question"`. Members' private 1:1
  questions are not on that tab at all: they merge into Tickets, and their
  status is derived in Python from who wrote last (`coach_inbox.py:135`), never
  stored. So bulk close for Conversations is this sweep scoped to a lane (R11),
  needs nothing in `coach_inbox.py`, and cannot reach a private thread — R1
  holds unchanged, for the reason it always did.
- 2026-10-20: the Conversations sweep offers **the same three filters as
  Tickets** (Martin), reusing the one panel with a lane argument (R12). This
  replaces "status only" (2026-10-19), whose recorded reason — "one filter
  keeps the sweep small" — was backwards: a filter narrows a sweep, so offering
  fewer of them makes the default sweep wider, and it would have cost a second
  panel to build. An age filter stays out, for the reason first given: "answered
  and untouched for N days" needs the `closed_at` column the cut "answered 3d
  ago" age needed (`coach_inbox.md`, 2026-10-19).
- 2026-10-20: a bulk close over members' private 1:1 threads is **not built
  and not asked for.** It would be a separate function in `coach_inbox.py`
  closing through `set_thread_workflow`, and it could not reuse the SQL here at
  all, because a thread's status is derived per read in Python rather than
  stored in a column. Written down because the 2026-10-19 pair of decisions
  promised that function in `coach_inbox.md`, where no such section exists.
- 2026-10-19: the other seventeen functions here are grouped stubs, by what
  each group writes, not seventeen one-line sections. Why: a section each costs
  ~70 lines saying nothing, putting the file over STYLE R8's ~150 before a rule
  is written — and R8's answer to a long spec is to split the module. The
  groups are the seams a split would follow. The file is still well over R8's ~150, the
  excess being the ten invariants on the one destructive path and the decisions
  behind them; cutting those to reach a line count would be the wrong trade, so
  the overage stands and the split is Martin's call.
