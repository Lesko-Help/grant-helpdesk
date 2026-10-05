# Brief: smoke-test-opt-in

Stages: oneshot — DOWNGRADED (dropped: product · architecture · design · slices)
Downgraded: repo default "groot" wanted product · architecture · design · slices.
Reason: Martin chose klein for this task on 2026-10-05: one small switch, behaviour already agreed in docs/specs/modules/tests.md

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)


## Goal

pytest tests/ no longer touches live BigQuery: tests/smoke_test.py is skipped unless LIVE_SMOKE=1, and deploy.sh sets that flag — build exactly what docs/specs/modules/tests.md says

## Done when

`python3 -m pytest tests/test_smoke_opt_in.py -q` passes. That file does not
exist yet — writing it is the first task. It must prove, per
docs/specs/modules/tests.md's two Test lines:
- a child `pytest tests/smoke_test.py` run, with `LIVE_SMOKE` unset and with
  BigQuery's `Client` constructor replaced by one that raises, reports all 17
  tests SKIPPED (not passed, not failed/errored), exit 0, and the skip reason
  names `LIVE_SMOKE=1` — same result with `LIVE_SMOKE=true` (not exactly `1`).
- `deploy.sh`'s line that runs `pytest tests/` sets `LIVE_SMOKE=1`.
Proven red first against `origin/main` (old `smoke_test.py`/`deploy.sh`: the
child run fails/errors on the raising constructor instead of skipping; the
deploy.sh line has no flag), then green after the change.

Spec: unchanged because docs/specs/modules/tests.md was already agreed by
Martin and committed on this branch before this worktree started (commit
2419078) — this task builds exactly what it already says.

## May touch

Module: `tests` (docs/specs/modules/tests.md). Files: `tests/smoke_test.py`
(the on/off switch at its top, before the `bq_client`/`config` imports),
`deploy.sh` (only the one line that runs `pytest tests/`, nothing else in that
file — an older "deploy.sh python fix" item from 2026-09-29 is not part of
this task), and the new `tests/test_smoke_opt_in.py`.

## Deploy implied

`deploy.sh` — this worktree changes its pytest line but never runs it. The
flag takes effect the next time the overseer runs `deploy.sh` from `main`
after this branch lands.

## Context

Memory from the overseer (helpdesk-opzichter), received 2026-10-05, after this
brief's first commit was already in flight — folded in here rather than left
to arrive separately:
- TRAP 2026-09-29: `pytest tests/` also runs `tests/smoke_test.py`, which
  reads live BigQuery and MERGEs `_smoke_test_*` rows into the production
  META_TABLE. Until this change lands, run the suite as
  `python3 -m pytest tests/ -q -p no:cacheprovider --ignore=tests/smoke_test.py`
  (138 passed on 2026-09-29). Never run `tests/smoke_test.py`, or a plain
  `pytest tests/`, without BigQuery's client constructor replaced — that
  includes the red proof against `origin/main` for this very task.
- Found 2026-10-05 (overseer, reading code): `tests/smoke_test.py` imports
  `bq_client` and `config` at the top of the file, and there is no pytest
  config or `conftest.py` in the repo. Confirmed by reading `bq_base.py`:
  `import bq_client` runs `bq_base.py`'s module-level
  `bigquery.Client(project=config.PROJECT_ID)` immediately — so the skip
  check must run and exit (`pytest.skip(..., allow_module_level=True)`)
  *before* those imports, not via a `skipif` marker alone (a marker still
  lets collection import the module first).
- DECISION BY MARTIN 2026-10-05: switch is `LIVE_SMOKE=1`; without it the 17
  tests show SKIPPED (file stays collected, not hidden). `deploy.sh` sets the
  flag itself and keeps cancelling on failure. The three smoke tests that
  write to production stay exactly as they are — not this task.

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
