# Brief: deploy-python-pick

Stages: oneshot — DOWNGRADED (dropped: product · architecture · design · slices)
Downgraded: repo default "groot" wanted product · architecture · design · slices.
Reason: Martin chose klein for this task on 2026-10-05: one small change to deploy.sh's test step, behaviour agreed in docs/specs/modules/tests.md (live run R3, R4)

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)


## Goal

deploy.sh picks its own Python for the test step (PYTHON if set, else /opt/anaconda3/bin/python3) and checks it for pytest first — build exactly live-run R3 and R4 of docs/specs/modules/tests.md

## Done when

`tests/test_deploy_python.py` (new file, this task writes it) proves R3 and
R4 of docs/specs/modules/tests.md's live-run section:
- R3: a copy of `deploy.sh`, run as a child process with `PYTHON` pointing
  at a stand-in Python, runs the suite through that stand-in, not a bare
  `python3`; and, read as text, `deploy.sh` falls back to
  `/opt/anaconda3/bin/python3` when `PYTHON` is unset.
- R4: with `PYTHON` pointing at a stand-in that fails `import pytest`,
  `deploy.sh` prints the Python it tried and the line
  `PYTHON=/path/to/python ./deploy.sh`, never runs the suite, and exits 1
  before a stand-in `gcloud` (first on `PATH`) is ever called.
Proven red first against `origin/main` (today's `deploy.sh` ignores `PYTHON`
and runs a bare `python3`, with no pytest check), then green after the
`deploy.sh` edit.

Spec: unchanged — the overseer already wrote R3, R4 and the decision behind
them into docs/specs/modules/tests.md (commit 9bbeccf, 2026-10-05) before
this worktree started; this task only makes `deploy.sh` match what is
already written there.

## May touch

Module: `tests` (docs/specs/modules/tests.md). Files: `deploy.sh` (step 1,
the test-runner line and the Python choice/check in front of it);
`tests/test_deploy_python.py` (new).

## Deploy implied

`deploy.sh` — the overseer re-deploys from `main` after the merge. No
Dataform tag; this module ships nothing of its own (see docs/specs/INDEX.md).

## Context

Goal and module spec are already on `main`: docs/specs/modules/tests.md,
"LIVE_SMOKE=1 pytest tests/ (live run)" section, R3/R4 and the 2026-10-05
decision line about `deploy.sh` picking its own Python. Prior commits on
this branch (523f69d, 9bbeccf, 8ed36f3) are the overseer writing that spec
and brief history before handing off; `a2d038f` is the prior task (R1/R2,
the `LIVE_SMOKE=1` opt-in) that this task builds on.

Overseer memory relay (arrived 2026-10-05, after this brief's sections above
were drafted but before the first commit):
1. Bare `python3` on this machine is `/opt/homebrew/bin/python3` (3.14, no
   pytest); only `/opt/anaconda3/bin/python3` has pytest and the project
   deps. Offline baseline on `origin/main`:
   `unset LIVE_SMOKE; /opt/anaconda3/bin/python3 -m pytest tests/ -q -p no:cacheprovider`
   -> `141 passed, 17 skipped`.
2. Never run this task's own test runs with `LIVE_SMOKE=1` — that writes to
   production; the proof here must not need it.
3. Never run the real `deploy.sh` and never call `gcloud`. The proof in
   `tests/test_deploy_python.py` runs only a COPY of `deploy.sh` from an
   empty temp folder, with a stand-in `gcloud` first on `PATH` (records the
   call, exits 1) and a stand-in Python via `PYTHON`.
4. May touch, confirmed by the overseer: the test step of `deploy.sh`,
   `tests/test_deploy_python.py`, and this brief. Keep `LIVE_SMOKE=1` on the
   pytest line (`tests/test_smoke_opt_in.py` reads `deploy.sh` as text and
   must stay green). Nothing else in `deploy.sh` changes.
5. Known and not mine to fix: pytest can fire a remote Dataform trigger
   (older open item, unrelated to this task).

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
