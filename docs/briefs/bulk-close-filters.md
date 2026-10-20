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
folder: repo root (`app.py`, `bq_reads.py`, `bq_writes.py`) and `tests/`
---

# Brief: bulk-close-filters

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Carry the three previewed filter values through to confirm, so the sweep closes exactly the rows the number counted

## Done when

The test that must go red then green: `test_r9_execute_filters_come_from_the_stored_preview` in `tests/test_bulk_close.py` (written first, red against the current `app.py`), plus a test that `preview_bulk_close` returns the three filter values it used. The full list is under Gate, below.

Spec: unchanged because specs are the overseer's; the proposal to drop R9's Open check entry is under Spec proposals.

# Gate — bulk-close-filters

Architecture and design: `docs/specs/modules/bulk_close.md`, R9 ("everything
the number depended on travels with the number") and its Open check. On main,
`f0e3143`.

## Product — why this first

The number is the consent. A coach presses Preview, reads "40 conversations
will be closed", changes the Status filter — and the confirm button is still on
screen, still saying 40. Pressing it sweeps with the *new* filter: `app.py`
recomputes the three filter values from the widgets every run, and execute
reads those, not the ones the number came from. Pre-existing, not from the lane
work; R9's `gt_cols` half was fixed this way already, so this finishes it.

## Slice order

1. Red first, before any production edit: a source-reading test in
   `tests/test_bulk_close.py` (`ast`, as R12's four already do — the login gate
   keeps AppTest off this panel) that the execute call's `status_filter`,
   `assigned_to` and `before_date` all come from the stored preview entry, and
   that the widget-derived locals are not referenced inside the confirm branch
   at all. On `origin/main` it goes red: all three read the widget locals.
2. `preview_bulk_close` returns the three filter values it used, as keys beside
   `gt_cols` — same shape and same reason, so any later caller is covered too.
   The panel keeps the whole result in `_bc_preview_<lane>` and the confirm
   button passes those values to `execute_bulk_close`.
3. Spec proposal back to the overseer, not a spec edit: R9's hand-off is then
   built, so its Open check entry goes.

## Done when

- Red-first output shown for the new test against `origin/main`, then green.
- `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q`
  passes, plus the app's own test file. Never bare `pytest tests/`: it runs
  `smoke_test.py`, which writes the live `ticket_metadata`.
- Preview is NOT cleared when a filter changes — the spec prefers carrying the
  values over snatching the number off the screen a coach is reading.
- May touch `bq_reads.py`, `app.py`, `bq_writes.py` and that test file — not
  the spec, not Dataform, not `coach_inbox.py`.

## Agentic review

### Verdict
Verdict: pass. Reviewed by helpdesk-opzichter 2026-10-20 at `9a1521f`, range
`f0e3143..9a1521f`. Verified independently, not from the worker's report: clean
tree after `git add -N .`; nothing touched under `docs/specs/`, `.claude/` or any
settings file; no new mutation against `private_chat`; 52 passed on
`tests/test_bulk_close.py`, `tests/test_app_followup_cache.py` and
`tests/test_raillog_app.py` from my own run, each file named, never bare
`pytest tests/`; `wt-done.sh --check` exits 0. The production diff is 20 lines
across `app.py` and `bq_reads.py`, and I read all of it: the confirm call now
takes all three filters plus `gt_cols` out of `_p`, and the Preview branch still
reads the widgets at `app.py:1433-1443`, so only what confirm sees changed.

Red then green, proven twice over. First the plain revert: both production files
back to `origin/main` with the worker's tests kept, in a scratch copy — all
three go red, the two `ast` tests on the widget locals and the preview test on
`KeyError: 'status_filter'`. Then four mutations of my own, none of them a
revert, each restored after: (1) one of the three arguments slipping back to
`_bc_before_val` while the other two stay correct — red on two guards, so a
partial fix cannot pass; (2) all three arguments correct but the confirm branch
still naming `_bc_status`, in the spinner text — red on the branch guard alone,
which is the case that earns that second test its place, since the arguments
are all right and only the reading is wrong; (3) `preview_bulk_close` reporting
`status_filter: ""` while counting with the real value, a preview that lies
about its own inputs — red; (4) the same function carrying only two of the
three keys — red. All four caught by the guard meant for them.

One strictness to know, not a hole: the first guard compares unparsed source
text against `_p['status_filter']` exactly, so aliasing the entry (`_f = _p`)
would read as red although the behaviour is right. That is the correct trade
here — the test's whole job is that the value comes from the stored entry and
nowhere else — but a future reader renaming `_p` must expect to update it.

Deviation, recorded not waived: the worker ran slices 1 to 3 in one go instead
of stopping after slice 1, and said so itself. It cost nothing here, because the
red-first proof survived and I re-proved it; the stop is for catching a wrong
direction after one slice instead of three. Reported to Martin, who decides
whether it needs more than the note I sent back.

Carried out of this review: the Conversations bulk-close panel still needs
Martin's hand check after deploy, since the login gate keeps AppTest off it —
now covering this change too, as it moves what that panel's confirm button
reads. The three spec proposals below read correctly and are mine to apply on
main after landing.

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

Module `bulk_close`. Files: `bq_reads.py` (`preview_bulk_close`), `app.py` (`render_bulk_close_panel`), `bq_writes.py` only if needed, and `tests/test_bulk_close.py`. Not the spec, not Dataform, not `coach_inbox.py`.

## Deploy implied

`deploy.sh` (Cloud Run, app code only), run by the overseer from main after landing. No Dataform change.

## Context

- 2026-10-20: the overseer's memory message had not arrived when this brief was committed; add its content here once it does.
- Spec: `docs/specs/modules/bulk_close.md` R9 and its Open check, on main at `f0e3143`.
- `app.py` `render_bulk_close_panel` (around line 1431) derives `_bc_status_val`, `_bc_coach_val`, `_bc_before_val` from the widgets on every run; the confirm button currently passes those to `execute_bulk_close`, while only `gt_cols` comes from the stored preview `_p`.
- No werk.queue row id is named in the Goal.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

Proposal 1, `docs/specs/modules/bulk_close.md`, section "Open check": delete the bullet "R9's filter hand-off is specified and **not built**", because it is built now (commit `7d28c87`).

Proposal 2, same file, rule R9: replace "Specified, not built; see the Open check." with "Built: `preview_bulk_close` returns `status_filter`, `assigned_to` and `before_date` beside `gt_cols`, and the confirm button passes those to `execute_bulk_close`. Guarded by `test_r9_execute_filters_come_from_the_stored_preview`, `test_r9_confirm_branch_does_not_read_the_filter_widgets` and `test_r9_preview_returns_the_three_filters_it_used`."

Proposal 3, same file, `### preview_bulk_close` entry: its return value is now `{will_close, skipped_followup, gt_cols, status_filter, assigned_to, before_date}`.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
In flight (file:line):
Next:
Traps (with dates):
