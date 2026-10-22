---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: BigQuery (query parameters)
module: bq_writes
spec: docs/specs/modules/bq_writes.md
folder: bq_writes.py, tests/
---

# Brief: nan-param-guard

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Writers in bq_writes.py coerce any non-string argument to None, so a float NaN from the merged frame can never reach BigQuery as a query parameter

## Done when

`tests/test_bq_writes_params.py::test_no_writer_binds_a_float` goes red on `origin/main` (a float NaN reaches a bound parameter) and green after the guard.

Spec: unchanged because specs are the overseer's; proposals are under Spec proposals.

# Gate — nan-param-guard

Design: `docs/specs/modules/bq_writes.md`, `### One ticket at a time`. Main `ae63685`.

## Product — why this first

A coach answers a member question, the answer reaches Mighty Networks, then the
status write dies and she sees "Failed to post: 400" (Misty, today). Rolled back
to `00080-2h2`, so coaches are unblocked and the app is again writing the
literal text 'nan' into `assigned_to` — 2608 of 7486 rows already.

`merge_into_tickets`' `pd.concat` fills the 33 columns the questions frame
lacks with float NaN. `bool(nan)` is True, so `v or ""` and `.get(k, "")` both
pass it on — to be interpolated as 'nan' (00080) or bound as a query parameter
that is not legal JSON (00081).

The guard belongs in the writers, not only at the NaN source: the mechanism is
proven but not which screen path carried the NaN in — `get_ticket_detail` tested
clean. A writer-side guard covers all twelve call sites without that answer and
needs no Streamlit to test. `merge_into_tickets` is a separate task under
`coach_inbox`, which owns it.

## Slice order

1. Red first, before any production edit: a test calling each writer with
   `float("nan")` per string argument, asserting no bound value is ever a
   float. Red on `origin/main`.
2. Coerce non-`str` to `None` at the top of each writer, repo pattern
   (`2a6adba`, `app.py:2160`). `None` not `""`: reads `COALESCE(tm.assigned_to,
   gt.assigned_to)`, so NULL falls through to the derived value where `""`
   shadows it. A caller passing `""` is unaffected.
3. Spec proposals back to the overseer, not spec edits.

## Done when

- Red-then-green output for slice 1 against `origin/main`.
- `pytest tests/test_bq_writes_params.py -q` then `tests/ --ignore=tests/smoke_test.py`
  pass, via `PATH=/opt/anaconda3/bin:$PATH python -m`. Never bare `pytest tests/`.
- May touch `bq_writes.py` and its test files only — not `app.py`, not
  `coach_inbox.py`, not Dataform, not the spec.

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

Module `bq_writes`: `bq_writes.py` and `tests/test_bq_writes_params.py` only.

## Deploy implied

`deploy.sh` (Cloud Run, from main) after landing. No Dataform change.

## Context

2026-10-22: the overseer's memory message had not arrived when this was committed. Scope chosen: the nine writers that bind string query parameters (`update_ticket_meta`, `set_ticket_lane`, `add_grant_coach`, `link_coach_login_email`, `update_followup_status`, `submit_team_feedback`, `reply_team_feedback`, `save_standard_reply`, `archive_standard_reply`). `set_ticket_assignee` and `set_member_assignment_override` still paste values into the SQL text (known, bq-writes-params item 6): a guard there would write the text 'None', so they need parameters first and are left for that task.

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
