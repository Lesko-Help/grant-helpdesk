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
folder: repo root (bq_reads.py, bq_writes.py, app.py, tests/)
---

# Brief: bulk-close-convo

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Scope bulk close to one lane so Conversations gets its own sweep and the Tickets sweep stops closing Conversations rows

# Gate — bulk-close-convo

Architecture and design: `docs/specs/modules/bq_writes.md`,
`### execute_bulk_close(...)`, R11 and R12 (new), R9 extended. On main, `68f5971`.

## Product — why this first

Conversations has no bulk close, and the reason recorded for leaving it out was
wrong about what that tab is. Worse: the Tickets sweep has no lane condition,
so "Close 40 tickets" there also closes Conversations rows that tab never
showed and that number never counted. One `lane` fixes the bug and supplies the
feature, so the fix ships as the feature.

## Slice order

1. Red first, before any production edit: extend `tests/test_bulk_close.py`
   with the lane cases — helper, preview and execute each constrain to one
   lane, for both branches of the migration guard (`lane` in `gt_cols`, and
   not). On `origin/main` they go red: no lane condition exists.
2. `lane` becomes a required keyword on `bulk_close_rows_sql`, threaded through
   `preview_bulk_close` and `execute_bulk_close`, built from
   `_live_lane_expr(gt_cols)` with `gt_cols` passed in (R11, never probed).
3. The R9 fixture now differs everywhere: extend its allowed-differences list
   with the lane predicate. Do NOT regenerate it — that deletes the one guard
   proving both callers pick identical rows.
4. `app.py`: the panel at `:1751` becomes one renderer taking the lane, called
   from both tabs, every widget key and `_bc_preview` carrying it (R12). Keys
   come from one pure function; a test asserts the two lanes' key sets are
   disjoint, since the login gate keeps AppTest off this panel.
5. Spec proposals back to the overseer, not spec edits.

## Done when

- Red-first output for every lane case against `origin/main`; a `general` row
  survives a `question` sweep and the reverse; a call with no `lane` raises.
- `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q`
  passes, plus the app's own test file. Never bare `pytest tests/`: it runs
  `smoke_test.py`, which writes live `ticket_metadata`.
- May touch `bq_reads.py`, `bq_writes.py`, `app.py`, that test file — not
  `coach_inbox.py`, not Dataform, not the spec.
- The named red-to-green tests are the new lane cases in `tests/test_bulk_close.py` (helper, preview, execute, both `gt_cols` branches, and no-`lane` raises).
- Spec: unchanged by this branch, because specs are the overseer's; the proposals below go to it instead.

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

Module `bq_writes`. Files: `bq_reads.py`, `bq_writes.py`, `app.py`, `tests/test_bulk_close.py`. Not `coach_inbox.py`, not Dataform, not `docs/specs/`.

## Deploy implied

`deploy.sh` (Cloud Run, the app) — `app.py`, `bq_reads.py` and `bq_writes.py` all ship in it. No Dataform change. The overseer runs it from main after landing.

## Context

2026-10-20: the overseer's memory message had not arrived when this brief was committed; its content gets added here once it does.

Spec: `docs/specs/modules/bq_writes.md` R9, R11, R12 (on main, `68f5971`). Today the Tickets sweep (`app.py:1880` area) has no lane condition and so closes `general` rows too.

Design note: `_live_lane_expr` reads `tm` and `gt`, which exist only inside the helper's `base` CTE, so the lane goes in as a `lane` column of `base` and a `t.lane = ...` condition in the WHERE.

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
