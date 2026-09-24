# Brief: alert-threshold-fix

Stages: review — DOWNGRADED (dropped: product · architecture · design · slices)
Downgraded: repo default "groot" wanted product · architecture · design · slices.
Reason: Martin 2026-09-24: follow-up one-field fix to the review-only alert-renotify-metric task

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

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
diff. Record the verdict, fix what needs fixing, commit, then report
again the normal way.

wt-done.sh's check on this is literal: it greps this brief for a line
starting with exactly `Verdict:` at the very start of the line (column 0)
— no bold, no indent, no renamed label, no different case. Keep the
`Verdict:` line reading exactly as it does above, or the guard cannot see
it and treats the brief as not yet reviewed.


## Goal

Make jobs/deploy-alerts.sh create the renotifying threshold policy: the API rejects evaluationMissingData EVALUATION_MISSING_DATA_NO_OP with duration 0s ('Conditions setting evaluation_missing_data must have a non-zero duration') — drop the field (UNSPECIFIED = NO_OP) and add a test pinning that it is absent or paired with non-zero duration

## Done when

`tests/test_deploy_alerts_payloads.py` (run with `python3 -m pytest
tests/test_deploy_alerts_payloads.py` — only this file; others reach live
Dataform) passes, including two new/changed tests:

1. A new test asserting `threshold_policy()`'s `conditionThreshold` has no
   `evaluationMissingData` key, or — if some future edit reintroduces it —
   that it is paired with a `duration` other than `"0s"`. Proved red first
   against today's payload (`evaluationMissingData:
   EVALUATION_MISSING_DATA_NO_OP` + `duration: "0s"`), then green after the
   field is dropped.
2. `test_threshold_policy_stays_open_for_a_full_day`'s
   `evaluationMissingData` assertion is removed (the field it checked no
   longer exists) while its `alignmentPeriod`/`perSeriesAligner` assertions
   stay.

Checked offline (not a committed test — a one-off scratch repro, see report
to overseer): `deploy-alerts.sh`'s create-policy path pipes the API's error
JSON through a `python3 -c` snippet that calls `sys.exit(1)` on an `"error"`
key; reproduced that exact snippet standalone under `set -euo pipefail` with
the live error JSON as input and confirmed the enclosing script exits 1
without reaching any later line. No code change needed there — `pipefail`
already propagates it correctly.

Spec: unchanged because this repo has no `docs/specs/` tree yet (checked —
`docs/specs` does not exist), so there is nothing to update.

## May touch

Module: `jobs` (the alerts deploy script and its payload builder — the
smallest thing deployed on its own via `jobs/deploy-alerts.sh`).

- `jobs/alert_payloads.py` — drop `evaluationMissingData` from
  `threshold_policy()`'s `conditionThreshold`.
- `tests/test_deploy_alerts_payloads.py` — new/changed assertions per Done
  when.

## Deploy implied

`jobs/deploy-alerts.sh` (PROJECT=bigtribebuilders, JOB=poll-dataform-failures).
Not run from this worktree — the overseer re-runs it live from `main` after
landing, per its message below.

## Context

Overseer message, 2026-09-24 ~10:25Z (helpdesk-opzichter, live run of
`jobs/deploy-alerts.sh` from `main` 406e2b7):
- The log-match policy "exists and matches"; the log metric
  `poll_dataform_failures_btb_alert_count` was created.
- Creating `BTB-ALERT bigtribebuilders — poll-dataform-failures reported a
  BTB_ALERT (renotifies every 24h)` failed with: "Field
  alert_policy.conditions[0].condition_threshold.evaluation_missing_data had
  an invalid value of "EVALUATION_MISSING_DATA_NO_OP": Conditions setting
  evaluation_missing_data must have a non-zero duration."
- Cause: `jobs/alert_payloads.py` `threshold_policy()` sets
  `"evaluationMissingData": "EVALUATION_MISSING_DATA_NO_OP"` together with
  `"duration": "0s"`.
- Fix: drop `evaluationMissingData` entirely (the API docs say
  `EVALUATION_MISSING_DATA_UNSPECIFIED` is equivalent to `NO_OP`). Keep
  `duration: "0s"` so one line still fires at once. Keep `alignmentPeriod
  86400s` and `renotifyInterval 82800s` unchanged, and keep the existing test
  asserting `renotifyInterval < alignmentPeriod`.
- Run only `tests/test_deploy_alerts_payloads.py` — other tests reach live
  Dataform (`bq_writes.trigger_assignment_refresh`).
- No live gcloud in this worktree; the live re-run against
  `bigtribebuilders` is the overseer's, after landing.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
In flight (file:line):
Next:
Traps (with dates):
