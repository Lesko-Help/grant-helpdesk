# Brief: coach-inbox-alert

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

# GATE — grant-helpdesk: coach inbox for members' private questions
# for: helpdesk-opzichter · approved by Martin 2026-09-25 · drafted 2026-09-25 from `20260924-HANDOFF-questions-zone-coach-inbox.md` + Martin's decisions of 2026-09-25

Design and function rules: `docs/specs/modules/coach_inbox.md` (in grant-helpdesk, on `main`). A worker reads that file before its first slice.

## Product — gate 1

### Problem
A member who asks a coach a private question on their page gets no answer, because no coach can see it; so the zone stays switched off.

### User
Lesko Help coaches (and the admin), working in the grant-helpdesk Tickets tab.

### Success metric
Hours from a member's message to the next coach message in `private_messages` (median per week, and count of threads still waiting after 48h):
`SELECT COUNT(*) FROM (SELECT thread_id, ARRAY_AGG(author_role ORDER BY created_at DESC LIMIT 1)[OFFSET(0)] AS last_role, MAX(created_at) AS last_at FROM lesko-486515.private_chat.private_messages GROUP BY thread_id) WHERE last_role='member' AND last_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)` — target 0.

### Mock-up
```
[🎫 Tickets (2 new)] [💬 Conversations] [📊 Reports] ... [📬 Inbox]
 Tickets (14)
 ┌───────────────────────────────────────────────────────────────┐
 │ [Member question] Anna K. · housing · "Can I get help with…"  │  waiting · 3h
 │   ▸ 2 messages (expand to read)                               │
 │ [Member question] Joe P. · jobs-training · "Is the course…"   │  waiting · 1d
 │ #8812 MN post · urgent · "Grant form rejected…"   [— action —]│  open · 20m
 │ [Member question] Sue L. · food · "Thanks, that worked"       │  answered · 2d
 └───────────────────────────────────────────────────────────────┘
```
Member-question rows have no action dropdown until the workflow slice; later they get Answer / Assign / Close like tickets.

## Slices — gate 4

### Slice order
Worktrees A and B run in parallel and touch no file in common. Neither edits `docs/specs/modules/coach_inbox.md` except A (its own functions); the overseer fills B's stubs at landing. Landing order: B, then A.

**A — `coach-inbox-list`** (read-only mixed list, badge, waiting count).
May touch: `coach_inbox.py` (new), `app.py` (tab label at ~1226, Tickets tab body, `render_ticket_table` for the badge row), `config.py` (`PRIVATE_CHAT_DATASET`), `tests/test_coach_inbox.py` (new), `tests/test_private_chat_insert_only.py` (new), `docs/specs/modules/coach_inbox.md` (its four functions + the code rule), `docs/briefs/coach-inbox-list.md`.
- A1 tracer: a hardcoded thread goes through `merge_into_tickets` and shows in Tickets with the badge. Proof: `pytest tests/test_coach_inbox.py -k merge` green, red first against `origin/main`; screenshot of the local app.
- A2 real read: `load_member_questions` against `private_chat` with names from `core_members`, derived status. Proof: fake-client test for R1-R3; local run against the real (empty or test) tables shows no error.
- A3 count: `waiting_count` and the `🎫 Tickets (N new)` label. Proof: test for R1-R2.
- A4 insert-only guard: `tests/test_private_chat_insert_only.py`, shown red with a fixture UPDATE, then green.
- A5 (after B has landed; rebase on `origin/main`): read failure -> `st.error` + `report_source_failure`. Proof: raising fake client -> empty frame and one captured `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED` line, red first.
Done when: A1-A5 proofs recorded in the brief, full `pytest tests/` green, B landed and its fire drill recorded.

**B — `coach-inbox-alert`** (alert helper for the app, and its policies).
May touch: `raillog.py` (new, repo root, copy of `jobs/raillog.py`), `jobs/alert_payloads.py` (service-scoped variants: `cloud_run_revision`, `service_name="grant-helpdesk"`), `jobs/deploy-alerts.sh` (second block for the service), `tests/test_raillog_app.py` (new), `tests/test_deploy_alerts_payloads.py`, `docs/briefs/coach-inbox-alert.md`.
- B1: root `raillog.py`, importable from `app.py`'s folder. Proof: test captures the exact JSON line with `severity` ERROR, red first.
- B2: service-scoped log-match and metric + threshold (24h re-notify) payloads, titles starting `BTB-ALERT bigtribebuilders`. Proof: offline payload tests, red first.
- B3: `deploy-alerts.sh` applies them, re-runnable, job policies unchanged. Proof: a dry re-run diff shows only the new service policies.
Done when: B1-B3 proofs in the brief. Fire drill (overseer, after landing B): run `jobs/deploy-alerts.sh`, write one synthetic `BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: fire drill` entry with resource `cloud_run_revision` / `service_name=grant-helpdesk` through the Logging API, see the email arrive, note it in `docs/briefs/coach-inbox-alert.md`.

**Overseer after A:** land A, `deploy.sh`, check the tab live against the real tables. Real fire drill: a no-traffic tagged revision with `PRIVATE_CHAT_DATASET` pointed at a missing dataset; open it, see the error and the email.

**Later — `coach-inbox-reply`** (reply box). Starts after A lands. May touch: `coach_inbox.py` (`add_coach_reply`), `app.py` (the reply box in the member-question row), `tests/test_coach_inbox_reply.py` (new), the spec's `add_coach_reply` section, its brief. Done when: tests prove role `coach`, `author_member_id` from `grant_coaches` for coach and admin alike, any coach can reply in any thread, the 4000-char limit, "unknown thread -> nothing written", no body in logs, write failure -> `SOURCE_FAILED` line (all red first); insert-only guard still green.

**Later — `coach-inbox-workflow`** (assign, lane, close). Starts after reply lands. May touch: `migrations/<n>_private_thread_workflow.sql` (new), `coach_inbox.py` (`set_thread_workflow`, read joins it), `bq_writes.py`, `app.py` (action dropdown for member-question rows), `config.py`, `tests/test_coach_inbox_workflow.py` (new), the spec's section, its brief. Done when: tests prove assign/lane/close write one row per thread, "member message after close -> waiting again", and closed threads leave the count (red first); overseer runs the migration.

**Then (zone overseer):** set `ZONE_WRITES=true`, ask one test question, answer it in the helpdesk, see "answered" on the member page; written into both briefs.

STOP: after every slice, message the overseer (SendMessage — find it with
ListAgents if the name needs a [ref]): "slice K done - continue or
re-steer?" plus a one-line summary of the slice and its proof line. Wait
for its reply before starting slice K+1 — it writes a slice file, asks
Martin in its own pane, and relays his answer back to you. Record that
reply here before continuing. Never ask Martin directly in this window.

## Settled 2026-09-25 (Martin)
- The admin gets a row in `grant_coaches`; nothing else supplies an MN id.
- Every coach sees and may answer every thread; the badge counts waiting threads, nothing stored.

## Open check
- "React to a specific message": replying to one message inside a thread, or only to the thread? Assumed thread; see the spec's Open check.

## Agentic review

### Verdict
Verdict: PASS, no blockers — 4 minor findings, all fixed as new commits.

### Findings
1. `tests/test_deploy_alerts_payloads.py`, `test_service_metric_name_matches_deploy_alerts_naming`: compared a test constant with a value derived from that same constant, so it could never fail, and never read `jobs/deploy-alerts.sh`.
2. `tests/test_deploy_alerts_payloads.py`, `test_service_threshold_policy_subject_keeps_btb_alert_prefix`: passed a title that already started with `BTB-ALERT bigtribebuilders` and checked that same input's prefix, so the real titles built in `jobs/deploy-alerts.sh` were never checked.
3. `jobs/deploy-alerts.sh`'s closing summary printed every page-1 policy a second time, headed "Policies now watching grant-helpdesk", even though the list is not filtered to the service.
4. `jobs/deploy-alerts.sh`'s header comment described only the three job-scoped policies, with no mention of the service-scoped block added below them.

### Fixed in
1. Fixed in `c1beaeb` — now reads `jobs/deploy-alerts.sh` and asserts the literal `SERVICE_METRIC_NAME="${SERVICE//-/_}_btb_alert_count"` line is present. Proved red by mutating that line once, confirmed the test failed, reverted, confirmed green.
2. Fixed in `c1beaeb` — now parses `TITLE_SERVICE` and `TITLE_SERVICE_METRIC` (and `PROJECT`'s default) out of the real script source, following `test_absence_policy_subject_keeps_btb_alert_prefix`'s existing pattern. Proved red by mutating `TITLE_SERVICE`'s prefix once, confirmed the test failed, reverted, confirmed green.
3. Fixed in `06589fd` — deleted the job block's own listing, renamed the remaining (service block's) heading to `Policies in ${PROJECT}`.
4. Fixed in `06589fd` — added a "SERVICE POLICIES BELOW" paragraph to the header comment, pointing at this brief.

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

Slice B of the approved coach-inbox gate: BTB_ALERT helper in the app path + log metric and threshold policy in jobs/deploy-alerts.sh; done-when and may-touch as in the gate; spec docs/specs/modules/coach_inbox.md

## Done when

B1: `pytest tests/test_raillog_app.py` proves root `raillog.py` prints the
exact `{"severity": "ERROR", "message": "BTB_ALERT grant-helpdesk/<runnable>
<CODE>: <message>"}` line (captured on stdout) — red first (file does not
exist yet), then green.

B2: `pytest tests/test_deploy_alerts_payloads.py` proves the new
service-scoped payload builders in `jobs/alert_payloads.py` —
`service_metric_log_filter`, `service_log_match_policy`,
`service_threshold_policy` — build a `resource.type="cloud_run_revision"`,
`resource.labels.service_name="grant-helpdesk"` filter, a log-match policy
with no `notificationChannelStrategy`, and a threshold policy with the 24h
`alignmentPeriod`/82800s `renotifyInterval` re-notify shape already proven for
the job policies, titles starting `BTB-ALERT bigtribebuilders` — red first,
then green.

B3: `jobs/deploy-alerts.sh` gains a second, re-runnable block that applies
those two service policies via the existing `apply_policy`/`find_policy`
helpers, leaving the existing job block and its policies untouched. Proof:
`bash -n jobs/deploy-alerts.sh` (parses) plus the offline payload tests above;
the live re-run against `bigtribebuilders` (dry re-run diff showing only the
new service policies, then the fire drill) is the overseer's to run after
landing, per its own memory message below — this worktree never runs
`deploy-alerts.sh`.

Full `pytest tests/` green at the end.

Spec: unchanged. `docs/specs/modules/coach_inbox.md`'s two functions this
slice touches (`raillog.alert` and "deploy-alerts.sh (service policies)") are
both marked `<!-- spec:stub -->`, and the brief's own Slice order note says
"the overseer fills B's stubs at landing" — this worktree does not edit
`docs/specs/`. Concrete R-line text for the overseer to apply is under Spec
proposals below.

## May touch

Module: `coach_inbox` (alert half). Files: `raillog.py` (new, repo root),
`jobs/alert_payloads.py`, `jobs/deploy-alerts.sh`, `tests/test_raillog_app.py`
(new), `tests/test_deploy_alerts_payloads.py`, `docs/briefs/coach-inbox-alert.md`.

## Deploy implied

`jobs/deploy-alerts.sh` — creates/reconciles two new Cloud Monitoring alert
policies (log-match + 24h-renotifying threshold) scoped to the grant-helpdesk
Cloud Run *service*, plus their backing log metric. The overseer runs it from
main after the merge, then does the fire drill described in the gate's Slice
B done-when. No `deploy.sh` (app) implication — this slice touches no `app.py`
code path.

## Context

- Gate header cites `20260924-HANDOFF-questions-zone-coach-inbox.md` as a
  source doc — not present anywhere in this repo (checked with `find`); it
  may live only in the overseer's pane or another repo. Not needed for this
  slice's code, which comes entirely from the gate text and the spec.
- Existing pattern this slice copies almost verbatim, scoped from job to
  service: `jobs/alert_payloads.py`'s `metric_log_filter`/`log_match_policy`/
  `threshold_policy` and `jobs/deploy-alerts.sh`'s job block, both already
  proven live for `poll-dataform-failures` (see `tests/test_deploy_alerts_payloads.py`).
- Overseer's memory message (2026-09-25, relayed after `wt-new.sh`, in full):
  1. TRAP 2026-09-24: Cloud Monitoring rejects `renotifyInterval`
     (`notificationChannelStrategy`) on log-match (`conditionMatchedLog`)
     policies — hence the separate metric + `conditionThreshold` policy.
     Existing pattern: `poll_dataform_failures_btb_alert_count`,
     `alignmentPeriod` 86400s, renotify 82800s, `autoClose` 7d.
  2. TRAP 2026-09-24: a `conditionThreshold` on a log-based metric must
     restrict `resource.type` itself. For this app that's
     `resource.type="cloud_run_revision"` (a Cloud Run *service*, not a job);
     without it, CREATE is rejected. Offline tests do not catch this.
  3. TRAP 2026-09-24: never set `evaluationMissingData` when `duration` is
     `"0s"` — the API rejects the combination (leave it unset; UNSPECIFIED
     behaves as NO_OP).
  4. TRAP 2026-09-15: a Cloud Run `print()` of
     `{"severity":"ERROR","message":"BTB_ALERT …"}` lands in `textPayload`,
     NOT `jsonPayload.message`. The metric filter must match
     `textPayload:"BTB_ALERT" OR jsonPayload.message:"BTB_ALERT"` with no
     severity clause, scoped to this repo's own alert-line prefix
     (`BTB_ALERT grant-helpdesk/`) so it doesn't double-count another
     service's own BTB_ALERT lines.
  5. TRAP 2026-09-14: Monitoring omits `thresholdValue: 0` from what it
     returns — treat a missing value as 0 or the re-run isn't idempotent. A
     failed CREATE may still have created the policy: re-read before
     retrying. Subject goes in `documentation.subject`, starting
     `BTB-ALERT bigtribebuilders`.
  6. TRAP 2026-09-17: a policy on a just-created log metric can fail with
     "Cannot find metric(s)… up to 10 minutes" — `deploy-alerts.sh` must stay
     safely re-runnable for that case.
  7. Fire drill note: `gcloud logging write` lands on the global resource and
     cannot trigger a `cloud_run_revision` filter — the fire drill needs
     steps that cause a real failure in the service, not a synthetic log
     write.
  The message also repeats the repo/role rule: this worktree never runs
  `deploy-alerts.sh` or any deploy; the overseer does, from main.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Proposed R-line text for the two stub sections
this slice fills, for the overseer to apply to `docs/specs/modules/coach_inbox.md`:

**`raillog.alert(runnable, code, message)`** — replace the stub line with:
functionally identical to `jobs/raillog.py` (same `REPO = "grant-helpdesk"`,
same `CODES` set, same JSON-line shape and unknown-code fallback to
`UNEXPECTED`); it is a separate file, not an import, because each Cloud Run
job's own Dockerfile `COPY`s only its one script plus `jobs/raillog.py`, and
the Streamlit app's Dockerfile builds from the repo root, so the root copy is
what makes `import raillog` resolve from `app.py`'s own folder. Test:
`tests/test_raillog_app.py`, capsys asserts the exact JSON line for a known
code and the `UNEXPECTED` fallback for an unknown one; red first.

**"deploy-alerts.sh (service policies)"** — replace the stub line with: adds
`jobs/alert_payloads.py`'s `service_metric_log_filter(service)`,
`service_log_match_policy(title, service, project, channel)`,
`service_threshold_policy(title, service, project, channel, metric_name)` —
same shapes as the job-scoped `metric_log_filter`/`log_match_policy`/
`threshold_policy`, but `resource.type="cloud_run_revision"` +
`resource.labels.service_name` instead of `cloud_run_job` + `job_name`, and
the log filter additionally requires the `BTB_ALERT grant-helpdesk/` prefix
(trap 4 above) since a service's logs are not already scoped to one repo the
way a job's are. `jobs/deploy-alerts.sh` gains a second, symmetric block
(`SERVICE="${SERVICE:-grant-helpdesk}"`) using the same `apply_policy`/
`find_policy`/metric-create-or-update flow as the job block, metric name
`grant_helpdesk_btb_alert_count`. Test:
`tests/test_deploy_alerts_payloads.py`, offline payload-shape tests mirroring
the job-policy ones; `bash -n jobs/deploy-alerts.sh` for the script itself;
red first. Live proof (dry re-run diff, then the fire drill) is the
overseer's, after landing.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
- Brief filled in and committed (d9cc716).
- B1: root `raillog.py` (copy of `jobs/raillog.py`) + `tests/test_raillog_app.py`,
  red then green (8a7240f).
- B2: `service_metric_log_filter`/`service_log_match_policy`/
  `service_threshold_policy` added to `jobs/alert_payloads.py` (cloud_run_revision
  + service_name="grant-helpdesk", repo-prefixed filter per trap 4), CLI
  subcommands `service-metric-filter`/`service-log-match-policy`/
  `service-threshold-policy` added; 17 new tests in
  `tests/test_deploy_alerts_payloads.py`, red then green (998df03).
- B3: second block in `jobs/deploy-alerts.sh` (`SERVICE="${SERVICE:-grant-helpdesk}"`)
  applying the two service policies + their log metric via the existing
  apply_policy/find_policy helpers; job block untouched. `bash -n` parses.
  Full `pytest tests/` green (93 passed) (c2971d9).

In flight (file:line): none — B1-B3 all committed and green.

Next:
1. Run `wt-done.sh --check coach-inbox-alert` (clean tree, origin/main merge,
   WT_TEST) and fix anything it refuses on.
2. `git add -N .` then `git status` to confirm clean.
3. Merge `origin/main` once (not rebase), right before reporting.
4. SendMessage to `helpdesk-opzichter`: branch `coach-inbox-alert`, commit
   range d9cc716..c2971d9 (plus the merge commit), HEAD sha, 5-line summary,
   red-then-green proof, deploy implication (overseer runs
   `jobs/deploy-alerts.sh` from main, then the fire drill — this worktree
   never runs it). Then wait for its review reply.
5. Tell the overseer's SendMessage that already arrived mid-session (see
   Context, "Overseer's memory message") was received and acted on — no
   reply needed unless it asks a question.

Traps (with dates):
- 2026-09-25 (overseer memory, in full under Context above): resource.type
  restriction required on conditionThreshold even when the metric filter
  already scopes it; evaluationMissingData rejected with duration "0s";
  Cloud Run print() lands in textPayload not jsonPayload.message, no severity
  clause works; thresholdValue:0 omitted on read (same_policy must tolerate
  it); a just-created log metric can 404 for up to 10 min; fire drill can't
  use `gcloud logging write` (global resource, won't match cloud_run_revision) —
  needs a real service failure instead.
- 2026-09-25 (this session): `jobs/deploy-alerts.sh` sets one `trap ... EXIT`
  per temp file — a second `trap ... EXIT` for a second mktemp file silently
  replaces the first instead of adding to it (bash keeps only the last EXIT
  handler). The service block's trap removes both `METRIC_DESCRIBE_ERR` and
  `SERVICE_METRIC_DESCRIBE_ERR` for this reason — don't add a third mktemp
  block with its own lone `trap` without folding it into the same line.
