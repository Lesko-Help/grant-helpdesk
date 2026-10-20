# bulk_close
Status: agreed
Kind: app
Summary: the one sweep that closes many tickets at once — one lane per sweep, confirmed against a previewed count
Part of: `docs/specs/INDEX.md` · Deploy: `deploy.sh` (ships inside the app image) · Updated: 2026-10-20
Who: a grant coach, on the Tickets tab or the Conversations tab · Where: Streamlit, a "Bulk Close" expander on each
Reads: `grant_helpdesk.grant_tickets`, `grant_helpdesk.ticket_metadata`, `grant_helpdesk.followup_queue` — only to decide which rows to write
Writes: `grant_helpdesk.ticket_metadata`

## Overview

*What it is for:* close a whole filtered batch of tickets in one press, for when
a coach has worked through them and only the statuses are lagging behind.
*What it owns:* the Preview-then-confirm panel, the row selection both halves
share, and the one MERGE that closes the batch.
*Where the code lives:* three files, one owner. `app.py` holds the panel
(`render_bulk_close_panel`, `bulk_close_keys`); `bq_reads.py` holds the shared
selection (`bulk_close_rows_sql`) and the count (`preview_bulk_close`);
`bq_writes.py` holds the write (`execute_bulk_close`). A task touching any of
them names **this** spec as its `WT_MODULE` — the spec that owns the function,
not the file the function sits in.
*What it depends on:* `config.py` for the table names and the two lane
constants, `followup_queue` for the one row class a sweep must never touch, and
`bq_base._tickets_cols()` for whether `grant_tickets` has a `lane` column yet.
*Not in scope:* members' private 1:1 threads — see R1 and the 2026-10-20
decision on why a thread sweep could not reuse this SQL at all.
*Numbering:* R1–R12 keep their numbers permanently, because
`tests/test_bulk_close.py` names its tests after them (`test_r4_*`,
`test_r9_*`, `test_r11_*`, `test_r12_*`) — renumbering a rule silently unhooks
a guard from the rule it guards.

## Screens

### Bulk Close (one expander per lane)

*What it shows or asks:* an expander titled "Bulk Close Tickets" or "Bulk Close
Conversations", by lane, holding three filters in a row — Status (`answered`,
`open`, `flagged`, or "— any open status —"), Grant coach (a coach, or "— all
coaches —"), Created before (a date, or blank) — and a **Preview** button.
Preview draws nothing directly: it writes a count into the lane's session-state
entry, which draws an info line, "**N conversations will be closed** — M
skipped (follow-up pending)", the skipped half only when M is not zero. Only
when N is above zero does the confirm button appear, labelled "✅ Close N
conversations". Pressing that runs the sweep, clears the stored preview, clears
the three ticket caches (`load_tickets`, `load_open_stats`, `load_daily_stats`),
reports "Closed N conversations." and reruns the page. The three "— any … —"
options are how R2's *empty means no constraint* reaches the coach: each maps
to `""` before it reaches the SQL.

*Reads / Writes:* reads `grant_tickets`, `ticket_metadata` and `followup_queue`
through `preview_bulk_close`; writes `ticket_metadata` through
`execute_bulk_close`, and nothing else on either tab.

*Error view:* none of its own. The panel wraps neither call in `try`, so a
`BadRequest` from an unparseable filter surfaces as Streamlit's own exception
box and the count or the sweep simply does not happen. That is the intended
direction — a coach is watching, and R5 makes the write all-or-nothing — but
see the Open check: nobody has watched it fail.

## Functions

### execute_bulk_close(status_filter="answered", assigned_to="", before_date="", closed_by="", *, lane, gt_cols=None)

- R1: community tickets only. It writes `ticket_metadata` keyed by `content_id`
  from `grant_tickets`, so a member's private thread can never be swept by it,
  whatever the filters say. Private threads close one at a time, through
  `coach_inbox.set_thread_workflow`.
- R2: the three filters AND together, and an empty string means *no constraint
  on that field* — never "match the empty value". All three empty is therefore
  "every open ticket in this lane", the widest sweep the function can do, and
  the one a coach reaches by leaving the form alone.
- R3: a ticket with any `pending` row in `followup_queue` is never closed,
  whatever the filters match. Why: that follow-up is a question already sent to
  the member, so closing discards an answer still on its way.
- R4: `closed`, `cancelled` and `archived` are all excluded, by effective
  status, so neither the preview number nor the sweep touches an archived
  ticket. `archived` was added on 2026-10-19 (Martin) and was the one rule here
  whose test went red against live behaviour rather than a missing helper.
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
  Both call `bq_reads.bulk_close_rows_sql`, which builds the `base` CTE and the
  filtered SELECT once; the pending-follow-up predicate (R3) stays per caller
  (execute: `NOT IN`; preview: a LEFT JOIN with `COUNTIF`). The coach consents
  to a number; if the two drift, the app asks about one thing and does another.
  Stated generally: **everything the number depended on travels with the
  number** — the preview result carries every input its count came from, and
  execute runs with those, not with the widgets as they stand at confirm time.
  `gt_cols` works this way (R11) and so do the three filter values:
  `preview_bulk_close` returns `status_filter`, `assigned_to` and `before_date`
  beside `gt_cols`, and the confirm button passes those to `execute_bulk_close`.
  The widgets are read only by the Preview branch. Until 2026-10-20 they were
  not: `app.py` recomputed them from the widgets on every run, so a coach could
  press Preview, change the Status filter, and confirm while the old number was
  still on screen — and the sweep ran with the new filters. That was R9 failing
  through the screen rather than the SQL, striking the one number that carries
  the consent. Fixed rather than papered over by clearing the preview whenever a
  filter changes, which would snatch away the number the coach is reading.
  Guarded by `test_r9_execute_filters_come_from_the_stored_preview`,
  `test_r9_confirm_branch_does_not_read_the_filter_widgets` and
  `test_r9_preview_returns_the_three_filters_it_used`. The second of those is
  the one that catches a widget merely *named* in the confirm branch while all
  three arguments are correct.
- R10: filter values must reach BigQuery as query parameters. Today all four are
  interpolated into the SQL with ad-hoc quote stripping — not a safety boundary,
  and it corrupts rather than refuses: `status_filter`, `before_date` and `lane`
  drop the quote (`.replace("'", "")`), so a sweep filtered on `O'Brien` runs on
  a value the coach never typed; `assigned_to` escapes it instead. Held by the
  `bulk-close-params` worktree, opened 2026-10-20.
- R11: **one lane per sweep.** Preview and execute each take a `lane` and
  constrain the selection to it, through the same live-lane expression the lists
  use (`bq_reads._live_lane_expr`: `tm.lane` when set, else `gt.lane`, else
  `question`), so the rows counted are the rows that tab shows. There is no
  default and no value meaning "both lanes": the button sits on a tab, the tab
  shows one lane, so a sweep that crosses lanes closes rows the coach never saw
  and never consented to. Before this rule was built the helper carried no lane
  condition at all and the Tickets-tab sweep closed Conversations rows too —
  making this, after R4, the second rule here whose test went red against live
  behaviour. `app.py` passes `config.LANE_QUESTION` from Tickets and
  `config.LANE_GENERAL` from Conversations.
  *Pure helper:* `bulk_close_rows_sql` takes `gt_cols` and hands it on, the way
  `_reopen_predicate(gt_cols)` does, and never calls `_tickets_cols()` itself —
  that probe is a BigQuery call, and the whole of `tests/test_bulk_close.py`
  builds SQL with no client. Both branches get a test: `lane` present in
  `grant_tickets` (the expression reads `gt.lane`) and absent (it reads the
  `'question'` literal, so a pre-migration `general` sweep matches only rows a
  coach moved by hand, which is correct).
  *Lane condition last:* it is appended after all three filters, and that is
  load-bearing rather than cosmetic — `_where` in the tests strips it with a
  `$`-anchored `re.sub` so R2 and R4 keep counting only their own conditions.
  Moving it does not quietly weaken those rules; it raises `AttributeError` and
  takes R2, R4 and R11 red together, which is the right failure.
  *One probe, handed on:* the two callers must build the *same* expression, and
  a schema probe each does not guarantee it. `_tickets_cols()` is cached for
  300 seconds (`bq_base.py:53`), a coach can take longer than that between the
  two presses, and the pending Dataform migration adding `lane` in that gap
  would leave preview on the `'question'` literal while execute read `gt.lane`
  — execute then closes more rows than the number the coach agreed to, which is
  R9's exact failure. So `preview_bulk_close` probes once and returns the sorted
  list as a third key, beside the three filter values (R9); `app.py`
  keeps that result in the lane's `_bc_preview_<lane>` entry, which already
  spans the two presses; and `execute_bulk_close` takes `gt_cols` as a keyword
  whose default `None` means "probe now", with the panel always passing what
  preview returned. Identical by construction, not by two probes agreeing.
- R12: **the panel exists once.** The two tabs' panels are one renderer taking
  the lane, not two copies, and every widget key plus the preview's
  session-state key carries the lane — both tabs render on the same Streamlit
  run, so a bare key like `bc_status` would be registered twice and Streamlit
  raises a duplicate-key error (the same reason `lane` is threaded through
  `render_ticket_table`). Why one renderer: two copies drift, and R9's whole
  promise is that the number and the sweep agree.
  The keys come from one pure function, `bulk_close_keys(lane)`, returning
  `bc_status_<lane>`, `bc_coach_<lane>`, `bc_before_<lane>`,
  `bc_preview_<lane>`, `bc_execute_<lane>` and the session-state key
  `_bc_preview_<lane>`. The renderer is `render_bulk_close_panel(lane,
  team_members, current_user)`.

*Examples:* `("answered", "", "", "coach@…", lane="question")` -> every
answered Tickets-lane ticket with no pending follow-up closes, credited to that
coach, count returned. `("", "coach@…", "2026-01-01", "coach@…",
lane="general")` -> only that coach's open Conversations-lane rows created
before 2026-01-01.

*Inputs:* an effective status or `""` for any; a coach's login email or `""`
for all; an ISO date (`YYYY-MM-DD`) or `""` for all dates; the closing coach;
`lane`, keyword-only, no default; and `gt_cols`, the column list preview used,
`None` meaning probe now.

*Outputs:* an `int`, the rows the MERGE affected.

*Errors:* a bad date or unparseable filter raises
`google.api_core.exceptions.BadRequest` and nothing is written, the MERGE being
one statement. No `BTB_ALERT`: this runs behind a coach's click, not on a
schedule, so a human sees the failure at once.

*Test:* `tests/test_bulk_close.py` guards R2, R3 (in both callers), R4, R9, R11
and R12, on SQL strings and on `app.py`'s source, with no BigQuery client; R7,
R8 and R10 are not tested. 44 tests, run with:

```
PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q
```

Never bare `pytest tests/` — that runs `smoke_test.py`, which writes the live
`ticket_metadata`.

R9's strongest guard reads `tests/fixtures/bulk_close_sql_before.json`, the SQL
both functions built *before* the extraction, and compares line multisets for
four filter sets against both callers, pinning the only differences the
extraction and the lane work were allowed to have: `'archived'` added, the
nesting, the `AS lane` column written out literally, the comma it puts on the
line before, and a per-case WHERE line equal to the fixture's own plus
`AND t.lane = 'question'`. It stays **exact multiset equality**, not
containment, and the fixture is never regenerated. It bites: one extra column
on the helper's `base` SELECT, a dropped lane predicate, a sweep ignoring its
lane argument, or a silent change to the lane expression each turn all eight
cases red.

That fixture is also the **only** guard on the lane expression's text:
`test_r11_helper_confines_the_selection_to_its_lane` builds its expectation by
calling `_live_lane_expr` — the code under test — so it agrees with any change
to it and stays green. The literal `_LANE_COLUMN` string in the fixture test is
therefore load-bearing: **do not "tidy" it into a call to `_live_lane_expr`**,
or the expression is left with no guard at all.

R12 is guarded by four tests that read `app.py` with `ast`, the login gate
keeping AppTest off the panel: the two lanes' key sets are disjoint and every
key carries its lane; no bare `bc_` string exists outside `bulk_close_keys`;
there is exactly one preview call and one execute call, both passing
`lane=lane`, execute also passing `gt_cols=_p['gt_cols']`; and each tab calls
the renderer with its own lane. The second deliberately exempts
`bulk_close_keys` itself, which is safe only because the first covers the
inside of that function — a lane stripped from a key *there* goes red on it.

### preview_bulk_close(status_filter="answered", assigned_to="", before_date="", *, lane)

*Lives in `bq_reads.py:544`; specified above as half of the pair — see R9 and
R11.* Returns `{"will_close": N, "skipped_followup": M, "gt_cols": [...],
"status_filter": ..., "assigned_to": ..., "before_date": ...}` — the count, and
every input the count was built from (R9).

### bulk_close_rows_sql(status_filter="answered", assigned_to="", before_date="", *, lane, gt_cols)

*Lives in `bq_reads.py:490`.* The selection both callers share: builds the
`base` CTE and the filtered SELECT, returns SQL text. Pure — no client, no
schema probe (R11); `lane` and `gt_cols` are keyword-only with no defaults, so
a caller cannot forget either one quietly.

### bulk_close_keys(lane) · render_bulk_close_panel(lane, team_members, current_user)

*Live in `app.py`.* The key function and the one panel — see R12 and Screens.

## Open check

- The Conversations panel has had **no visual check.** The login gate keeps
  AppTest off it, so R12's `ast` tests prove the wiring and nothing proves the
  rendering; it is hand-checked on the live app after a deploy, as
  `coach_inbox`'s click-through is. First due after the 2026-10-20 deploy,
  revision `grant-helpdesk-00078-rmk`.
- The error view above is read off the absence of a `try` in the panel, not off
  a failure anyone watched. What a coach actually sees is unverified.

## Decisions

- 2026-10-20: split out of `bq_writes.md` (Martin), which stood at 249 lines
  against STYLE R8's ~150. The seam is the one that file already named: the
  destructive sweep and its panel on one side, the single-row writes on the
  other. Nearly the whole overage was here — twelve invariants on one
  destructive path and the decisions behind them — so the split cost no rule
  and no reason, and it gives the sweep's three files one owner to name in
  `WT_MODULE` instead of a spec named after only one of them. This file is
  itself over ~150, for the reason `bq_writes.md` first recorded: the excess is
  the invariants and their reasons, and cutting those to reach a line count
  would be the wrong trade.
- 2026-10-19: written (then as part of `bq_writes.md`) because `bq_writes.py`
  was owned by no spec at all (global rule 7, owned or gone), and because
  helpdesk-05 asks for bulk close in Conversations. Writing it established that
  the community-ticket version was **already built** — Preview then confirm — so
  helpdesk-05 was an extension, not a new feature, and R7, R8 and R10 were
  found by reading the code, not by a coach hitting them.
- 2026-10-19: a bulk close is confirmed against a count, not a list. Preview,
  read "N will be closed, M skipped", press the button. R9 exists because that
  number is the whole of the consent: nobody re-reads forty rows, so the number
  must be true.
- 2026-10-19: `archived` is excluded from the sweep (Martin). An archived
  ticket is already out of every coach's list, so sweeping it closed changes
  nothing anyone sees and only moves numbers in reports that count by status —
  a silent edit to history. The three terminal-ish states now behave alike,
  which is the asymmetry a reader would otherwise have had to rediscover.
  Carried by R4, in the code since `be289bf` (landed 2026-10-19).
- 2026-10-20: **the two 2026-10-19 decisions on what "Conversations" is were
  wrong, and are replaced by this one and the next.** The Conversations tab is
  `load_tickets(lane=config.LANE_GENERAL)` — community posts and comments that
  are not grant questions, in *these same* tables, carrying status,
  `assigned_to`, domain and urgency like any ticket. The Tickets tab is the
  same code with `lane="question"`. Members' private 1:1 questions are not on
  that tab at all: they merge into Tickets, and their status is derived in
  Python from who wrote last (`coach_inbox.py:135`), never stored. So bulk
  close for Conversations is this sweep scoped to a lane (R11), needs nothing
  in `coach_inbox.py`, and cannot reach a private thread — R1 holds unchanged,
  for the reason it always did.
- 2026-10-20: the Conversations sweep offers **the same three filters as
  Tickets** (Martin), reusing the one panel with a lane argument (R12). This
  replaces "status only" (2026-10-19), whose recorded reason — "one filter
  keeps the sweep small" — was backwards: a filter narrows a sweep, so offering
  fewer makes the default sweep wider, and it would have cost a second panel to
  build. An age filter stays out, for the reason first given: "answered and
  untouched for N days" needs the `closed_at` column the cut "answered 3d ago"
  age needed (`coach_inbox.md`, 2026-10-19).
- 2026-10-20: a bulk close over members' private 1:1 threads is **not built and
  not asked for.** It would be a separate function in `coach_inbox.py` closing
  through `set_thread_workflow`, and could not reuse the SQL here at all,
  because a thread's status is derived per read in Python rather than stored in
  a column. Written down because the 2026-10-19 pair of decisions promised that
  function in `coach_inbox.md`, where no such section exists.
- 2026-10-19: `bq_writes` importing `bq_reads.bulk_close_rows_sql` is a new
  edge between those modules, chosen by Martin over putting it in `bq_base.py`,
  because R9 wants one copy of the selection more than a tidy dependency graph.
