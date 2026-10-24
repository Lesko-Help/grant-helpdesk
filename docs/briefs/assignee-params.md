---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: BigQuery (ticket_metadata MERGE)
module: bq_writes
spec: docs/specs/modules/bq_writes.md
folder: bq_writes.py, tests/test_bq_writes_params.py
---

# Brief: assignee-params

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Bind set_ticket_assignee values as query parameters instead of pasting them into the MERGE SQL

## Done when

`tests/test_bq_writes_params.py::test_set_ticket_assignee_binds_every_value` is red on origin/main and green after the fix. `test_nan_case_table_covers_every_binding_writer` stays green via a `set_ticket_assignee` entry in `_STRING_WRITERS`. `pytest tests/ --ignore=tests/smoke_test.py` is green.

Spec: unchanged because the spec's section for `set_ticket_assignee` is still a stub; proposed text goes under Spec proposals for the overseer.

# Gate: assignee-params
Spec: docs/specs/modules/bq_writes.md (### One ticket at a time, line 31) - WT_MODULE=bq_writes

## What is wrong (verified today by reading every writer, not assumed)
set_ticket_assignee (bq_writes.py:501) pastes the caller's text straight into
its MERGE: '{content_id}', '{assigned_to}', TIMESTAMP '{now}'. Every other
single-row writer binds a ScalarQueryParameter (:118, :141, :233, :282, :337)
and runs the value through _text_or_none (:22); this one does neither, so a
coach name with an apostrophe ends the SQL string early. Latent, not live:
the five current coach names are apostrophe-free, so it fires the day an
O'Brien is added - a plausible human name, not a hypothetical.

## What this task is NOT
Not a NaN fix - I called it "unguarded against 'nan'" earlier; the caller
disproves that, app.py:1273 feeds a fixed selectbox over get_team_members().
This is hazard removal. Out of scope: set_member_assignment_override (:525)
has the identical defect but zero callers, so fixing it is fixing dead code;
save_mn_api_key (:87) interpolates an API key and email - a separate task.

## Invariant
No caller value appears in the SQL text; each reaches BigQuery as a named
STRING parameter, byte for byte, referred to as @name.

## Slices
1. Red first: add set_ticket_assignee to tests/test_bq_writes_params.py using
   the harness there - _hostile(label) carries -O'Brien\ , _FakeClient records
   sql/job_config, _params reads back. Fail on origin/main; show that red.
2. The fix, inside set_ticket_assignee only: bind both values, _text_or_none
   on assigned_to, keep trigger_assignment_refresh() at the end.
3. test_nan_case_table_covers_every_binding_writer (:330) goes red on its own
   once the function binds - add the _STRING_WRITERS entry it demands.
4. Spec proposals for bq_writes.md back to me as text; do not edit specs.

## Scope and done when
bq_writes.py and tests/test_bq_writes_params.py only - no app.py, no docs.
Leave datetime.utcnow() at :503 alone; its deprecation is its own task.
Green (PATH=/opt/anaconda3/bin:$PATH python -m): pytest
tests/test_bq_writes_params.py -q, then pytest tests/
--ignore=tests/smoke_test.py - never bare pytest tests/, it writes live
ticket_metadata. Report branch, commit range, red-then-green proof.

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

Module `bq_writes`. Files: `bq_writes.py` (only `set_ticket_assignee`) and `tests/test_bq_writes_params.py`. Nothing else.

## Deploy implied

`deploy.sh`, run by the overseer from main after landing (the app ships `bq_writes.py`). No Dataform change.

## Context

2026-10-24: the overseer's memory message had not arrived when this brief was committed; add its content here once it comes. Source facts are in the Gate section above (verified by the overseer). Harness: `_hostile`, `_FakeClient`, `_params` in `tests/test_bq_writes_params.py`. Never run bare `pytest tests/`: it writes live ticket_metadata.

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
