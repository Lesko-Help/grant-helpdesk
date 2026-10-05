# tests
Status: agreed 2026-10-05 (approved by Martin)
Kind: helper
Summary: the test suite — a plain `pytest tests/` stays offline; the live BigQuery smoke test runs only with `LIVE_SMOKE=1`, which `deploy.sh` sets

Part of: `docs/specs/INDEX.md` · Deploy: none (never shipped; `deploy.sh` runs it before shipping) · Updated: 2026-10-05
Reads: with `LIVE_SMOKE=1` only — live BigQuery through `bq_client` (tickets, app logs, team members).
Writes: with `LIVE_SMOKE=1` only — `_smoke_test_answered_` and `_smoke_test_closed_` rows merged into the production meta table, and one real ticket moved to another lane and back *(as-built)*.

## Overview

Says when each kind of test runs, so that running the tests never touches production by accident.
Owns: `tests/smoke_test.py`'s on/off switch, and the line in `deploy.sh` that runs the tests before a deploy.
Depends on: `pytest`; for the live run also `bq_client`, `config` and working BigQuery credentials; for `deploy.sh` a Python that has `pytest` installed.
Entry points: `pytest tests/` (offline run), `LIVE_SMOKE=1 pytest tests/` (live run), `deploy.sh` step 1.
*Not in scope:* what the 17 smoke tests check, the three of them that write to production (left as they are), what each offline test file checks (its own module's spec says), `tests/test_paste_links.cjs`.

Used by: every worktree session and the overseer's review (offline run); `deploy.sh` (live run).

## Functions

### pytest tests/  (offline run)

`python3 -m pytest tests/` with `LIVE_SMOKE` unset, empty, or anything other than `1`

*What it does:*
- R1: when `LIVE_SMOKE` is not exactly `1`, every test in `tests/smoke_test.py` is reported as SKIPPED, and the skip reason names `LIVE_SMOKE=1`.
- R2: when `LIVE_SMOKE` is not exactly `1`, no BigQuery client is created and no BigQuery call is made — not while pytest collects the file, and not while it runs.
- R3: R1 and R2 hold the same way when the file is named directly (`pytest tests/smoke_test.py`); the flag is the only switch.
- R4: all other test files run as before; none of them needs BigQuery or credentials.

*Examples:*
`python3 -m pytest tests/ -q` -> `141 passed, 17 skipped`, exit 0, nothing read from or written to BigQuery.
`LIVE_SMOKE=true python3 -m pytest tests/smoke_test.py -q` -> `17 skipped`, exit 0.

*Inputs:* the environment variable `LIVE_SMOKE`.

*Outputs:* pytest's report and exit code.

*Errors:* an offline test fails -> exit 1 -> no `BTB_ALERT` (a person is watching the run).

*Test:* `python3 -m pytest tests/test_smoke_opt_in.py -q` — it starts `pytest tests/smoke_test.py` as a child process with `LIVE_SMOKE` removed from the environment and with BigQuery's client constructor replaced by one that raises, so the proof itself can never reach production — observed: the child reports 17 skipped, 0 passed, 0 failed, exit 0, and its output names `LIVE_SMOKE=1` (R1, R2, R3); a second case sets `LIVE_SMOKE=true` and observes the same (R1) — red first against `origin/main`, where the same child run reports the 17 tests as failed or errored on the raising constructor instead of skipped.

### LIVE_SMOKE=1 pytest tests/  (live run)

`LIVE_SMOKE=1 python3 -m pytest tests/`, or with `tests/smoke_test.py` named directly

*What it does:*
- R1: when `LIVE_SMOKE` is exactly `1`, the 17 smoke tests run against live BigQuery, unchanged from before this switch existed.
- R2: `deploy.sh` step 1 runs the whole suite with `LIVE_SMOKE=1`, and a failure there still cancels the deploy.
- R3: `deploy.sh` runs the suite with the Python named in the environment variable `PYTHON` when that is set and not empty, and with `/opt/anaconda3/bin/python3` otherwise. It never falls back to a bare `python3`.
- R4: before it runs any test, `deploy.sh` checks that the chosen Python exists and can import `pytest`. When it cannot, `deploy.sh` prints the Python it tried and the line `PYTHON=/path/to/python ./deploy.sh`, runs no test, ships nothing and exits 1.

*Examples:*
`LIVE_SMOKE=1 python3 -m pytest tests/smoke_test.py -q` -> `17 passed`, exit 0; the two `_smoke_test_*` rows are merged again.
`./deploy.sh` with BigQuery unreachable -> smoke tests fail, "deploy cancelled", exit 1, nothing shipped.
`./deploy.sh` on Martin's machine, `PYTHON` unset -> step 1 runs under `/opt/anaconda3/bin/python3`.
`PYTHON=/opt/homebrew/bin/python3 ./deploy.sh` (no `pytest` there) -> message naming that Python and `PYTHON=/path/to/python ./deploy.sh`, exit 1, no test run, nothing shipped.

*Inputs:* `LIVE_SMOKE=1`, BigQuery credentials of whoever runs it; for `deploy.sh` also the optional `PYTHON`.

*Outputs:* pytest's report and exit code; the writes listed under `Writes:` above.

*Errors:* a smoke test fails -> exit 1 (and `deploy.sh` stops before shipping) -> no `BTB_ALERT` (run by hand, a person is watching). The chosen Python is missing or has no `pytest` -> exit 1 before any test -> no `BTB_ALERT` (same reason).

*Test:* `python3 -m pytest tests/test_smoke_opt_in.py -q` — it reads `deploy.sh` as text — observed: the line that runs `pytest tests/` sets `LIVE_SMOKE=1` (R2) — red first against `origin/main`, where that line has no flag. A second file, `python3 -m pytest tests/test_deploy_python.py -q`, runs a copy of `deploy.sh` from an empty temporary folder as a child process, with a stand-in `gcloud` first on `PATH` that only writes down that it was called and exits 1, so the proof itself can never ship anything — observed: with `PYTHON` pointing at a stand-in that writes down its arguments and exits 1, the stand-in was asked to run `pytest tests/`, the copy exits 1 and the stand-in `gcloud` was never called (R3); with `PYTHON` pointing at a stand-in that fails `import pytest`, the output names that stand-in and `PYTHON=/path/to/python ./deploy.sh`, the stand-in was never asked to run `pytest tests/`, the copy exits 1 and `gcloud` was never called (R4); and, reading `deploy.sh` as text, the Python used when `PYTHON` is unset is `/opt/anaconda3/bin/python3` (R3) — red first against `origin/main`, where the copy ignores `PYTHON` and runs a bare `python3`. R1 is not proven by an automated test, because proving it means writing to production: it is shown once by hand at the next real deploy, when step 1 reports the 17 smoke tests as passed, not skipped.

## Decisions

- 2026-10-05: the live smoke test is opt-in through `LIVE_SMOKE=1` and skipped otherwise. Why: every worker and every review runs `pytest tests/`, and each such run wrote to production.
- 2026-10-05: skipped, not hidden — the file stays where pytest finds it. Why: a run that shows "17 skipped" cannot be mistaken for a run that passed them.
- 2026-10-05: `deploy.sh` keeps running the live smoke test. Why: it is the only check that BigQuery works before a deploy ships.
- 2026-10-05: the three smoke tests that write to production stay as they are. Why: this change is about when the smoke test runs, not what it does; changing the writes is its own task.
- 2026-10-05: `deploy.sh` picks its Python itself — `PYTHON` when set, `/opt/anaconda3/bin/python3` otherwise — and checks it for `pytest` first. Why: a bare `python3` on Martin's machine is a Python without `pytest`, so step 1 failed unless he put another Python first on `PATH` by hand; only Martin deploys, from this one machine, so a path that fits this machine is accepted.
