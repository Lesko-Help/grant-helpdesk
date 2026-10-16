---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: <fill in>
module: alert_payloads
spec: docs/specs/modules/alert_payloads.md
folder: <fill in>
---

# Brief: dataform-silence-alert

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Build the silence alert for the grant-helpdesk Dataform pipeline: a counter metric over its completion log plus a conditionAbsent policy that pages after an hour without a successful run

## Done when

`tests/test_deploy_alerts_payloads.py`, new cases over `dataform_silence_policy` and `DATAFORM_COMPLETION_LOG_FILTER`, run as `pytest tests/test_deploy_alerts_payloads.py` (never bare `pytest tests/`). Red first: the builder does not exist on `origin/main`, so the import fails and every case is red; green once R1-R10 of the spec hold.

Slice 2 adds a source-walk case over `jobs/deploy-alerts.sh`: the metric block comes before the `apply_policy` call that names it. Red first by moving the block after the call.

Spec: unchanged because the spec was agreed 2026-10-16 and this implements it as written.

# Gate: silence alert for the grant-helpdesk Dataform pipeline

## Product

Problem: `jobs/poll_dataform_failures.py` pages when a Dataform run FAILS. A run
that never starts writes no log line, so nothing pages. Global rule 4, "Silence
is a failure", is unmet for the pipeline itself.

User: Martin, on the BTB-ALERT mail. It says the Dataform pipeline has not
completed a run in an hour, so the coaches' ticket list is going stale. He opens
the `grant-helpdesk-5min` workflow config, reads the last invocation, and either
restarts it or chases the upstream break.

One missed tick must not page. The config runs `5,35 * * * *` Europe/Amsterdam
and the window is 3600s, two ticks: a transient miss stays quiet, a stopped
pipeline pages within the hour. A rail that pages on noise gets muted.

Success: the policy exists in `bigtribebuilders`, is enabled, and its absence
would have shown on a real stoppage. Martin waived the break-it-on-purpose drill
("skip the drill", 2026-10-16) — this is not a claim the alert fired.

Not in scope: no change to `poll_dataform_failures.py`; no second alert for the
Monday `grant-helpdesk-weekly-prompt` config; no SMS, this rail touches no money.
Mock-up: no screen — the output is a Cloud Monitoring policy and an email.

## Slices

1. Payload builder in `jobs/alert_payloads.py`: in = workflow config, project,
   channel; out = the metric filter plus a conditionAbsent policy, 3600s,
   matching the three sibling Dataform silence policies. Proof: red-then-green on
   `pytest tests/test_deploy_alerts_payloads.py` — absent on `origin/main`.
2. Deploy wiring in `jobs/deploy-alerts.sh`: create the counter metric first,
   then apply the policy that references it; both create-or-reconcile. Proof:
   run it twice, the second run changes nothing.

Never bare `pytest tests/` — `tests/smoke_test.py` writes live `ticket_metadata`.

Design: docs/specs/modules/alert_payloads.md (agreed 2026-10-16) — the payload, the filter, the window, and why conditionAbsent.

## Agentic review

### Verdict
Verdict: pass. Reviewed 2026-10-16 by the overseer over `git diff origin/main...HEAD`, then re-verified after slice 3. The spec's R1-R10 all hold in code, the two guards that could not go red now can, and `jobs/` is byte-identical between `fa27891` and `e2779b1`, so tightening the tests moved nothing that ships.

### Findings
1. `test_deploy_script_dataform_metric_reconciles_like_the_others` did not constrain the error path — replacing the `else ... exit 1` branch with a warn-and-continue left all 52 tests green. The one failure shape this repo's rules single out was unguarded.
2. The `metric_name_agrees` half of `test_deploy_script_dataform_title_keeps_btb_alert_prefix_and_metric_name_agrees` was a tautology — it regexed the name out of the script and asserted the builder interpolated it, true for any string. Renaming the metric to `totally_wrong_metric_name` left all 52 green.
3. `DATAFORM_COMPLETION_LOG_FILTER` is the first multi-line filter in `deploy-alerts.sh`. If gcloud normalises the newlines, the "exists and matches — leaving it" branch never hits and every deploy re-issues an update. Harmless, but it is exactly what slice 2's own "run it twice, the second run changes nothing" was meant to prove, and that was never run.
4. `test_cli_dataform_verbs_match_direct_calls` compares the CLI output to the builder — a fair round-trip, and the spec asks for it, but it pins no value. Noted so it is not counted as value coverage.

### Fixed in
1. Fixed in `e2779b1`. The test now slices the source from the `elif ... NOT_FOUND` line to the branch's closing `fi` and asserts that branch carries an `exit 1`. Re-verified independently: warn-and-continue gives 1 failed / 51 passed, "an unexpected describe error must stop the script, not carry on".
2. Fixed in `e2779b1`. The literal `grant_helpdesk_dataform_succeeded` is now typed in the test file (`tests/test_deploy_alerts_payloads.py:647`, and as a module constant at `:491`) and the script's value compared against it. Re-verified: the rename gives 1 failed / 51 passed, `assert 'totally_wrong_metric_name' == 'grant_helpdesk_dataform_succeeded'`.
3. Not fixed — only a live run can tell. It is the overseer's check at deploy: run `jobs/deploy-alerts.sh` twice and read the second run's output.
4. Not fixed — left deliberately, as a round-trip is what it is for.

### Known limit of guard 1
The tightened error-path test proves the text `exit 1` sits inside the right branch, not that the branch exits. The slice is tight — moving the `exit 1` into the neighbouring `NOT_FOUND` branch reddens it, and deleting it outright reddens it — but wrapping it in a nested `if false; then ... fi` inside the same branch keeps the suite at 52 while the error path no longer stops. The nested `fi` is indented, so the test's end-marker steps over it. Accepted: it catches the regression someone would actually write (dropping or softening the exit), and closing the rest means running the branch under `bash` with a stubbed `gcloud` and reading its exit status. That is a worthwhile follow-up, not a condition of landing.


## May touch

Module: `alert_payloads`. Files: `jobs/alert_payloads.py`, `jobs/deploy-alerts.sh`, `tests/test_deploy_alerts_payloads.py`, this brief. Nothing else.

## Deploy implied

`jobs/deploy-alerts.sh`, run by hand from main after the merge (it ships in no image). It creates the log metric and the policy in `bigtribebuilders`. No `deploy.sh`, no Dataform change.

## Context

2026-10-16, overseer's memory message (arrived after the first commit):

Superseded: "conditionThreshold sum<1 with evaluationMissingData, not conditionAbsent" is wrong. A log-based counter metric is sparse (12 points in 6h for `btbr_core_30min_succeeded`, not 36), and three live Dataform silence policies use conditionAbsent. Closest analogue is `elin-crm-all`: 3600s, 300s, ALIGN_SUM/REDUCE_SUM. The `evaluationMissingData` trap does not apply.

Trap, confirmed: a log metric counts only entries written after it exists, and conditionAbsent fires only for a series already seen. So the metric is created before the policy (R10). A cold deploy may sit without a series until the first SUCCEEDED run; that is expected, do not seed anything.

Live evidence, 2026-10-16: the 16:35:29Z scheduled run carries `workflowConfigId="grant-helpdesk-5min"`; manual runs at 16:21 and 16:08 carry no `workflowConfigId`. So the pin also keeps hand-run invocations from resetting the silence clock. Do not loosen the filter. The config now runs `5,35 * * * *` Europe/Amsterdam; some repo docs still say `*/30` and are stale.

Known weak spot, deliberately left alone: `find_policy` treats a failed GET as absent, and the `same_policy` round-trip is self-derived, so only a second live run really proves it.

Constants: project `bigtribebuilders`, region `europe-west1`, channel `4324299381952164741`, autoClose `604800s`.

Slice 1 red-then-green: the import failed before the builder existed; flipping `SUCCEEDED` to `FAILED` in the filter turned `test_dataform_filter_pins_config_and_succeeded_state` red (1 failed, 47 passed), reverted, 48 passed.

Spec: `docs/specs/modules/alert_payloads.md` (agreed 2026-10-16), R1-R10 and the Decisions section. Martin waived the break-it-on-purpose drill (2026-10-16), a deliberate exception to global rule 5.

Trap: pausing `grant-helpdesk-5min` for a drill fails unless the PATCH body also carries `releaseConfig`.

The Goal names no `werk.queue row <id>`, so no exit state is written on a queue row.

Slice 2 red-then-green: the 4 script cases were red before the Dataform block existed; moving the `apply_policy` call ahead of the metric block turned the ordering test red, restored.

Slice 3 (overseer review, two guards that could not go red). Guard 1: replacing the `else ... exit 1` branch of the Dataform metric block with a warn-and-continue turned `test_deploy_script_dataform_metric_reconciles_like_the_others` red (1 failed, 51 passed, "an unexpected describe error must stop the script, not carry on"), restored. The test now checks `exit 1` inside that branch only. Guard 2: renaming the script's metric to `totally_wrong_metric_name` turned `test_deploy_script_dataform_title_keeps_btb_alert_prefix_and_metric_name_agrees` red (1 failed, 51 passed, the literal `grant_helpdesk_dataform_succeeded` no longer matches), restored. The file is 52 passed again, and `jobs/` is unchanged by this slice.

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
