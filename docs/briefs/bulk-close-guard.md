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
folder: repo root (`bq_reads.py`, `bq_writes.py`, `tests/`)
---

# Brief: bulk-close-guard

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Extract one shared row-selection helper used by both execute_bulk_close and preview_bulk_close, exclude archived from the sweep, and add the first bulk-close test with a red-first proof for each rule

## Done when

`tests/test_bulk_close.py`: test_r2, test_r3, test_r4, test_r9 go red against `origin/main` (no helper to import; archived swept), then green. Details in the gate section below.

Spec: unchanged because specs are the overseer's; the new R4 and R9 wording (drop "not yet in the code") is proposed under Spec proposals.

# Gate — bulk-close-guard

Architecture and design: `docs/specs/modules/bq_writes.md`, section
`### execute_bulk_close(...)`, rules R2, R3, R4, R9, R10. Agreed text, on main.

## Product — why this first

A coach presses Preview, reads "40 will be closed, 3 skipped", presses the
button. That number is the whole of the consent: nobody re-reads forty rows.
Today the number and the sweep are two separate copies of the same SQL
(`bq_writes.execute_bulk_close`, `bq_reads.preview_bulk_close`), and no test
covers either — `grep -rn bulk_close tests/` finds nothing. helpdesk-05 asks
for the same sweep over member questions, which would make a third copy. One
shared row-selection helper, guarded, has to exist first.

## Slice order

1. Capture today's SQL for a few filter sets as a fixture, so the extraction
   is provably row-identical except for the one intended change.
2. Extract one pure helper that builds the row selection (WHERE + `base` CTE)
   from filters and returns SQL text — `bq_reads._reopen_predicate`'s shape.
3. Exclude `archived` alongside `closed` and `cancelled` (R4, Martin, 2026-10-19)
   — the only rule whose red comes from live behaviour, not a missing import.
4. `tests/test_bulk_close.py` asserts R2, R3, R4 and R9 on strings, with no
   BigQuery client. R9 is one assertion that both callers use the helper.
5. Update `bq_writes.md` R4 and R9, which today say "not yet in the code".

## Done when

- One pure helper builds the row selection; neither function inlines it.
- `archived` is excluded; a ticket in that state survives a matching sweep.
- Red-first shown as output for each of R2, R3, R4, R9, against `origin/main`.
- `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q`
  passes. Never bare `pytest tests/` — it runs `smoke_test.py`, which writes
  live `ticket_metadata`. No change beyond `archived`: R7 and R10 stay put.

## May touch

`bq_writes.py`, `bq_reads.py`, `tests/test_bulk_close.py`,
`docs/specs/modules/bq_writes.md`. Not `app.py`, not `coach_inbox.py`.

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


## May touch (module)

Module `bq_writes`. Files: `bq_writes.py`, `bq_reads.py`, `tests/test_bulk_close.py`. Nothing else.

## Deploy implied

`deploy.sh` (Cloud Run app) after the merge: `app.py` calls both functions. No Dataform change. The worktree never runs it.

## Context

2026-10-19: the overseer's memory message had not arrived when this brief was committed; add its content here once it does.

Design choice: the helper `bulk_close_rows_sql(status_filter, assigned_to, before_date)` lives in `bq_reads.py` (next to `preview_bulk_close`, `bq_writes` imports it). It returns the `base` CTE plus the filtered SELECT; the pending-follow-up handling (R3) stays with each caller. R10 stays as is (interpolation), as the brief says.

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
