---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: BigQuery insert_rows_json
module: bq_writes
spec: docs/specs/modules/bq_writes.md
folder: bq_writes.py, tests/
---

# Brief: nan-insert-guard

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

The three bq_writes writers that insert rows as JSON coerce every non-text argument before the row dict is built, so a float NaN can never reach BigQuery as a bare NaN nor as the text nan

## Done when

`tests/test_bq_writes_inserts.py` (new): fakes the client, calls `post_comment`, `log_rsvp`, `queue_followup` with `float("nan")` per non-text argument, asserts no value in the row is a float and none is the text `nan`. Red on `origin/main` first, then green. Plus a completeness guard: every writer calling `insert_rows_json` appears in the case table.

One fixed extra line, always present, naming the module this task belongs to:
Spec: unchanged because the three write-group sections are `spec:stub`; proposals below.

# Gate — nan-insert-guard

Design: `docs/specs/modules/bq_writes.md`, its three write-group sections (one ticket, follow-ups, settings and events). Main `d38bd01`.

## Product — why this first

`nan-param-guard` landed today and guards the eleven writers that bind query
parameters. `post_comment`, `log_rsvp` and `queue_followup` bind nothing: they
hand a row dict to `client.insert_rows_json`, so an invariant worded about
bound parameters never reaches them, and its test's table cannot see them.
`queue_followup` is "Schedule a follow-up" on a member question — the same
screen path that gave Misty a 400 yesterday, and its `member_name` comes from
the frame `merge_into_tickets` fills with float NaN.

Both of yesterday's failure shapes are reachable here, verified not assumed:
`insert_rows_json` sanitises nothing and `google.cloud._http` does
`json.dumps(data)` with NaN allowed, so a bare `NaN` reaches BigQuery, which
answers 400. Nothing raises locally, so the test must inspect the row handed
to the client. Wrapped in `str()`, the same NaN becomes the text 'nan'.

## Slice order

1. Red first, before any production edit: a test faking the client, calling
   each writer with `float("nan")` per text argument, asserting no value in
   the row dict is a float and none is the text 'nan'. Red on `origin/main`.
2. Reuse `_text_or_none`; no second helper. Coerce *before* any `str()`, or
   the fix itself writes 'nan'. Keep each field's present empty-value
   behaviour — one written `v or ""` keeps `""`, a raw one becomes None — so
   only whether NaN can arrive changes, nothing about the schema.
3. A completeness guard, as in `test_bq_writes_params.py`: every writer here
   calling `insert_rows_json` must appear in the test's case table.
4. Spec proposals back to the overseer, not spec edits.

## Done when

- Red-then-green output for slice 1 against `origin/main`.
- `pytest tests/test_bq_writes_inserts.py -q`, then `tests/
  --ignore=tests/smoke_test.py`, via `PATH=/opt/anaconda3/bin:$PATH python -m`.
- May touch `bq_writes.py` and its test files only — not `bq_base.py` (same
  hole, swallowed; no spec owns it), not `jobs/*`, not `app.py`, not the spec.

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

Module `bq_writes`: `bq_writes.py`, `tests/test_bq_writes_inserts.py`. Nothing else.

## Deploy implied

`deploy.sh` (Cloud Run app) after landing; run by the overseer.

## Context

2026-10-22: the overseer's memory message had not arrived when this was committed. The three writers are in `bq_writes.py`; the spec sections for them are stubs. `event_id` (INTEGER) and `member_id` (wrapped in `str()`) are also NaN-reachable, so they are covered too.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

- File `docs/specs/modules/bq_writes.md`, sections "One ticket at a time", "Follow-ups", "Settings and events" (stubs). Proposed text for `post_comment`, `log_rsvp`, `queue_followup`: each writer hands a row dict to `insert_rows_json`, which sanitises nothing. Invariant: no value in that row is a float or the text `nan`. A text argument that is not a str becomes NULL (via `_text_or_none`); `rsvped_by` and `member_name` keep `""`; `member_id` NaN becomes `""`; `event_id` NaN becomes NULL. Why: NaN comes from `merge_into_tickets`. Guard: `tests/test_bq_writes_inserts.py`.
- Two small helpers were added next to `_text_or_none`: `_integer_or_none` (INTEGER column) and `_member_id_text` (id wrapped in `str()`); `_text_or_none` cannot serve either.
- Same hole remains in `bq_base.py` (swallowed there), out of scope.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done: red test, fix, full suite green (356).
In flight (file:line): none
Next: merge origin/main, wt-done --check, report.
Traps (with dates):
