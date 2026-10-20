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

2026-10-20, overseer's memory message: the bug is live, since the Tickets-tab button today also closes Conversations rows. Both callers go through `bulk_close_rows_sql`, and `bq_writes` imports `bq_reads` for it (Martin's choice over a third module). Lanes are the same tables: Tickets is `load_tickets(lane="question")`, Conversations `load_tickets(lane=config.LANE_GENERAL)` at `app.py:1880`; `coach_inbox.py` is not needed. Martin's decision of 2026-10-20: the Conversations sweep has the same three filters as Tickets, reusing the panel with a lane argument; read R11 and R12, not the older bullets.

Traps from the message: never bare `pytest tests/` (it writes live `ticket_metadata`). The R9 fixture test compares line multisets with exact equality; add the lane lines to the allowed `added` list per case, never regenerate the fixture and never loosen to substring containment. R3 stays per caller, R10 belongs to `bq-writes-params`, leave both alone.

Spec: `docs/specs/modules/bq_writes.md` R9, R11, R12 (on main, `68f5971`). Today the Tickets sweep (`app.py:1880` area) has no lane condition and so closes `general` rows too.

Design note: `_live_lane_expr` reads `tm` and `gt`, which exist only inside the helper's `base` CTE, so the lane goes in as a `lane` column of `base` and a `t.lane = ...` condition in the WHERE.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

All proposals are for `docs/specs/modules/bq_writes.md`; this branch edits nothing under `docs/specs/`.

### 1. R11: the gt_cols hand-off and the test counts

Spec now: R11 says the helper takes `gt_cols` and never probes, and gives `execute_bulk_close(..., *, lane)` and `preview_bulk_close(..., *, lane)` as the signatures. It says nothing about who probes, and the Test paragraph says 18 tests and names R2, R3, R4 and R9.

Proposed text, to add to R11: preview probes `_tickets_cols()` once and returns the sorted list as a third key, `{"will_close", "skipped_followup", "gt_cols"}`. Execute takes `gt_cols` as a keyword (default `None`, meaning probe now) and the panel always passes the list preview returned. Why: the schema cache lives five minutes (`bq_base._TICKETS_COLS_TTL_SEC`) and a coach can take longer between Preview and confirm; if the Dataform migration adds `lane` in that gap, two probes would build different lane expressions and execute would close more rows than the coach agreed to.

Proposed signature lines: `execute_bulk_close(status_filter, assigned_to, before_date, closed_by, *, lane, gt_cols=None)` and a preview return of `{"will_close": N, "skipped_followup": M, "gt_cols": [...]}`.

Proposed Test paragraph: `tests/test_bulk_close.py` now holds 44 tests and also guards R11 (helper, preview and execute each confine to one lane, in both `gt_cols` branches; no lane raises; the helper never probes; execute given preview's `gt_cols` builds the byte-identical lane expression) and R12. The R9 fixture test pins the lane as deliberate differences: the `AS lane` column written out literally, the comma it puts on the line before, and a per-case WHERE line equal to the fixture's own plus `AND t.lane = 'question'`. It stays exact multiset equality and the fixture is not regenerated. Proven to bite: an extra condition, a dropped lane predicate, a sweep ignoring its lane, and a silent change of the lane expression each turn all 8 fixture cases red.

### 2. R12: the key function and how it is guarded

Spec now: R12 says the panel is one renderer taking the lane and every key carries the lane, but names no function and no test.

Proposed text, to add to R12: the keys come from one pure function in `app.py`, `bulk_close_keys(lane)`, returning the widget keys `bc_status_<lane>`, `bc_coach_<lane>`, `bc_before_<lane>`, `bc_preview_<lane>`, `bc_execute_<lane>` and the session-state key `_bc_preview_<lane>`. The renderer is `render_bulk_close_panel(lane, team_members, current_user)`, called with `config.LANE_QUESTION` from Tickets and `config.LANE_GENERAL` from Conversations. The login gate keeps AppTest off this panel, so four tests read `app.py` as source with `ast`: the two lanes' key sets are disjoint and every key carries its lane; no bare `bc_` string exists outside `bulk_close_keys`; there is exactly one preview call and one execute call, both passing `lane=lane`, execute also passing `gt_cols=_p['gt_cols']`; and each tab calls the renderer with its own lane. The panel itself has had no visual check; it needs a hand check after deploy.

### 3. R9: everything the number depended on travels with the number (pre-existing)

Spec now: R9 says preview and execute select the same rows, and guards that at the SQL level.

The gap: on `origin/main`, before this branch, the confirm button already recomputes the filter values from the widgets on every run. A coach can press Preview, change the Status filter, and press confirm while the old number is still on screen; the sweep then runs with the new filters. That is R9 failing through the UI instead of through the SQL, and it strikes the one number that carries consent. It is pre-existing; this branch neither causes nor worsens it, and the panel body is unchanged here apart from keys, lane, noun and the `gt_cols` hand-off.

Proposed clause for R9: the preview result carries every input its number depended on, and execute runs with those, not with the widgets as they are at confirm time. Concretely, store the three filter values in the lane's preview entry next to `gt_cols`, and have the confirm button pass them to `execute_bulk_close`. This is the same shape and the same fix as the `gt_cols` hand-off. Prefer this over clearing the preview on every filter change, which would hide the number the coach is looking at.

Proposed test: a source-reading test that the execute call's `status_filter`, `assigned_to` and `before_date` come from the stored preview entry, and that changing a widget after Preview does not change them. Needs its own slice; not in this gate.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done (2026-10-20), all accepted by `helpdesk-opzichter` up to slice 3; slice 4 reported, reply pending:
- Slice 1, `47abfe1`: R11 lane tests, red first (19 failed, 19 passed on the old base).
- Slice 2, `c822aeb`: `lane` required keyword on `bulk_close_rows_sql`, `preview_bulk_close`, `execute_bulk_close`. The helper also takes `gt_cols` and never probes. Preview returns `gt_cols` (sorted list); execute takes `gt_cols=None` and the panel always passes preview's.
- Slice 3, `d3f7935`: R9 fixture test pins the lane lines (`_LANE_COLUMN` written out literally, comma pair, per-case WHERE pair from `_allowed_for`). Fixture not regenerated, comparison still exact.
- Slice 4, `3a0555d` (one bq_base import line) and `fbb687b`: `bulk_close_keys(lane)`, `render_bulk_close_panel(lane, team_members, current_user)` in `app.py`, called from both tabs; R12 tests read `app.py` as source with ast.
- Suite: `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q` gives 44 passed; `tests/test_app_followup_cache.py` and `tests/test_raillog_app.py` give 5 passed.

In flight: nothing uncommitted. Waiting for the overseer's reply to "slice 4 done - continue or re-steer?".

Next (slice 5 and landing):
1. DONE: spec proposals written under `## Spec proposals` (R11 hand-off, R12 key function, R9 stale-filters clause). Slice 4 accepted by the overseer, who said finding (a) goes in as a proposal only.
2. Merge `origin/main` once, then `git add -N .`, check `git status` is clean.
3. Run `wt-done.sh --check bulk-close-convo` until it exits 0. Never fill the `Verdict:` line.
4. Read the werk.queue row id from the Goal (it names none so far, so write nothing and say so) and report to `helpdesk-opzichter [434020]` (use the ref, the bare name is ambiguous): branch, range `5f25bc4..HEAD`, HEAD sha, summary, red-then-green proof, deploy implied (`deploy.sh`, app plus both bq modules, no Dataform).

Traps (with dates):
- 2026-10-20: never bare `pytest tests/` (it runs `smoke_test.py`, which writes live `ticket_metadata`).
- 2026-10-20: do not tidy `_LANE_COLUMN` in the test into a call to `bq_reads._live_lane_expr`; the fixture test is the only guard that catches a silent change to the expression.
- 2026-10-20: the schema cache lives five minutes (`bq_base._TICKETS_COLS_TTL_SEC`), hence the `gt_cols` hand-off from preview to execute.
- 2026-10-20: a heredoc followed by a stray `cat > /dev/null` hangs the shell on stdin; do not add one.
- 2026-10-20: `SendMessage` to `helpdesk-opzichter` needs the ref `[434020]` (four sessions share the name).
- 2026-10-20: pre-existing, not fixed: the confirm button runs with the filter widgets as they are NOW, not as at Preview time, so the sweep can differ from the number shown (R9-relevant). Goes in the spec proposals and the report.
