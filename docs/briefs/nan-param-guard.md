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
Verdict: pass. Landed on Martin's say-so 2026-10-22. Verified by the overseer independently, not from the worker's report: red-first reproduced on a scratch tree built from `git archive origin/main` carrying only the new test file (31 failed, 1 passed, `_text_or_none` confirmed absent); green 43 passed on the branch and 341 passed on `tests/ --ignore=tests/smoke_test.py`; three mutations each red and each only in its own case — helper to pass-through 29 failed, `update_ticket_meta`'s single call site wrapped in `(lambda v: v)` exactly 6 failed and all of them `update_ticket_meta-*`, a newly appended unguarded binding writer red on `test_nan_case_table_covers_every_binding_writer`. Scope checked too: three files, nothing in `app.py`, `coach_inbox.py`, `docs/specs/` or Dataform.

### Findings
Raised by the overseer at review, each checked against the branch before it was
raised. None of them is a rework request; all four are follow-up tasks.

1. `bq_writes.py:200-201` — `_text_or_none(kwargs["skipped_reason"]) or ""`
   turns the guard's `None` straight back into `""`, against this task's own
   "NULL, not `''`" rule. Harmless, because `skipped_reason` is not COALESCEd
   by any read, but inconsistent with the invariant the branch argues for.
2. `queue_followup`, `post_comment` and `log_rsvp` write through
   `client.insert_rows_json`. A float NaN breaks their JSON by exactly the
   mechanism this task fixes, while they bind no query parameter at all — so an
   invariant worded about *bound parameters* does not reach them, and the new
   test's writer table cannot see them either.
3. `execute_bulk_close` binds `closed_by or ""` with no guard, leaving it the
   one parameter-binding writer in the file still exposed. Owned by
   `docs/specs/modules/bulk_close.md`, so correctly outside this gate.
4. The worker's own declared gaps, confirmed accurate rather than accepted:
   `set_ticket_assignee` (`app.py:1273`) and `set_member_assignment_override`
   interpolate and bind nothing, so a NaN there writes the literal text `'nan'`
   — the old silent bug, not a 400 — and they need parameters *before* a guard,
   as the worker said. `save_mn_api_key` and a NaN arriving as an int
   `member_id` are likewise uncovered.

### Fixed in
1. Not fixed — see report. One line (`bq_writes.py:201`), but it is a decision
   about what `skipped_reason` should hold, which belongs with the follow-up
   spec proposals rather than with a landing.
2. Not fixed — its own task. The gate's invariant does not cover
   `insert_rows_json`, so widening it here would be work nobody reviewed.
3. Not fixed — `bulk_close` owns it, so a task touching it names `bulk_close`
   as its `WT_MODULE`, not `bq_writes`.
4. Not fixed, by design: these writers must bind parameters first. A guard
   without parameters would paste the text `None` into the SQL, which is worse
   than the `'nan'` they write today.

No finding blocked the landing: the branch fixes the 400 a coach actually hit,
and the overseer confirmed a redeploy cannot reproduce that 400 through the two
unguarded writers, because neither binds anything.

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

1. File `docs/specs/modules/bq_writes.md`, Overview, next to the bind-every-value rule: a writer that binds a text value takes only a `str`; anything else (float NaN from the merged frame) is sent as NULL, never `""`, so `COALESCE(tm.assigned_to, gt.assigned_to)` falls through. Guarded by `tests/test_bq_writes_params.py::test_no_writer_binds_a_float`, which also fails if a new binding writer is not in its table.
2. Same file, `### One ticket at a time` and `### Follow-ups`: `update_ticket_meta` with a NaN `assigned_to` writes NULL and so skips the assignment refresh; `save_standard_reply` with a NaN `reply_id` inserts a new reply (same as None); `update_followup_status` sends a NaN `sent_at`/`skipped_at` as NULL.
3. Not covered, needs its own task: `set_ticket_assignee` and `set_member_assignment_override` paste values into the SQL, so NaN still becomes the text 'nan' there (app.py:1273 calls the first). They must first bind parameters; only then can the guard apply (None would paste as 'None'). Also `save_mn_api_key`, `queue_followup` (insert_rows_json, no parameters) and int arguments (`member_id` NaN into INT64).

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done: red test (29 failures on main, f-test commit), guard in nine writers, timestamp NaN test, full suite green (341).
In flight: nothing.
Next: wt-done.sh --check, queue row update, report to helpdesk-opzichter.
Traps (with dates): 2026-10-22 set_ticket_assignee and set_member_assignment_override still interpolate; a NaN there writes 'nan'.
