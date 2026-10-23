---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: none
module: coach_inbox
spec: docs/specs/modules/coach_inbox.md
folder: coach_inbox.py, tests/test_coach_inbox.py
---

# Brief: merge-nan-fill

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Stop merge_into_tickets introducing float NaN: a column a row frame never had must read as None there, not NaN

## Done when

The test or assertion that must go from red to green. Name it. If it does not
exist yet, writing it is the first task — and prove it goes red before trusting
it green.

Test: `test_merge_into_tickets_introduces_no_float_nan` (and its non-vacuous companion) in `tests/test_coach_inbox.py`. Red on origin/main (concat fills the missing columns with NaN), green after the fix inside `merge_into_tickets`.

Spec: unchanged by this worktree (specs are the overseer's); proposed text is under Spec proposals below.

# Gate: merge-nan-fill
Spec: docs/specs/modules/coach_inbox.md (### merge_into_tickets, line 72) - WT_MODULE=coach_inbox

## What is wrong (verified today against the real schemas, not assumed)
merge_into_tickets concatenates the tickets and questions frames, and
pd.concat fills a column one side never had with float NaN, both ways: a
ticket row gains topic, subject, messages, status; a question row gains
every ticket-only column (~30: thread_id, title, body, assigned_to,
domain...). It fires even with zero questions, because the empty
frame still carries _QUESTION_COLUMNS (coach_inbox.py:116). NaN is a trap,
not untidiness: bool(nan) is True so `x or ""` keeps it, .get(k, default)
defaults only on an ABSENT key, and str(nan) is the text 'nan'.

## What this task is NOT
Not the cause of the 2,611 assigned_to='nan' rows - disproved today (the merge
leaves a ticket's None as None, and those rows are all community tickets), so
leave those alone. Known consumers are each hardened already (pd.isna in
ticket_group_key, coach_inbox.py:431; app.py:1624 skips the columns); this
removes the hazard at its one source instead.

## Invariant
No float NaN is introduced: a column a row's own frame never had reads as None
there. What the frames carried - a real None, a numeric column's NaN - stands.

## Slices
1. Red first: a test on the returned frame - real column sets both ways and
   an empty-but-columned questions frame - asserting no cell is a float
   NaN. Must fail on origin/main; show that failure before fixing.
2. The fix, inside merge_into_tickets only.
3. Non-vacuous guard: assert the test saw a column present on one side only.
4. Spec proposals for coach_inbox.md back to me as text; do not edit specs.

## Scope and done when
coach_inbox.py and tests/test_coach_inbox.py only - no app.py, no bq_writes,
no docs/specs/. Do not touch .attrs: read_failed is read off the questions
frame at app.py:1359, before the merge. R1-R4 ordering tests stay green.
Green (PATH=/opt/anaconda3/bin:$PATH python -m): pytest
tests/test_coach_inbox.py -q, and pytest tests/ --ignore=tests/smoke_test.py;
never bare pytest tests/, smoke_test.py writes live ticket_metadata. Report
branch, commit range, red-then-green proof, spec proposals.

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

Module `coach_inbox`: `coach_inbox.py` (inside `merge_into_tickets` only) and `tests/test_coach_inbox.py`. Nothing else.

## Deploy implied

`deploy.sh` (Cloud Run app, `coach_inbox.py` ships with it). Run by the overseer from main after the merge.

## Context

2026-10-23: the overseer's memory message had not arrived when this brief was committed; add its content here once it comes. The gate text above carries the measured facts (about 30 ticket-only columns; fires even with zero questions; 2,611 assigned_to='nan' rows are NOT caused by this). Reporting to `helpdesk-opzichter`.

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
