# alert_payloads
Status: agreed 2026-10-16
Kind: helper
Summary: the Dataform silence alert — a counter metric over the pipeline's own completion log line, and the absence policy that pages when that line stops arriving for an hour
Part of: `docs/specs/INDEX.md` · Deploy: `jobs/deploy-alerts.sh`, run by hand (this file ships in no image) · Updated: 2026-10-16
Used by: `jobs/deploy-alerts.sh` (through the CLI form in `_main`, never by import) and `tests/test_deploy_alerts_payloads.py` (by import)
Reads: nothing — no network, no credentials, no file
Writes: one JSON object on stdout, which `deploy-alerts.sh` captures and POSTs to the Cloud Monitoring API

## Overview

*What it is for:* give `deploy-alerts.sh` the exact JSON for an alert that pages
when the helpdesk's Dataform pipeline stops running at all, so silence cannot
read as "all fine" (global rule 4).
*What it owns:* the Cloud Logging filter that counts a successful Dataform run,
and the `conditionAbsent` policy built on it.
*What it depends on:* `json` and `sys` only — no gcloud, no network, so the
payload is testable offline.
*Public entry points:* `dataform_silence_policy` and `DATAFORM_COMPLETION_LOG_FILTER`
(this spec); uncovered: `metric_log_filter`, `log_match_policy`,
`threshold_policy`, `service_metric_log_filter`, `service_log_match_policy`,
`service_threshold_policy`, `absence_policy`, `same_policy`.
*Not in scope:* creating the metric or policy (`deploy-alerts.sh`), which action
failed (`jobs/poll_dataform_failures.py`), and those eight live rails.

## The signal

Dataform writes one completion log entry per workflow invocation, so a run that
finishes leaves a line and a run that never starts leaves nothing at all. The
heartbeat is that SUCCEEDED completion line, counted by a log-based counter
metric; the alarm is the count going absent.

```
logName="projects/bigtribebuilders/logs/dataform.googleapis.com%2Fworkflow_invocation_completion"
AND resource.type="dataform.googleapis.com/Repository"
AND resource.labels.repository_id="grant-helpdesk"
AND jsonPayload.workflowConfigId="grant-helpdesk-5min"
AND jsonPayload.terminalState="SUCCEEDED"
```

The payload, with `<title>`, `<metric>` and `<channel>` for its arguments:

```json
{
  "displayName": "<title>",
  "documentation": {
    "subject": "<title>",
    "content": "<runbook — see R8>",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "no successful grant-helpdesk-5min run in the window",
    "conditionAbsent": {
      "filter": "metric.type=\"logging.googleapis.com/user/<metric>\" AND resource.type=\"dataform.googleapis.com/Repository\"",
      "duration": "3600s",
      "aggregations": [{
        "alignmentPeriod": "300s",
        "perSeriesAligner": "ALIGN_SUM",
        "crossSeriesReducer": "REDUCE_SUM"
      }]
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "alertStrategy": {
    "autoClose": "604800s",
    "notificationChannelStrategy": [{
      "notificationChannelNames": ["<channel>"],
      "renotifyInterval": "86400s"
    }]
  },
  "notificationChannels": ["<channel>"]
}
```

## Functions

### dataform_silence_policy(title, project, channel, metric_name, window_seconds=DATAFORM_SILENCE_WINDOW_SECONDS)

*Signature, as it is in code.*

*What it does:*
- R1: returns one AlertPolicy dict, shaped exactly as the block above, ready for
  `json.dumps`. It takes no repository or workflow-config argument: both are
  pinned in `DATAFORM_COMPLETION_LOG_FILTER`, so metric and policy cannot differ.
- R2: the filter pins `jsonPayload.workflowConfigId="grant-helpdesk-5min"`, not
  only `resource.labels.repository_id`. The name is a misnomer left from when the
  config ran `*/5`; it runs every 30 minutes now. Cloud Logging matches the
  literal string, so renaming the config changes this constant in that commit.
- R3: the filter also pins `jsonPayload.terminalState="SUCCEEDED"`. A run that
  starts and fails is not a heartbeat; it is `poll_dataform_failures.py`'s
  business, and a pipeline failing every tick trips both rails.
- R4: the condition is a `conditionAbsent` over
  `metric.type="logging.googleapis.com/user/<metric_name>" AND
  resource.type="dataform.googleapis.com/Repository"` (the resource type is how
  Monitoring knows which series it waits on), with `duration: window_seconds` and
  one aggregation — `alignmentPeriod: "300s"`, `ALIGN_SUM`, `REDUCE_SUM`: the
  shape of `absence_policy` next door and of the sibling Dataform silence
  policies live in this project. No `conditionThreshold`, and no
  `evaluationMissingData`, which belongs to threshold conditions only.
- R5: `window_seconds` defaults to `DATAFORM_SILENCE_WINDOW_SECONDS = 3600`, its
  own constant, written into the condition's `duration` — not the existing
  `SILENCE_WINDOW_SECONDS = 5400`, which is `absence_policy`'s hourly job.
- R6: `alertStrategy` carries `autoClose: "604800s"` and a
  `notificationChannelStrategy` with `renotifyInterval: "86400s"`, a full 24h. No
  `notificationRateLimit`: Monitoring accepts it only on log-match policies and
  rejects the whole create or patch otherwise.
- R7: `documentation.subject` is the `title` unchanged, and so is `displayName`.
  `deploy-alerts.sh` passes a title beginning `BTB-ALERT bigtribebuilders`; Cloud
  Alerting prefixes its own `[ALERT - <severity>] ` in the email.
- R8: `documentation.content` is a runbook, not a restatement of the condition —
  the call that lists recent workflow invocations, the three usual causes (config
  disabled, release config not compiling, every run FAILED), and the note that
  the incident closes on the next successful run. `gcloud dataform` does not
  exist in this SDK, so those commands drive `dataform.googleapis.com/v1beta1`
  with `gcloud auth print-access-token`.
- R9: `channel` is a notification channel's full resource name, as every other
  builder here takes it; `deploy-alerts.sh` looks up `Martin (email)`, the
  verified channel the other policies use, and exits 1 without it.
- R10: `deploy-alerts.sh` creates the log metric before the policy that names it,
  both idempotent — the metric through the script's describe-then-update-or-create
  block (match, leave; drift, update; NOT_FOUND, create; any other error, stop
  with nothing changed), the policy through `find_policy` / `apply_policy`, which
  compares via `same_policy` and patches in place, keeping the policy id and any
  open incident.

*Examples:* ticks at `:05` and `:35` -> a point every 30 minutes -> no incident.
Last success 14:35, nothing after -> absent from 15:35 -> incident, subject
`[ALERT - Critical] BTB-ALERT bigtribebuilders — ...`. One tick missed, 15:35
runs -> a 60-minute gap, not over it -> no page.

*Inputs:* the policy title, the GCP project, a channel resource name, the log
metric's name, and optionally a window in seconds.

*Outputs:* a dict of JSON-safe values; nothing is printed or sent from here.
`_main`'s `dataform-silence-policy` verb prints it, `dataform-metric-filter`
prints `DATAFORM_COMPLETION_LOG_FILTER`.

*Errors:* it cannot fail on a value — every argument is interpolated into a
string. Wrong arity -> `_main` writes `bad arguments for kind
'dataform-silence-policy'` to stderr and returns 1; any other failure -> a
traceback and a non-zero exit. Either way `set -euo pipefail` stops
`deploy-alerts.sh` at the command substitution, before `apply_policy` sends
anything. No `BTB_ALERT` code: this script is run by hand, watched by a person.

*Test:* `/opt/anaconda3/bin/python -m pytest tests/test_deploy_alerts_payloads.py`
from the repo root. Fixture: the builder called with the fake channel already in
that file and the title regexed out of `jobs/deploy-alerts.sh` (as
`test_absence_policy_subject_keeps_btb_alert_prefix` does, so the test cannot
check its own input), plus one `subprocess` round-trip through the CLI verb.
Observed on the returned dict: the workflow-config and terminal-state pins
(R2, R3); `conditionAbsent`, `duration == "3600s"`, the 300s
`ALIGN_SUM`/`REDUCE_SUM` aggregation, `metric.type` and `resource.type` both
in the condition filter, and `conditionThreshold`, `conditionMatchedLog` and
`evaluationMissingData` all absent (R4); `"3600s"` typed in the test rather than
read back, and `!= "5400s"` (R5); no `notificationRateLimit`,
`renotifyInterval == "86400s"` (R6); `subject == displayName == title`, starting
`BTB-ALERT bigtribebuilders` (R7); the three runbook causes and the v1beta1 URL
(R8); `notificationChannels == [channel]` (R9); and, from the script's source,
the metric block before the `apply_policy` call naming it, plus `same_policy`
True for a round-trip with a condition `name` added (R10). Red first against
`origin/main`: `dataform_silence_policy` does not exist there, so the import
fails and every case is red. Never `pytest tests/` — it runs `smoke_test.py`,
which writes to the live `ticket_metadata`.

## Decisions

- 2026-10-16: this spec covers the Dataform silence builder only, not the eight
  other builders in `jobs/alert_payloads.py`. Why: the style guide caps a spec at
  about 150 lines of prose and says a longer one means a split — the file is 545
  lines across four live rails, and the rest is owed its own spec.
- 2026-10-16: the alert watches the Dataform completion log, not
  `poll_dataform_failures.py`. Why: that poller pages on an invocation in state
  FAILED, and a pipeline paused, disabled or failing to compile produces no
  invocation to be in any state, so every alert this repo has today stays quiet
  — global rule 4 unmet for the one pipeline the whole app reads from.
- 2026-10-16: the filter pins `workflowConfigId="grant-helpdesk-5min"` (R2). Why:
  the repository also holds `grant-helpdesk-weekly-prompt`, on `0 6 * * 1`, and a
  repository-wide filter would let that Monday run reset the silence clock,
  hiding up to a week of a dead 30-minute pipeline. House pattern too:
  `btbr_core_30min_succeeded` pins `workflowConfigId="core-30min"` beside
  `repository_id="BTBR"`; `kit_dataform_workflow_succeeded` pins only the
  repository, the weaker form, not copied.
- 2026-10-16: `conditionAbsent`, not a threshold on sum < 1 (R4). Why: a
  log-based counter metric is sparse — measured, not assumed: the timeSeries API
  returned 12 points for `logging.googleapis.com/user/btbr_core_30min_succeeded`
  over 6 hours at 600s alignment, one per run, where a zero-filled series would
  give 36. The series genuinely goes absent when runs stop, three sibling
  Dataform policies here rely on that, and it matches `absence_policy`.
- 2026-10-16: the honest caveat — `conditionAbsent` fires only for a series
  Monitoring has already seen. That holds here (the pipeline has run every 30
  minutes since 2026-10-06); copied to a repo whose pipeline never ran, it
  cannot fire until the first successful run.
- 2026-10-16: the window is 3600s in its own constant, not the existing 5400s
  (R5). Why: at a 30-minute cadence an hour is two missed ticks, so one transient
  miss wakes nobody and a stopped pipeline pages within the hour; it matches the
  closest live analogue, `elin-crm-all` (3600s/300s). 5400s is sized for an
  hourly Cloud Run job, and sharing it would tie two schedules together.
- 2026-10-16: `renotifyInterval` is 86400s, `absence_policy`'s value (R6). Why: a
  `conditionAbsent` has no rolling-sum window that can clear and auto-resolve the
  incident first, so global rule 3's full 24h fits exactly; the threshold
  policies' shorter value answers a window this condition does not have.
- 2026-10-16: the heartbeat counts SUCCEEDED completions only (R3). Why: global
  rule 4 counts runs that started and finished, not scheduled attempts, and
  accepting a FAILED run here would quietly downgrade a failure to healthy.
- 2026-10-16: Martin waived the break-it-on-purpose fire drill — he approved the
  gates and said "skip the drill". It lands on the policy created and enabled
  plus the unit tests over the payload, the pause-and-wait drill left to him: a
  deliberate exception to global rule 5, not a claim the alert was proven to
  fire. Pausing `grant-helpdesk-5min` has a known trap too — the PATCH fails
  unless the body also carries `releaseConfig`.
