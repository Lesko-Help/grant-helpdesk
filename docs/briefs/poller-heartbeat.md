# Brief: poller-heartbeat

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

No `docs/specs/` in this repo; the changes below are measured against `docs/gates/*.md` and what runs live on 2026-09-24.

## Product — gate 1

### Problem
If the hourly Dataform-failure poller stops running, nothing tells Martin. The failure alerts it drives just go quiet, and quiet looks like "all fine".

### User
Martin, who reads the BTB-ALERT mails. He depends on poll-dataform-failures to catch grant_ticket_labels failures.

### Success metric
Minutes from "poller stops succeeding" to the BTB-ALERT mail arriving. Target: 95 min or less, measured once in the overseer's fire drill. Second number: false silence incidents on this policy in its first 7 days, target 0. Both come from Monitoring's incident list for the policy.

### Mock-up
No screen. What Martin gets is an email:
```
Subject: BTB-ALERT bigtribebuilders — poll-dataform-failures went silent (no successful run in 90 min)
Body:    what it means · last run: gcloud run jobs executions list ... · usual causes · how to resume
```
Known limit, on purpose: this alert watches "a run finished with exit 0". It does NOT catch a poller that runs fine but sees too little. Until worktree poller-paging lands, the job exits 0 after reading only page 1 of Dataform invocations. That is poller-paging's job, not this one's.

## Architecture — gate 2

### Services
- Cloud Scheduler `poll-dataform-failures-hourly` (europe-west1, `0 * * * *` Europe/Brussels) starts the job. No change.
- Cloud Run job `poll-dataform-failures`: 1 task, maxRetries 0, timeout 120s. Runs finish about 1 min after :00. No change.
- Cloud Monitoring built-in metric `run.googleapis.com/job/completed_execution_count` (DELTA/INT64, sampled every 60s, ingest delay 120s). Google writes it; we create nothing.
- Cloud Monitoring alert policy (new): a metric-absence condition on that metric.
- Notification channel "Martin (email)": looked up by name, as today.

### Endpoints
No new endpoints. `deploy-alerts.sh` already calls all of these:
- `GET  /v3/projects/bigtribebuilders/notificationChannels` finds the channel by name.
- `GET  /v3/projects/bigtribebuilders/alertPolicies?filter=display_name="…"` is find_policy.
- `POST /v3/projects/bigtribebuilders/alertPolicies` creates the policy.
- `PATCH /v3/{policy}?updateMask=conditions,alertStrategy,documentation` fixes drift.

### Data models
```
AlertPolicy (new, one row) {
  displayName = documentation.subject = "BTB-ALERT bigtribebuilders — poll-dataform-failures went silent (no successful run in 90 min)"
  conditions[0].conditionAbsent {
    filter      = resource.type="cloud_run_job" AND metric.type="run.googleapis.com/job/completed_execution_count"
                  AND resource.labels.job_name="poll-dataform-failures" AND metric.labels.result="succeeded"
    duration    = "5400s"   -- 60 min schedule + 30 min margin
    aggregations= [{alignmentPeriod "300s", ALIGN_SUM, REDUCE_SUM}]
  }
  alertStrategy { autoClose "604800s", notificationChannelStrategy [{channel, renotifyInterval "86400s"}] }
}
```
Metric and label names were checked three ways. Google's metric list (cloud.google.com/monitoring/api/metrics_gcp_p_z, section "run", job/completed_execution_count, label `result`). The live descriptor in bigtribebuilders, read-only. The live time series on 2026-09-24: `metric.labels.result="succeeded"` with resource labels `job_name="poll-dataform-failures"`, `location`, `project_id`, with points at 14:02 and 15:02–15:03 UTC. Known-good use of the same pattern in this project: the live policy "any Cloud Run job execution failed" filters on this metric with `result="failed"`. The live conditionAbsent policy "cerbo-logger went silent" already accepts a notificationChannelStrategy and a 24h renotify.

Margin: the job runs hourly and each run finishes about 3 min after :00, counting ingest delay. 5400s (1.5 schedules) means one missed or failed run pages about 33 min after that run was due. The 30 min margin covers the 2 min job timeout, the 3 min scheduler deadline, and ingest lag. The metric counts executions that actually ran to completion. Scheduler attempts that never started a run count as silence. Rule 4 asks for exactly that.

Rejected alternative, log-based: a counter metric on a "success" log line, then an absence policy on it. That needs either a heartbeat line in `poll_dataform_failures.py`, which this task may not touch, or a filter on Cloud Run's system log text. It also adds a second live object (a log metric) with its own describe/create/update drift dance, and a 1–2 min log-to-metric lag. The built-in metric needs no code change and no new object, and it counts real successful executions.

### Sequence
1. Scheduler hits `…/jobs/poll-dataform-failures:run` every hour.
2. The job runs and exits 0. Cloud Run emits completed_execution_count{result=succeeded} += 1.
3. Monitoring checks the absence condition. If there is no such point for 5400s, it opens an incident and emails "Martin (email)".
4. While the incident is open: a repeat email every 24h. The next successful run closes it. autoClose after 7 days is a backstop.
5. Separately: `deploy-alerts.sh` → `alert_payloads.py absence-policy …` → find_policy → create, or PATCH on drift.

## Design — gate 3

### Files
- M `jobs/alert_payloads.py`: new `absence_policy()`, new CLI kind `absence-policy`, a `SILENCE_WINDOW_SECONDS = 5400` constant with its derivation in a comment, and a usage line.
- M `jobs/deploy-alerts.sh`: one new section at the end, "the silence policy": TITLE_SILENCE, PAYLOAD_SILENCE, then apply_policy. Update the header comment.
- M `tests/test_deploy_alerts_payloads.py`: new tests below. Import `absence_policy`.
- M `docs/briefs/poller-heartbeat.md`: the brief.
- MAY NOT TOUCH: `jobs/poll_dataform_failures.py`. Worktree poller-paging is editing it, and two worktrees never edit the same file. Also no Dataform configs, no `deploy.sh`.

### Types & signatures
- `absence_policy(title: str, job: str, project: str, channel: str, window_seconds: int = SILENCE_WINDOW_SECONDS) -> dict`: builds the AlertPolicy above.
- `_main(argv)`: gains `absence-policy TITLE JOB PROJECT CHANNEL`, which prints the JSON.
- `same_policy(existing, want) -> bool`: unchanged. Its defaults fill only conditionThreshold, and conditionAbsent is compared as-is.

### Call stack
```
deploy-alerts.sh
  CHANNEL = lookup "Martin (email)"                     (existing)
  apply_policy log-match …; metric …; threshold …       (existing, unchanged)
  TITLE_SILENCE = "BTB-ALERT ${PROJECT} — ${JOB} went silent (no successful run in 90 min)"
  PAYLOAD_SILENCE = python3 alert_payloads.py absence-policy "$TITLE_SILENCE" "$JOB" "$PROJECT" "$CHANNEL"
  apply_policy "$TITLE_SILENCE" "$PAYLOAD_SILENCE"
    find_policy → none: POST, exit 1 on {"error"} | same_policy True: leave | else PATCH, exit 1 on {"error"}
```

### Test plan
All payload-shape only. No gcloud, no network, no live Dataform, BigQuery or Monitoring.
- `test_absence_policy_watches_succeeded_runs_of_the_job`: the filter contains `resource.type="cloud_run_job"`, the metric type, `job_name="poll-dataform-failures"`, and `metric.labels.result="succeeded"`.
- `test_absence_policy_window_is_schedule_plus_margin`: `duration == "5400s"`, and 3600 < duration < 7200, so one missed hourly run fires the alert. The expected values are written in the test, not read from the builder.
- `test_absence_policy_is_condition_absent_not_threshold`: the condition has `conditionAbsent` and no `conditionThreshold`/`conditionMatchedLog`.
- `test_absence_policy_has_no_evaluation_missing_data`: the field is absent. That field is for threshold conditions, and this is the 0s trap from 2026-09-24.
- `test_absence_policy_renotifies_every_24h_and_has_no_rate_limit`: renotifyInterval "86400s", notificationChannels == [CHANNEL], and no notificationRateLimit.
- `test_absence_policy_subject_keeps_btb_alert_prefix`: the subject and displayName start "BTB-ALERT bigtribebuilders".
- `test_absence_policy_documentation_is_a_runbook` (slice 3): the content names `gcloud run jobs executions list`, the scheduler job name, and the "does not catch a blind poller" limit.
- `test_cli_absence_policy_matches_direct_call`: runs the subprocess CLI, parses its JSON, and checks it equals the direct call.
- `test_same_policy_absence_round_trip`: an existing policy with a condition `name` added compares True. With a changed duration it compares False.

### Least confident decisions
- 5400s fires on one missed run. That catches silence fast but could be noisy if Scheduler blips. 9000s would wait for two misses. See the open question.
- Whether Monitoring echoes a conditionAbsent back unchanged on GET, for example by adding `trigger`. If not, same_policy sees drift on every run and re-PATCHes. That is harmless but not "exists and matches". Only the overseer's second live run shows this.
- Absence conditions stop tracking a series after about 24h with no data. The incident should stay open, with the 24h renotify, until data returns. That is not proven here.
- The alignment of 300s ALIGN_SUM + REDUCE_SUM is copied from cerbo-logger's live absence policy, not derived afresh.

## Slices — gate 4

### Slice order
1. **Payload builder, red then green.** Write the tests above, except the runbook test. Run them: red, because the import fails. Add `absence_policy()` + CLI kind: green. Then flip `"succeeded"`→`"failed"` in the builder once: the filter test goes red. Revert: green. Proof: `python3 -m pytest tests/test_deploy_alerts_payloads.py -q`, with the red and green output pasted into the brief.

   **Proof, run 2026-09-24 via `/opt/anaconda3/bin/pytest tests/test_deploy_alerts_payloads.py -q`** (this checkout's system `python3 -m pytest` has no pytest module installed):
   - Red (before `absence_policy()` existed):
     ```
     ImportError: cannot import name 'absence_policy' from 'alert_payloads'
     1 error in 0.07s
     ```
   - Green (after implementing `absence_policy()` + the `absence-policy` CLI kind):
     ```
     ......................                                                   [100%]
     22 passed in 0.20s
     ```
   - Red again (`"succeeded"` flipped to `"failed"` in the filter, once):
     ```
     ..............F.......                                                   [100%]
     FAILED tests/test_deploy_alerts_payloads.py::test_absence_policy_watches_succeeded_runs_of_the_job
     1 failed, 21 passed in 0.12s
     ```
   - Green again (reverted):
     ```
     ......................                                                   [100%]
     22 passed in 0.15s
     ```
2. **Wire into deploy-alerts.sh.** Add the silence section at the end through `apply_policy`, keep `set -euo pipefail`, and don't touch the earlier sections. Proof: `bash -n jobs/deploy-alerts.sh`. Then an offline stubbed run: fake `curl`/`gcloud` on PATH in the scratchpad (not committed) returning a channel, "no policy", and then `{"error":…}` on the silence POST. The script must exit 1 at that step. Re-run with the stubs returning a matching policy: it prints "exists and matches" and exits 0.
3. **Runbook + fire-drill note.** `documentation.content` covers what went silent, the last run (`gcloud run jobs executions list --job poll-dataform-failures --region europe-west1 --project bigtribebuilders --limit 5`), usual causes (scheduler paused or failing, job failing (see the "execution failed" alert), image broken), the blind-poller limit, and how to resume. Add the runbook test. Proof: pytest green. The brief's "Deploy implied" holds the overseer's steps: after landing, from main, run `jobs/deploy-alerts.sh` twice. The 2nd run must say "exists and matches" for every policy. Then, with Martin's per-action OK: `gcloud scheduler jobs pause poll-dataform-failures-hourly …`, wait until the BTB-ALERT mail arrives (about 95 min after the last success) and record the minutes, then `resume`, and confirm the incident closes after the next run. No `deploy.sh`: the job's image does not change.

STOP: after every slice, message the overseer (SendMessage — find it with
ListAgents if the name needs a [ref]): "slice K done - continue or
re-steer?" plus a one-line summary of the slice and its proof line. Wait
for its reply before starting slice K+1 — it writes a slice file, asks
Martin in its own pane, and relays his answer back to you. Record that
reply here before continuing. Never ask Martin directly in this window.

**Slice 1 reply (2026-09-24, relayed by helpdesk-opzichter):** Martin's
answer was "Continue to slice 2" — go ahead and wire the silence policy
into `jobs/deploy-alerts.sh`, as the slice order says.

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

Add a silence alert that fires when the Cloud Run job poll-dataform-failures has had no successful run within its schedule plus a margin (5400s)

## Done when

`tests/test_deploy_alerts_payloads.py` goes red then green for the new
`absence_policy()` tests listed under Design's Test plan above (run with
`/opt/anaconda3/bin/pytest tests/test_deploy_alerts_payloads.py -q` — this
repo's system `python3 -m pytest` has no pytest installed; only this file,
no gcloud/network/live Monitoring). Slice 1's proof is the red-then-green
transcript pasted into this brief. Slice 2's proof is `bash -n
jobs/deploy-alerts.sh` plus the offline stubbed-curl run described in the
Slices section. Slice 3's proof is the runbook test passing.

Spec: unchanged because this repo has no `docs/specs/` (see the note at the
top of this brief) — there is no module spec file to update.

## May touch

Module: `jobs` (the alerts deploy script and its payload builder — the
smallest thing deployed on its own, via `jobs/deploy-alerts.sh`; same module
named in the sibling briefs alert-threshold-fix and alert-renotify-metric).

- `jobs/alert_payloads.py` — add `absence_policy()` and the `absence-policy`
  CLI kind.
- `jobs/deploy-alerts.sh` — add the silence-policy section at the end.
- `tests/test_deploy_alerts_payloads.py` — new tests for `absence_policy()`.
- `docs/briefs/poller-heartbeat.md` — this brief.
- MAY NOT TOUCH: `jobs/poll_dataform_failures.py` (worktree poller-paging
  owns it), no Dataform configs, no `deploy.sh`.

## Deploy implied

`jobs/deploy-alerts.sh` (PROJECT=bigtribebuilders, JOB=poll-dataform-failures).
Not run from this worktree — the overseer re-runs it live from `main` after
landing, per the Slices section's step 3: run it twice (2nd run must say
"exists and matches" for every policy), then, with Martin's per-action OK,
pause `poll-dataform-failures-hourly`, wait for the BTB-ALERT mail, record
the minutes, resume, and confirm the incident closes.

## Context

Overseer memory relayed by message on 2026-09-24, right after `wt-new.sh`
(no earlier arrival to note — it was here before the first commit):

1. DECISION BY MARTIN (2026-09-24): the gate plan is approved as drafted,
   with a 5400s duration, so one missed hourly run pages him.
2. TRAP (2026-09-24): a conditionThreshold with evaluationMissingData set is
   REJECTED when duration is "0s". This absence condition uses 5400s, so it
   does not bite here, but don't copy that field blindly from
   `threshold_policy()`. Offline payload tests cannot catch this kind of
   API-side check — only the overseer's live run after landing can.
3. TRAP (2026-09-14): the Monitoring API leaves `thresholdValue: 0` out of
   the policies it returns, so a naive compare sees drift on every run. The
   same class of drift may hit an absence condition — keep the reconcile
   compare tolerant of fields the API drops.
4. TRAP (2026-09-14): a CREATE that returns an error can still have created
   the policy — re-read before any retry, or you get duplicates. The email
   subject comes from `documentation.subject` and must start
   "BTB-ALERT bigtribebuilders".
5. TRAP (2026-09-23): the reference kit's create paths leave out the 24h
   re-notify. Put `renotifyInterval` (plus `notificationChannelNames`) into
   the CREATE payload itself, not only into the repair path.
6. TRAP (2026-09-14): a fire drill with `gcloud logging write` lands on the
   global resource type. For this task, the live drill is the overseer's
   job after landing, with Martin's OK — pausing the Scheduler trigger for
   over 90 min and confirming the email. The worker (here) proves the
   payload offline, red then green, only.
7. Precedent (2026-09-17, lesko-questions-zone): an absence policy there
   worked live, created only once the success metric had a time series.
   Nobody has drill-proven any absence policy in any repo yet.
8. Scope: never touch `jobs/poll_dataform_failures.py` (poller-paging owns
   it). Tests must never call live Monitoring, Dataform or BigQuery.

Related sibling briefs in this repo, same `jobs` module:
`docs/briefs/alert-threshold-fix.md`, `docs/briefs/alert-renotify-metric.md`,
`docs/briefs/dedupe-ticket-tables.md` (original BTB_ALERT policy).

Live metric checked 2026-09-24 (Architecture section above has the full
citation trail): `run.googleapis.com/job/completed_execution_count`
(DELTA/INT64), `metric.labels.result="succeeded"`,
`resource.labels.job_name="poll-dataform-failures"`.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done: brief filled in (commit 20d0278, first on branch). Slice 1 done and
committed (43f5d4e): absence_policy() added to jobs/alert_payloads.py:249
(SILENCE_WINDOW_SECONDS=5400 at jobs/alert_payloads.py:222), plus the
absence-policy CLI kind, plus 8 tests appended to
tests/test_deploy_alerts_payloads.py (all pass via
`/opt/anaconda3/bin/pytest tests/test_deploy_alerts_payloads.py -q` — 22
passed; red-then-green-then-red-then-green transcript is pasted into this
brief's Slices section under slice 1). Reported to overseer, Martin said
"Continue to slice 2" (relayed 2026-09-24, recorded in Slices section,
commit 432453f).
In flight: slice 2 — wiring absence_policy() into jobs/deploy-alerts.sh.
Was about to add a new section at the end (TITLE_SILENCE, PAYLOAD_SILENCE,
apply_policy "$TITLE_SILENCE" "$PAYLOAD_SILENCE") right before the closing
"Policies now watching..." listing loop at the very end of the file — no
code written yet for this slice.
Next: write that section in jobs/deploy-alerts.sh, run `bash -n
jobs/deploy-alerts.sh`, then prove it offline with fake curl/gcloud on
PATH in the scratchpad (not committed): one run where the silence POST
returns {"error":...} and the script must exit 1; a second run where it
returns a matching policy and the script prints "exists and matches" and
exits 0. Paste both transcripts into the brief's slice 2 line, commit,
report to overseer, wait for reply — then slice 3 (runbook content + its
test).
Traps (with dates): see Context section above, items 1-8 (all 2026-09-14
to 2026-09-24, from the overseer's memory relay) — notably #3/#4 (API
omits zero-value fields on read; re-read after a CREATE error before
retrying) apply to apply_policy()'s existing find_policy/same_policy
logic, which slice 2 reuses unchanged, not to new code.
This checkout's system `python3 -m pytest` has no pytest installed — use
`/opt/anaconda3/bin/pytest` for every test run in this worktree.
