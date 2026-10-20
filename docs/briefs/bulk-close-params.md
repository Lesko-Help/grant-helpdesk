---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: BigQuery
module: bulk_close
spec: docs/specs/modules/bulk_close.md
folder: bq_reads.py, bq_writes.py, tests/test_bulk_close.py
---

# Brief: bulk-close-params

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Filter values reach BigQuery as query parameters, not interpolated SQL, per R10

## Done when

The test or assertion that must go from red to green. Name it. If it does not
exist yet, writing it is the first task — and prove it goes red before trusting
it green.

One fixed extra line, always present, naming the module this task belongs to:
`Spec: docs/specs/modules/<module>.md updated` if the module's spec changed,
or `Spec: unchanged because <reason>` if it did not.

# Gate — bulk-close-params

Architecture and design: `docs/specs/modules/bulk_close.md`, R10, with R9's
fixture guard and the `*Test:*` paragraph. On main, `14be20c`.

## Product — why this

A coach who filters the sweep by a name like `O'Brien` gets no error. The quote
is stripped (`.replace("'", "")` on status, date and lane) or backslash-escaped
into the SQL text, so the sweep runs on a value the coach never typed and closes
whatever that other filter matched — plausible, silent, and counted, on the one
destructive path we have. The repo already uses `ScalarQueryParameter`
(`bq_reads.py:397-421`, `bq_writes.py:409-441`), so this copies a local pattern.

## Slice order

1. Red first, before any production edit: a filter value holding an apostrophe
   must reach BigQuery unchanged. Assert the SQL text carries no filter value at
   all, that the parameters carry each one exactly, and that preview and execute
   are handed the identical pair. Red on `origin/main`, where the helper returns
   a bare string.
2. `bulk_close_rows_sql` returns its SQL together with the parameters it needs,
   so no caller can run the SQL without them; both callers merge those into
   their own `QueryJobConfig`. All four values become parameters, `lane` too.
3. STOP and ask before touching `tests/fixtures/bulk_close_sql_before.json`.
   Placeholders change every filter line, so the R9 fixture will differ broadly;
   extending its allowed-differences list versus regenerating it once is a spec
   call, not yours. Regenerating it unasked deletes the one guard proving both
   callers select identical rows.
4. Spec proposals back to the overseer, not spec edits.

## Done when

- Red-first output shown for each assertion in slice 1 against `origin/main`.
- `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q`
  passes, the existing 44 included. Never bare `pytest tests/`: it runs
  `smoke_test.py`, which writes the live `ticket_metadata`.
- Spec: unchanged because R10 already says it; worker edits no spec. The `*Test:*` paragraph's "R10 is not tested" and "44 tests" go stale: proposed under Spec proposals.
- May touch `bq_reads.py`, `bq_writes.py`, a call site in `app.py` if one needs
  it, and that test file — not the spec, not Dataform, not `coach_inbox.py`, and
  not the `.replace("'", ...)` sites outside this sweep.

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

Module `bulk_close`. Files: `bq_reads.py` (`bulk_close_rows_sql`, `preview_bulk_close`), `bq_writes.py` (`execute_bulk_close`), a call site in `app.py` only if one needs it, `tests/test_bulk_close.py`. Nothing else; fixture `tests/fixtures/bulk_close_sql_before.json` only after the overseer's answer (slice 3).

## Deploy implied

`deploy.sh` (Cloud Run, from main after the landing). No Dataform change.

## Context

2026-10-20: the overseer's memory message had not arrived when this brief was committed; add its content when it comes. Spec read: `bulk_close.md` R9, R10, R11 and the `*Test:*` paragraph. Existing tests call `bulk_close_rows_sql` expecting a string and `_FakeClient.query(sql)` takes no `job_config`, so slice 2 forces edits to those tests; slice 1 adds only new ones. Existing `.replace("'", ...)` sites outside this sweep (`closed_by_val` in `execute_bulk_close`, etc.) are out of scope.

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

Name the module first — the smallest thing that deploys or is scheduled on
its own (see docs/specs/INDEX.md for this repo's module list). Then the
folders and files in scope. Anything outside this list is a question back to
the overseer, not a change.

## Deploy implied

Which deploy script (or Dataform tag) this change needs to go live. The
worktree session never runs it; the overseer does, from main, after the merge.

## Context

Links: the HANDOFF doc, the session log lines, the ids, the numbers measured.
Enough that a fresh session needs no paste.

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
