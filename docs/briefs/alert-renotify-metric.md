# Brief: alert-renotify-metric

Stages: review — DOWNGRADED (dropped: product · architecture · design · slices)
Downgraded: repo default "groot" wanted product · architecture · design · slices.
Reason: Martin 2026-09-24: one-script alert-policy change, review-only is enough

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Agentic review

### Verdict
Verdict: changes requested — round 4, 1 finding (blocker #9), fixed on top (no history rewrite); reported back.

### Findings
Round-3 review of fc1f911..3f7842e, from the overseer's review subagent:
1. [blocker] deploy-alerts.sh:250-259 — log-match policy's alertStrategy still carried notificationChannelStrategy (renotifyInterval 86400s), which Monitoring rejects on a log-based policy; apply_policy's PATCH would fail and, under set -euo pipefail, the script would never reach the metric/threshold-policy code.
2. [blocker] alert_payloads.py:76-105 — threshold_policy()'s 60s alignmentPeriod on a DELTA/ALIGN_SUM counter reports a genuine 0 within about a minute of the last BTB_ALERT line, auto-resolving the incident long before a 24h renotify could fire.
3. [should-fix] tests/test_deploy_alerts_payloads.py missed both blockers — the log-match policy's payload lived inline in deploy-alerts.sh's heredoc, invisible to the offline test suite.
4. [should-fix] deploy-alerts.sh:156-167 — apply_policy's drift check used exact dict equality, so a live policy missing API-omitted default fields (thresholdValue 0, duration "0s") would always look "drifted" and get re-PATCHed on every clean re-run.
5. [should-fix] deploy-alerts.sh:277-278 — the metric-exists branch never compared the live metric's filter to METRIC_FILTER, so a filter edit here would silently never reach an already-created metric.
6. [should-fix] deploy-alerts.sh:281-296 — on a first run, Monitoring may briefly reject the threshold policy created right after the metric, since the metric may not have propagated yet.
7. [nit] deploy-alerts.sh:276-290 — the mktemp METRIC_DESCRIBE_ERR file was left behind if `metrics create` failed under set -e.
8. [nit] alert_payloads.py:31-34 — the filter also matches textPayload:"BTB_ALERT"; reviewer confirmed this is harmless and consistent with the old policy, no change needed.

Round-4 review of a99e68e..3901e38, from the overseer's review subagent:
9. [blocker] alert_payloads.py:161 + :180 — alignmentPeriod (86400s) equaled renotifyInterval (86400s). For a one-off BTB_ALERT line at time T, the 24h rolling sum clears at about T+24h; the incident opens at T+ingestion-lag, so the re-notify was due at T+lag+24h — after the condition had already cleared. The second email would likely never arrive for a one-off event; it only worked while new BTB_ALERT lines kept coming, defeating half the point of a renotify safety net.

### Fixed in
1. a99e68e — removed notificationChannelStrategy from the log-match policy's alertStrategy.
2. dd9b6b5 — alignmentPeriod 86400s + explicit EVALUATION_MISSING_DATA_NO_OP, doc text updated, red→green proven via a git-history temp-file import of the pre-fix module.
3. 79ff681 — extracted log_match_policy() into alert_payloads.py with a CLI subcommand and a regression-guard test (notificationChannelStrategy not in alertStrategy), proven red by reintroducing finding #1's bug in a scratch copy first.
4. 39b79ce — added same_policy() to alert_payloads.py, normalizing thresholdValue/duration before comparing; proven red against a naive dict-equality scratch copy first.
5. cd48053 — metric-exists branch now compares the live filter to METRIC_FILTER and runs `gcloud logging metrics update` on drift.
6. 96e8b73 — documented the expected first-run race and its idempotent fix (re-run the script) in the brief's Deploy implied section, per the reviewer's own offered alternative to retry logic.
7. d05ffad — `trap 'rm -f "$METRIC_DESCRIBE_ERR"' EXIT` replaces the manual rm -f calls.
8. not fixed — see report (reviewer confirmed no change needed).
9. 05a9415 — renotifyInterval dropped to 82800s (23h), one hour under alignmentPeriod's 86400s, so the re-notify always fires while the 24h sum is still >0; new test asserts the invariant `renotifyInterval < alignmentPeriod` directly rather than pinning today's exact values, proven red against the pre-fix 86400s/86400s code first.

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

Replace poll-dataform-failures' log-match BTB_ALERT alert policy with a log-based metric + threshold policy that re-notifies every 24h (Monitoring API rejects notificationChannelStrategy on log-based alerts), so jobs/deploy-alerts.sh runs clean from main; retire the old policy only after the new one is proven to fire

## Done when

`tests/test_deploy_alerts_payloads.py` goes red then green, proving the new
policy's JSON shape offline (no gcloud creds needed here — same "not run live
from this worktree" split commit 730057b already used):
- red: the file imports `jobs/alert_payloads.py`, which does not exist yet —
  collection fails.
- green: after `jobs/alert_payloads.py` is written and `jobs/deploy-alerts.sh`
  calls it, all cases pass:
  - `threshold_policy()`'s `conditionThreshold.filter` names `resource.type`
    explicitly (Monitoring rejects a metric filter without it).
  - its `alertStrategy` carries `notificationChannelStrategy` with
    `renotifyInterval: "86400s"` and does **not** carry
    `notificationRateLimit` (Monitoring rejects that field on a non-log-based
    policy — the mirror image of today's log-based error).
  - the CLI form (`python3 jobs/alert_payloads.py threshold-policy ...`, what
    `deploy-alerts.sh` actually calls) returns the same JSON as calling the
    function directly.
  - `metric_log_filter()` scopes to `job_name="poll-dataform-failures"` and
    the `BTB_ALERT` text.

`bash -n jobs/deploy-alerts.sh` stays clean (syntax only — the script's own
gcloud/curl calls are not run from this worktree; the overseer runs it live
from main per "Deploy implied" below, which is the real test of whether the
API accepts this shape).

Spec: unchanged because this repo has no `docs/specs/` directory yet (nothing
under `docs/specs/modules/` to update — confirmed by search, see Context).

## May touch

Module: `jobs/deploy-alerts.sh` (poll-dataform-failures' alert policy —
smallest thing deployed on its own; it is a plain script run by hand/CI, not
itself scheduled).

- `jobs/deploy-alerts.sh` — add the log metric and the new threshold policy;
  leave the existing log-match policy in place, untouched in behavior.
- `jobs/alert_payloads.py` (new) — the new policy's JSON payload, pulled out
  so it can be tested without gcloud. Mirrors
  `lesko-provisioning/scripts/dataform_lane_alert_payloads.py`'s split.
- `tests/test_deploy_alerts_payloads.py` (new) — the offline proof above.
- `docs/briefs/alert-renotify-metric.md` — this file.

Not touched: `jobs/poll_dataform_failures.py` (overseer's explicit instruction
— behavior unchanged, image sha256:c9e5faab stays the deployed one).

## Deploy implied

`jobs/deploy-alerts.sh`, run by the overseer from `main` after landing — same
as every earlier commit on this branch. This worktree does not run it.
Proof-of-fire is live-GCP work the overseer does after landing (see Context
and the report to come): one forced BTB_ALERT execution of the job, watching
for the metric-threshold policy's own email, before anyone retires the
older log-match policy.

Expected first-run hiccup: the script creates the counter metric and then,
in the same run, creates the threshold policy that reads it
(`gcloud logging metrics create` followed immediately by the policy
`POST`). Monitoring can reject a brand-new policy pointing at a metric it
hasn't propagated yet. No retry logic was added for this (round-3 review
should-fix #6, chose the reviewer's documented alternative over retry
logic) — `deploy-alerts.sh` is fully idempotent end to end (`find_policy` /
`apply_policy` / the metric-exists check above all re-check live state), so
if the first run fails here, re-running it is the fix: the metric already
exists on the second run, and only the policy create is retried.

Proof plan for the renotify itself (round-4 review blocker #9's fix —
renotifyInterval 82800s vs. alignmentPeriod 86400s): after the one forced
BTB_ALERT execution above, the incident should still be OPEN about 1h later
(the 24h rolling sum has not yet cleared), and a second email should arrive
within about 23h of the first (renotifyInterval). If the incident instead
auto-closes before the second email arrives, the safety margin was not
enough and needs widening.

## Context

Overseer's memory message (helpdesk-opzichter, 2026-09-24 09:20Z), verbatim
findings:
- Running `jobs/deploy-alerts.sh` from `main` (765d1de) PATCHes the live
  policy with `alertStrategy.notificationChannelStrategy` — API rejects it:
  `"Field alertStrategy.notificationChannelStrategy is not allowed:
  notificationChannelStrategy is not allowed for log-based alerts"`. Script
  exited 1. Live policy is unchanged:
  `projects/bigtribebuilders/alertPolicies/13511530526976011919`
  (`conditionMatchedLog`, `resource.labels.job_name="poll-dataform-failures"
  AND jsonPayload.message:"BTB_ALERT"`), `alertStrategy` still
  `{notificationRateLimit 1800s, autoClose 604800s}`. Channel
  `projects/bigtribebuilders/notificationChannels/4324299381952164741`
  ("Martin (email)").
- Both the counter metric and the threshold policy must be created
  idempotently by `deploy-alerts.sh`, which must exit 0 on a re-run. Email
  subject keeps starting "BTB-ALERT bigtribebuilders".
- Retire the log-match policy only after the metric one is proven to fire
  once; the overseer does that deploy and proposed the proof should be one
  forced BTB_ALERT execution plus watching for the email — this brief adopts
  that plan under "Deploy implied" above.
- Don't touch `jobs/poll_dataform_failures.py` behavior. Deployed today,
  image `sha256:c9e5faab`.

Known-good field shapes, cited per the overseer's ask:
- `lesko-questions-zone/deploy-alerts.sh` (lines ~150-238, this machine) —
  a log metric created with plain `gcloud logging metrics create
  --log-filter=...` (default DELTA/INT64 counter, no custom
  `metricDescriptor` needed for a bare count) feeding a `conditionThreshold`
  policy whose `alertStrategy.notificationChannelStrategy` carries
  `renotifyInterval: "86400s"` — live in project `lesko-486515` today per
  that file's own comments ("a 1800s autoClose paired with an 86400s
  renotify on the email channel").
- `lesko-provisioning/deploy-alerts.sh` (`rail_alert_by_code` policy,
  ~line 576) — same `conditionThreshold` shape, with the explicit comment
  that `resource.type` must be named in the filter even though the metric
  already scopes itself, and that `notificationRateLimit` must be **left
  out** of a threshold policy's `alertStrategy` ("Monitoring accepts one
  ONLY on log-based policies and rejects the whole request otherwise").
- Google Cloud REST docs (fetched 2026-09-24): `projects.metrics`
  (`LogMetric`) — an unspecified `metricDescriptor` defaults to
  `DELTA`/`INT64`, no labels, unit `"1"`, i.e. exactly a bare counter, no
  custom descriptor needed here. `AlertPolicy.AlertStrategy` docs confirm
  `notificationRateLimit` is documented as a log-based-policy field and
  `notificationChannelStrategy` as a general `AlertStrategy` field — general
  enough to explain the asymmetry the overseer hit live, though the "not
  allowed for log-based alerts" wording itself only surfaced in the live
  error text, not in the reference docs.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done: round-3 review (8 findings) and round-4 review (1 finding) both fixed,
one commit per finding, on top (no history rewrite):
- blocker #1 (stray notificationChannelStrategy on the log-match policy):
  a99e68e.
- blocker #2 (60s alignmentPeriod + default evaluationMissingData let the
  incident auto-resolve before the 24h renotify could fire; fixed with
  alignmentPeriod 86400s + explicit EVALUATION_MISSING_DATA_NO_OP): dd9b6b5.
- should-fix #3 (extracted log_match_policy() into alert_payloads.py + CLI
  subcommand + regression-guard test): 79ff681.
- should-fix #4 (same_policy() normalizes API-omitted defaults
  thresholdValue/duration before apply_policy's drift check): 39b79ce.
- should-fix #5 (metric-exists branch now compares live filter to
  $METRIC_FILTER and updates on drift): cd48053.
- should-fix #6 (documented the first-run metric-propagation race in the
  brief's Deploy implied section instead of adding retry logic): 96e8b73.
- nit #7 (trap 'rm -f "$METRIC_DESCRIBE_ERR"' EXIT replaces manual rm -f
  calls): d05ffad.
- nit #8: no code change needed (reviewer confirmed harmless).
- blocker #9 (alignmentPeriod == renotifyInterval, both 86400s, meant a
  one-off alert's re-notify was due right as the 24h sum cleared, so the
  second email likely never fired; fixed with renotifyInterval 82800s,
  one hour under alignmentPeriod): 05a9415.
Every python-touching fix proven red→green per repo convention (git-history
or scratch-copy temp import to show red, then
/opt/anaconda3/bin/pytest tests/test_deploy_alerts_payloads.py -q green —
currently 13 passed). bash -n jobs/deploy-alerts.sh clean after every
deploy-alerts.sh edit.
In flight / next:
- This State commit plus the brief's Agentic review round-4 entry and
  Deploy implied proof-plan update are being committed now, alongside
  05a9415 (the blocker #9 code+test fix).
- git add -N ., confirm git status --short clean, merge origin/main if it
  moved, wt-done.sh --check alert-renotify-metric until it exits 0.
- Report back to helpdesk-opzichter [a6904a] via SendMessage: commit 05a9415
  (blocker #9 fix) plus this brief-update commit, proof method (scratch-copy
  red→green), and the updated Deploy implied proof plan (incident stays
  OPEN ~1h after the forced alert; second email arrives within ~23h). Then
  stop and wait for the next verdict.
Traps (with dates):
- 2026-09-24: GCP docs confirm EVALUATION_MISSING_DATA_UNSPECIFIED (unset)
  already equals NO_OP — the real bug in blocker #2 is not missing-data
  handling, it's that a DELTA/ALIGN_SUM counter reports a genuine 0 (not
  "missing") once BTB_ALERT lines stop, which NO_OP does nothing about.
  The fix is alignmentPeriod, not evaluationMissingData (though setting the
  latter explicitly is harmless belt-and-suspenders).
- 2026-09-24: don't run the full pytest suite from this worktree — review
  flagged that some test can reach the live Dataform repo via
  bq_writes.trigger_assignment_refresh(). Run only
  tests/test_deploy_alerts_payloads.py.
- 2026-09-24: `conditionMatchedLog` (log-match) policies reject
  `alertStrategy.notificationChannelStrategy` outright — confirmed live
  against bigtribebuilders. Don't try to add a 24h renotify to a log-match
  policy again; use a metric + `conditionThreshold` policy instead.
- 2026-09-24: a `conditionThreshold` policy's own filter must name
  `resource.type` explicitly even when the metric it reads already scopes to
  one resource type, or Monitoring rejects the create/patch at apply time
  (lesko-provisioning hit this first, see brief Context).
- 2026-09-24: a `conditionThreshold` policy's `alertStrategy` must NOT carry
  `notificationRateLimit` — Monitoring accepts that field only on log-based
  policies and rejects the whole request otherwise (mirror-image trap of the
  one above).
- 2026-09-24: this worktree's default `python3` (3.14, /opt/homebrew) has no
  pytest; `/opt/anaconda3/bin/pytest` does. Use that interpreter (or
  `/opt/anaconda3/bin/python3 -m pytest`) to run this repo's tests here.
