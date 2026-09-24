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

Done: brief filled in and committed (fc1f911). Wrote
tests/test_deploy_alerts_payloads.py (7 cases) against jobs/alert_payloads.py,
which does not exist yet — confirmed red: `ModuleNotFoundError` on collection.
In flight (file:line): tests/test_deploy_alerts_payloads.py:22 imports
`alert_payloads` — next step is writing that module to turn this green.
Next: write jobs/alert_payloads.py; run tests green (use
`/opt/anaconda3/bin/pytest` — the default `python3` has no pytest installed,
see trap below); wire jobs/deploy-alerts.sh to call it for the new metric +
threshold policy; `bash -n jobs/deploy-alerts.sh`; commit; merge origin/main;
wt-done.sh --check; report to helpdesk-opzichter.
Traps (with dates):
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
