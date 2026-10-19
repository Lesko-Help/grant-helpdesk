# bq_reads
Status: agreed 2026-10-19
Kind: helper
Summary: every SELECT the app runs — the ticket list, one ticket's detail, the KPI cards and the report tables — each joined live to `ticket_metadata` so a coach's last click is already in the answer
Part of: `docs/specs/INDEX.md` · Deploy: `deploy.sh` (ships inside the app image) · Updated: 2026-10-19
Used by: `bq_client.py` (re-exports it with `from bq_reads import *`), and through it `app.py` and `coach_inbox.py`
Reads: `grant_helpdesk.grant_tickets`, `grant_helpdesk.ticket_metadata`, `grant_helpdesk.app_logs`, and the lookup tables named in `config.py`
Writes: nothing — everything here is a SELECT; writes live in `bq_writes.py`

## Overview

*What it is for:* answer the app's questions about tickets without waiting for
the nightly Dataform rebuild of `grant_tickets`.
*What it owns:* the live join onto `ticket_metadata`, and the two values derived
on top of it — a ticket's live status and its urgency.
*What it depends on:* `bq_base.py` for the client, `_tickets_cols()` and the
schema-retry wrapper; `config.py` for table names and `TERMINAL_STATUSES`.
*Public entry points:* `get_tickets`, `get_ticket_detail`,
`get_member_thread_tickets`, `get_open_stats`, `get_daily_stats`, and the
smaller `get_*` lookups and report readers.
*Not in scope:* writes (`bq_writes.py`), Mighty Networks HTTP (`mn_api.py`),
members' private 1:1 questions (`coach_inbox.py`), and `get_daily_stats`'s
volume counts — how many came in and were answered today carry no urgency.
*Personal data:* member name, member id and the question body pass through to
the screen unchanged; nothing here stores or hashes them.

## Derived

Three values are computed in SQL on every read instead of being stored, so that a
coach's click shows up on the next rerun rather than after the next rebuild.
All three are built from the same live join: `grant_tickets gt` LEFT JOIN the
newest `ticket_metadata` row per `content_id` as `tm`.

**This live CTE is the authority the app reads, not the table's own column.**
Every status the app shows comes out of the CASE in this join, and that CASE's
last branch (`ELSE gt.ticket_status`) is reached only when no live branch
matched — so the reopen branch and a coach's `tm.status` both override whatever
Dataform built into `grant_tickets.ticket_status` (`bq_reads.py:191-192` for the
list, `:241-242` for the detail). The reopen predicate is written out at four
separate sites in `bq_reads.py`: `:33` (`_live_status_cte()`, used by
`get_open_stats` and `get_daily_stats`), `:176` (`get_tickets`), `:227`
(`get_ticket_detail`) and `:271` (`get_member_thread_tickets`). A change to the
reopen reading is wrong unless all four carry it.

`definitions/marts/grant_tickets.sqlx` computes its own copy of the same reopen
(rule (4) in the comment block at `:95`, branch at `:107-108`). That copy serves
SQL readers of the table, never the app. It must agree with R1-R1a here; it is
not where a coach-visible change lands. No spec owns the
`definitions/marts/*.sqlx` layer yet — until one does, this paragraph is the
only written statement that the two copies must match.

### Live status — `_live_status_cte()`

- R1: when `tm.status = 'closed'` and `gt.last_member_activity_at > tm.closed_at`
  (both non-NULL), the ticket reads `open` — a member has spoken since the close,
  so the ticket is live work again. This is the reopen. The status value stays
  `open` and no new status is invented: `config.TICKET_STATUSES` is the vocabulary
  of values a *coach can write* through the dropdown, and a reopen is derived from
  two timestamps, not clicked.
- R1a: the same condition as R1 is also selected as its own boolean column,
  `is_reopened` — true exactly when R1's branch fired, false otherwise. It is the
  one place the app learns that an `open` ticket had already been answered and
  closed, and it is what the REOPENED mark in the list, the detail header and the
  group dialog is drawn from. It is derived, never stored, and it is never
  compared against `config.TERMINAL_STATUSES` or passed to
  `config.is_open_status` — both keep working on `ticket_status` alone.
- R2: otherwise, when `tm.status` is set and not empty, that is the status — a
  coach's click beats the table.
- R3: otherwise `gt.ticket_status`, as Dataform last built it.
- R4: when `grant_tickets` has no `last_member_activity_at` column at all (an old
  Dataform compilation), R1 is dropped and nothing reopens. Silent by design: the
  app must keep answering mid-rebuild.
- R4a: under R4's missing column, `is_reopened` is still selected and is
  `FALSE` for every row, so the app's reading code needs no branch for a schema
  it may meet mid-rebuild. A missing mark is the safe failure: the row reads as
  an ordinary open ticket, which is what it reads today.

*Examples:* closed 2026-10-01, member comments 2026-10-06 -> `open`,
`is_reopened` true. Closed 2026-10-01, no member activity since -> `closed`,
`is_reopened` false. Never closed, created 2026-10-18 -> `open`, `is_reopened`
false — the two read the same but only one of them is a question nobody has
answered yet.

### The urgency clock — `_urgency_clock_expr()`

One timestamp per ticket: the moment its waiting time is counted from.

- R5: when `tm.closed_at` is set and `gt.last_member_activity_at` is later than
  it, the clock is `gt.last_member_activity_at` — the member's comment that
  reopened the ticket.
- R6: otherwise the clock is `gt.created_at`, as it has always been.
- R7: R5 does not test the current status, unlike R1. A reopened ticket a coach
  has marked `answered` but not closed is still on the reopen clock; were the
  status tested, that one click would snap the badge back to `critical`.
- R8: urgency is read off the clock: under 24 hours `normal`, 24 to 47 hours
  `urgent`, 48 hours or more `critical`.

*Examples:* created 2026-09-20, closed 2026-10-01, member comments today ->
clock today -> `normal` (today it reads `critical`). Created 2026-09-20, never
closed -> clock 2026-09-20 -> `critical`. Reopened today, coach marks
`answered` today -> clock today -> `normal`.

## Functions

### get_tickets(status, date_from, date_to, assignee, member_id, urgency, domain, lane)

*Signature, as it is in code.*

*What it does:*
- R9: returns one lane at a time — `question` feeds the Tickets tab, `general`
  feeds Conversations, `lane=None` returns both.
- R10: always drops rows with an empty `body`: a post with no question text is
  not work a coach can do. `get_open_stats` drops the same rows, so the list and
  the KPI card cannot disagree.
- R11: with no `status`, hides `closed` and `archived` and shows the rest;
  `status='open'` means every non-terminal status (`config.TERMINAL_STATUSES`).
- R12: the `urgency` argument filters on the clock of R5-R6, the same expression
  the `urgency` column is derived from, so a ticket badged `normal` is the one
  the Normal pill finds. The clock is selected in the `live` CTE as
  `urgency_since`, because the filter and the badge both sit outside that CTE and
  BigQuery cannot filter on a SELECT alias.
- R13: one row per `content_id`, newest `created_at` wins, ordered newest first.
- R13a: the row carries `is_reopened` (R1a) beside `ticket_status`. No filter
  reads it — the Status dropdown at `app.py:415-416` still offers only
  `config.TICKET_STATUSES`, and `status='open'` still means every non-terminal
  status (R11), reopened tickets included.

*Examples:* `urgency='Normal'` -> only tickets whose clock is under 24 hours old.
`status='open', lane='question'` -> the default Tickets tab.

*Inputs:* the sidebar's filter values; every one of them optional.

*Outputs:* a DataFrame of ticket rows plus `body_preview`, `urgency`,
`urgency_since`, `is_reopened`, and the live `ticket_status`, `assigned_to`,
`domain`, `lane`.

*Errors:* a schema mismatch mid-rebuild -> `_query_with_schema_retry` refreshes
`_tickets_cols()` and builds the query again; a second failure raises to the app,
which is watched by a person. No `BTB_ALERT` — this is not unattended code.

*Test:* `PATH=/opt/anaconda3/bin:$PATH python -m pytest
tests/test_bq_reads_urgency.py -q` from the repo root, with
`_query_with_schema_retry` stubbed to return the built SQL and `_tickets_cols()`
stubbed to include `last_member_activity_at`; observes that the `urgency` CASE
and the `urgency='Normal'` filter both read `urgency_since`, that
`urgency_since` is the R5/R6 expression, and that each of the four built
queries (`get_tickets`, `get_ticket_detail`, `get_member_thread_tickets`, and
`_live_status_cte()` as `get_open_stats` uses it) selects `is_reopened` from the
same predicate as its reopen branch — proves R12, R1a, R13a and R15a. A
second case stubs `_tickets_cols()` *without* `last_member_activity_at` and
observes `is_reopened` still selected and constant false — proves R4a. Red first
against `origin/main` @ `3ecd4d6`, where `is_reopened` appears in no query; R12's
own cases were red first against `57fc071`. Never `pytest tests/`: that runs
`smoke_test.py`, which writes to the live `ticket_metadata`.

### get_ticket_detail(content_id) · get_member_thread_tickets(thread_id, member_id)

*Signatures, as they are in code.*

*What they do:*
- R14: `get_ticket_detail` returns one ticket by `content_id`; it reads the same
  live status (R1-R4) and the same urgency clock (R5-R8) as the list, so a row
  and the dialog opened from it can never show different badges.
- R15: `get_member_thread_tickets` returns every ticket from one member in one
  thread, all statuses, oldest first, for the group dialog — same status, same
  clock, each row badged off its own.
- R15a: both carry `is_reopened` on the same terms as R13a, so a row, the dialog
  opened from it and the group dialog can never disagree about whether the
  ticket had been answered before.

*Examples:* a ticket the list badges `normal` after a reopen -> the dialog badges
`normal` too.

*Inputs:* a `content_id`; or a `thread_id` and a `member_id`.

*Outputs:* a dict of one ticket's columns (`{}` when there is no such row); or a
DataFrame of that member's tickets in that thread, plus `body_preview`.

*Errors:* as `get_tickets`.

*Test:* same command and stubs as `get_tickets`; observes that both built queries
derive `urgency` from the R5/R6 expression — proves R14 and R15, red first
against the commit before the fix, `57fc071`.

### get_open_stats()

*Signature, as it is in code.*

*What it does:*
- R16: four numbers for the KPI cards — `open`, and `normal` / `urgent` /
  `critical` among the open ones.
- R17: counts only the `question` lane and only non-empty bodies, the same two
  narrowings `get_tickets` applies (R9-R10).
- R18: the three urgency counts bucket on the clock of R5-R6, so the cards add up
  to what the pills show.
- R18a: the KPI cards do not count reopened tickets separately. `is_reopened` is
  a per-row mark, not a fifth card; a reopened ticket is counted in `open` and in
  whichever urgency bucket its clock (R5-R6) puts it. Why not a card: the cards
  must add up to the pills (R18), and a reopened count would overlap all three.

*Examples:* one ticket reopened today and nothing else open -> `open` 1,
`normal` 1, `urgent` 0, `critical` 0.

*Inputs:* none.

*Outputs:* a dict with `open`, `normal`, `urgent`, `critical`.

*Errors:* as `get_tickets`.

*Test:* same command and stubs; observes the three `COUNTIF`s bucket on the
R5/R6 expression and not on `created_at` — proves R18, red first against the
commit before the fix, `57fc071`.

## Decisions

- 2026-10-06: a reopened ticket's urgency is counted from the member's comment
  that reopened it, not from `created_at` (R5). Why: a coach reported tickets
  coming back as `urgent` or `critical` the moment a member commented. Urgency
  here only ever meant "how long has this person been waiting", and after a
  reopen that wait starts at the comment.
- 2026-10-06: the badge, the Urgency pills and the KPI counts all read the one
  clock (R12, R18). Why: `bq_reads.py`'s own note says the Open KPI and the list
  share their predicate so the two never diverge; a clock in one place and
  `created_at` in the others would hide a ticket badged `normal` behind the
  Normal pill.
- 2026-10-06: the clock ignores the current status (R7), while the reopen rule
  tests it (R1). Why: the status answers "is this live work", which a coach's
  `answered` click rightly changes; the clock answers "since when", which that
  click must not move.
- 2026-10-06: `get_daily_stats` is left alone. Why: `in_today`,
  `answered_today` and `daily_avg` count arrivals and answers by date, not
  waiting time, and a reopen is not a new arrival.
- 2026-10-06: this spec documents the four functions the urgency clock touches,
  not all 27 public reads. Why: the spec style guide caps a module spec at about
  150 lines and says a longer one should be split — `bq_reads.py` is 833 lines
  and does deserve splitting, but that is its own task, not this one's.
- 2026-10-19: a reopen is shown as a derived `is_reopened` mark on a ticket that
  still reads `open` (R1a), not as a new `reopened` value in
  `config.TICKET_STATUSES`. Why: `TICKET_STATUSES` is the list of values a coach
  can *write* from the dropdown (`config.py:37`, offered at `app.py:415-416` and
  at `app.py:1023` for the per-ticket override, where `app.py:1116` snaps any
  value not in that list back to `open`), and a reopen is derived from two
  timestamps, never clicked. A `reopened` value in that list would be offered as
  a settable status; once a coach saved it, `tm.status` would no longer be
  `'closed'`, R1 would stop matching, and the ticket would read `reopened`
  forever with nothing to clear it. A derived mark also leaves
  `TERMINAL_STATUSES`, `is_open_status`, `member_history.STATUS_ICON`
  (`app.py:84`) and every status reading in `app.py` (`:644`, `:653`, `:1115`,
  `:1514`) untouched, and it keeps R7 intact: the mark is read off the same two
  timestamps as the clock and tests no status, so marking a reopened ticket
  `answered` moves neither the badge nor the mark. Cost: a fifth value
  duplicated across the four reopen sites, a new column on the table, and three
  render sites in `app.py` to touch.
- 2026-10-19: fixing `definitions/marts/grant_tickets.sqlx` alone was rejected as
  a no-op. Why: the app reads the live CTE, not `grant_tickets.ticket_status` —
  the CASE's `ELSE gt.ticket_status` is its last branch, and the reopen branch
  and `tm.status` both come first (`bq_reads.py:191-192`, `:241-242`). The
  `.sqlx` copy of the reopen serves SQL readers of the table only. The `.sqlx`
  change still lands, last, so the two copies agree; it is additive (a new
  `is_reopened` column, `ticket_status` unchanged at `'open'`) because
  `definitions/` compiles from GitHub `main` and reaches the scheduled Dataform
  runs within the hour, which makes push-to-main and `deploy.sh` one window.
- 2026-10-19: no spec is written for the `definitions/marts/*.sqlx` layer as part
  of this change. Why: one table spec per table (STYLE.md R11) is a task of its
  own; until it exists, the `## Derived` preamble here is the only written record
  that the table's reopen must agree with the live CTE's, and that the CTE wins.
