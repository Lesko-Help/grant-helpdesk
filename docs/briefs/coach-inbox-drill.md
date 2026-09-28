# Brief: coach-inbox-drill

Stages: oneshot — DOWNGRADED (dropped: product · architecture · design · slices)
Downgraded: repo default "groot" wanted product · architecture · design · slices.
Reason: one-line config change (env override of an existing constant, default unchanged) for the coach-inbox fire drill; Martin chose this route 2026-09-28; design is already agreed in the coach_inbox spec

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)


## Goal

Make config.PRIVATE_CHAT_DATASET overridable by env var PRIVATE_CHAT_DATASET (default unchanged, lesko-486515.private_chat), so the overseer can fire-drill the coach-inbox BTB_ALERT by pointing the live service at a non-existent dataset. Test proves default and override, red first. No other change.

## Done when

New file `tests/test_config.py`, function `test_private_chat_dataset_env_override`:
- with env var `PRIVATE_CHAT_DATASET` unset (deleted, then `importlib.reload(config)`),
  `config.PRIVATE_CHAT_DATASET == "lesko-486515.private_chat"` (today's default, unchanged).
- with `PRIVATE_CHAT_DATASET` set to a throwaway value (e.g. `"no-such-project.no-such-dataset"`),
  then `importlib.reload(config)`, `config.PRIVATE_CHAT_DATASET` equals that value.
- the env var is restored (monkeypatch.delenv/setenv, or an explicit
  try/finally + a final reload) so later tests still see the default —
  config is read at import time, so a leaked override would poison every
  test that imports config after this one.
Proven red first: today's `config.py` hardcodes the string, so the override
half of the test fails against the unmodified file. Green after the one-line
change in `config.py`.

Spec: unchanged because `docs/specs/modules/coach_inbox.md`'s R1 already
describes `config.PRIVATE_CHAT_DATASET` as "default `lesko-486515.private_chat`"
— wording that already allows a non-default value; only the default itself
would be a spec change, and it does not change.

## May touch

Module: coach_inbox (this env override exists so the overseer can fire-drill
the coach-inbox BTB_ALERT by pointing the live service at a non-existent
dataset — see docs/specs/modules/coach_inbox.md, "R1" and the SOURCE_FAILED
decision dated 2026-09-25).

Files: `config.py` (one constant becomes env-overridable, default unchanged),
`tests/test_config.py` (new).

## Deploy implied

`deploy.sh` (app) — the Cloud Run service picks up the new env var only once
redeployed from `main` with `PRIVATE_CHAT_DATASET` set in its environment for
the drill, then unset/redeployed to return to the default. The overseer runs
this, never this worktree.

## Context

From the overseer's message (2026-09-28, plan + traps for this task):
1. Run tests with `/opt/anaconda3/bin/python -m pytest tests/ -q -p no:cacheprovider`
   — the system `python3` has no pytest installed.
2. `config.py` already has one env-switch precedent, `HELPDESK_PREVIEW=1`
   (see `config.py` lines ~10-13) — follow that style: `os.getenv(...)`,
   comment explaining why, unset keeps today's behaviour.
3. `config` is read at import time, so the test must set/clear the env var
   and then `importlib.reload(config)`; restore the env afterwards so other
   tests importing config still see the default.
4. Tests must not reach live BigQuery or Dataform write paths — this change
   doesn't touch them; keep it that way.
5. The overseer's message also asked for a plain-language comment on the
   setting saying why it exists (the fire-drill use), which this brief's
   Done-when folds into the one-line change.

Baseline: `/opt/anaconda3/bin/python -m pytest tests/ -q -p no:cacheprovider`
passed 116/116 before this change (run 2026-09-28, no test_config.py yet).

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done: brief filled and committed as first commit.
In flight (file:line): about to write tests/test_config.py (red first), then
the one-line env-override change in config.py.
Next: write the failing test, confirm red, make config.py change, confirm
green, run full suite, merge origin/main, wt-done.sh --check, report.
Traps (with dates):
- 2026-09-28: config is read at import time — any test touching
  PRIVATE_CHAT_DATASET must importlib.reload(config) after setting/clearing
  the env var, and restore the env afterwards or later tests leak the override.
- 2026-09-28: use /opt/anaconda3/bin/python -m pytest tests/ -q
  -p no:cacheprovider — system python3 has no pytest.
