---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: BigQuery
module: bq_writes
spec: docs/specs/modules/bq_writes.md
folder: bq_writes.py and tests/ at the repo root
---

# Brief: bq-writes-params

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Bind every value in the single-row bq_writes SQL as a query parameter, guarded by a new offline test file

## Done when

The test or assertion that must go from red to green. Name it. If it does not
exist yet, writing it is the first task — and prove it goes red before trusting
it green.

The test: `tests/test_bq_writes_params.py` (new, offline, fake client). Per
function: no caller value in the SQL text, every value a named STRING
parameter, `O'Brien\` round-trips. Red against `origin/main`, green here.

Spec: unchanged because specs are the overseer's; proposals go under Spec proposals.

# Gate — bq-writes-params

Architecture and design: `docs/specs/modules/bq_writes.md`, the one-ticket /
coaches / follow-ups / team-feedback groups. On main, `2b22c50`.

## Product — and two corrections to the note I gave you

These twelve sites *escape* the quote (`\'`), they do not drop it, so an
apostrophe survives: no silent corruption like R10's. The defect is a
**backslash** — a value ending in one escapes the closing quote and breaks or
extends the statement. And the `.replace` sites are not the hand-built SQL,
only the values somebody noticed: `update_ticket_meta` interpolates
`content_id`, `status`, `assigned_to` and `domain` raw, `submit_team_feedback`
the same with `submitted_by` and `feedback_type`. Converting only the
`.replace` lines leaves each statement interpolated while reading as handled,
so the unit of work is a function, not a `.replace`. Five of the seven have
**no test at all**; `update_ticket_meta` and `set_ticket_lane` are reached only
by `smoke_test.py`, against live BigQuery. The guard is most of the value.

## Slice order

1. Red first: new `tests/test_bq_writes_params.py`, fake-client pattern lifted
   from `tests/test_bulk_close.py` (`_FakeClient`, `_param_values`) — per
   function: the SQL carries no caller value, every value is a named STRING
   parameter, and a value holding `O'Brien\` round-trips. Red on main.
2. `update_ticket_meta`, `set_ticket_lane` — every value bound; the MERGE's
   typed-NULL branches (`CAST(NULL AS ...)`) stay SQL, not parameters.
3. `add_grant_coach`, `link_coach_login_email`, `update_followup_status`.
4. `submit_team_feedback`, `reply_team_feedback`.
5. Spec proposals back to me, not spec edits.

## Done when

- Each slice shows red-then-green, red proved against `origin/main`.
- `python -m pytest tests/test_bq_writes_params.py tests/test_bulk_close.py -q`
  passes (with `PATH=/opt/anaconda3/bin:$PATH`). Never bare `pytest tests/`:
  it runs `smoke_test.py`, which writes live `ticket_metadata`.
- May touch `bq_writes.py` and that one new test file — not `bq_reads.py` (its
  `:436` twin is a separate task), not `app.py`, not `smoke_test.py`, not
  Dataform, not the spec.

## Agentic review

### Verdict
Verdict: `<fill in — pass, or changes requested>`

### Findings
What the overseer's review subagent flagged — style, bugs, security —
one line each. A trimmer before Martin's read, not a replacement for it.

### Fixed in
Which commit fixed each finding, or "not fixed — see report" — one line
each.

This section is filled last, after the overseer runs its review subagent
and sends the findings back — never by the worker reviewing its own
diff. Record the findings under Findings (word for word) and the
fixes under Fixed in (one line per finding, naming its commit), fix
what needs fixing, commit, then report again the normal way. Also
leave the `Verdict:` line exactly as it stands: the overseer fills
it at review.

wt-done.sh's check on this is literal: it greps this brief for a line
starting with exactly `Verdict:` at the very start of the line (column 0)
— no bold, no indent, no renamed label, no different case. Keep the
`Verdict:` line reading exactly as it does above, or the guard cannot see
it and treats the brief as not yet reviewed.


## May touch

Module `bq_writes`. Files: `bq_writes.py` and the new
`tests/test_bq_writes_params.py`. Nothing else (not `bq_reads.py`, `app.py`,
`smoke_test.py`, Dataform, docs/specs).

## Deploy implied

`deploy.sh` (Cloud Run app) after the merge: `bq_writes.py` is app code. No Dataform change. The overseer runs it.

## Context

2026-10-21: the overseer's memory message had not arrived when this brief was
committed; add its content here once it does. Seven functions in scope:
`update_ticket_meta`, `set_ticket_lane`, `add_grant_coach`,
`link_coach_login_email`, `update_followup_status`, `submit_team_feedback`,
`reply_team_feedback`. Test pattern: `_FakeClient`, `_param_values` in
`tests/test_bulk_close.py`. Run with `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bq_writes_params.py tests/test_bulk_close.py -q`.
Spec functions for these groups are all `spec:stub`, so the brief is the source.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
In flight (file:line):
Next:
Traps (with dates):
