#!/usr/bin/env bash
# One alert policy: page Martin when poll_dataform_failures.py logs a
# BTB_ALERT line, per docs/briefs/dedupe-ticket-tables.md's requirement that
# grant_ticket_labels gets an alert proven to fire.
#
# NOT A NEW PATTERN — this project (bigtribebuilders) already has an
# identical policy for a different job: "BTB-ALERT bigtribebuilders —
# cerbo-logger reported a BTB_ALERT" (id 6770814786273898596), which matches
# textPayload/jsonPayload.message:"BTB_ALERT" scoped to
# resource.labels.job_name="cerbo-logger". This script creates the same
# shape scoped to job_name="poll-dataform-failures" instead. No new log
# metric needed — a conditionMatchedLog policy watches Cloud Logging
# directly, the same way the cerbo-logger one does.
#
# WHY NOT THE EXISTING PROJECT-WIDE POLICIES INSTEAD:
#   "a Dataform invocation failed"       — fires on ANY repo's ANY action
#                                           failing, not specifically on
#                                           grant_ticket_labels, and carries
#                                           no repo-specific runbook.
#   "any Cloud Run job execution failed" — fires on the job's PROCESS exiting
#                                           non-zero, which also happens for
#                                           actions never in ALERTED_ACTIONS
#                                           (poll_dataform_failures.py can
#                                           exit 1 for reasons unrelated to
#                                           grant_ticket_labels).
# Both already exist and still apply — two alerts on one real failure is
# fine, per the "any Cloud Run job execution failed" policy's own
# documentation. This script adds the one thing neither covers: a policy
# that names grant_ticket_labels specifically, via the BTB_ALERT text
# raillog.alert() writes.
#
# Idempotent: find_policy/apply_policy below are lifted near-verbatim from
# lesko-questions-zone/deploy-alerts.sh — same page-walk-safe lookup, same
# whole-shape reconcile (condition + documentation + alertStrategy, not just
# the filter) so a later edit here can't silently stop reaching the live
# policy. Re-running this script is always safe.
#
# SECOND POLICY BELOW, SAME JOB: the log-match policy above cannot carry a
# 24h re-notify — confirmed live 2026-09-24, PATCHing
# alertStrategy.notificationChannelStrategy onto it returns
# "notificationChannelStrategy is not allowed for log-based alerts". A
# conditionThreshold (metric) policy is the kind that field is documented
# for, so this script also creates a log-based counter metric and a
# threshold policy on top of it — same shape lesko-questions-zone/
# deploy-alerts.sh already runs live for its own Dataform-failure alert, and
# lesko-provisioning/deploy-alerts.sh's rail_alert_by_code policy for the
# trap of leaving resource.type out of the filter or notificationRateLimit
# in the strategy. See docs/briefs/alert-renotify-metric.md for the full
# citation trail. The log-match policy above is left in place, unchanged,
# until the new one is proven to fire once — see that brief's "Deploy
# implied".
#
# THIRD POLICY BELOW, SAME JOB: the two above only page when the job runs
# and logs something — if the job or its Scheduler trigger stops running at
# all, neither ever fires, and quiet reads as "all fine"
# (docs/briefs/poller-heartbeat.md, Product). This script also creates a
# conditionAbsent policy on Cloud Run's own built-in
# completed_execution_count metric, watching for 5400s (90 min: the hourly
# schedule plus a margin) with no successful execution. No new log metric
# needed — see that brief's Architecture, "Rejected alternative".
#
# SERVICE POLICIES BELOW: everything above this point watches
# poll-dataform-failures, a Cloud Run job. The last two policies in this
# script instead watch grant-helpdesk, the app itself — a Cloud Run
# service, which Monitoring addresses differently (resource.type=
# "cloud_run_revision" + service_name, not "cloud_run_job" + job_name). See
# docs/briefs/coach-inbox-alert.md, slice B, for why and what they cover.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT="${PROJECT:-bigtribebuilders}"
JOB="${JOB:-poll-dataform-failures}"
SERVICE="${SERVICE:-grant-helpdesk}"
CHANNEL_NAME="${CHANNEL_NAME:-Martin (email)}"

TOKEN="$(gcloud auth print-access-token)"
API="https://monitoring.googleapis.com/v3/projects/${PROJECT}"

CHANNEL=$(curl -s -H "Authorization: Bearer $TOKEN" "${API}/notificationChannels" \
  | python3 -c "
import json,sys
name='''${CHANNEL_NAME}'''
for c in json.load(sys.stdin).get('notificationChannels',[]):
    if c.get('displayName')==name: print(c['name']); break")
[ -n "$CHANNEL" ] || { echo "no notification channel named '${CHANNEL_NAME}' in ${PROJECT} — not creating one, fix by hand"; exit 1; }
echo "==> routing to ${CHANNEL}"

# find_policy DISPLAYNAME — the live alertPolicy JSON with this displayName,
# or empty if none exists yet. SQL analogy: SELECT ... WHERE display_name = ?
# LIMIT 1 — except this "table" is over the network and can fail without
# being empty, so a malformed body, an {"error": ...} envelope, an ambiguous
# multi-row match, or a page walk that never terminates all exit 1 instead of
# printing as "not found" (caught by `set -euo pipefail`).
ALERT_POLICY_LIST_MAX_PAGES="${ALERT_POLICY_LIST_MAX_PAGES:-50}"

find_policy() {
  local title="$1"
  python3 - "$TOKEN" "$API" "$title" "$ALERT_POLICY_LIST_MAX_PAGES" <<'PY'
import json
import subprocess
import sys

token, api, title, max_pages = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
matches = []
page_token = None
page = 0
while True:
    page += 1
    if page > max_pages:
        sys.stderr.write(
            "ERROR: alertPolicies list for %r did not finish after %d pages "
            "(nextPageToken still present) — stopping instead of looping "
            "forever\n" % (title, max_pages))
        sys.exit(1)
    cmd = ["curl", "-s", "-G", "-H", "Authorization: Bearer %s" % token,
           "--data-urlencode", 'filter=display_name="%s"' % title]
    if page_token:
        cmd += ["--data-urlencode", "pageToken=%s" % page_token]
    cmd.append("%s/alertPolicies" % api)
    body = subprocess.run(cmd, capture_output=True, text=True).stdout
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        sys.stderr.write(
            "ERROR: alertPolicies list for %r was not valid JSON: %s\n" % (title, e))
        sys.exit(1)
    if "error" in data:
        sys.stderr.write(
            "ERROR: alertPolicies list for %r failed: %s\n"
            % (title, data["error"].get("message", data["error"])))
        sys.exit(1)
    matches += [p for p in data.get("alertPolicies", []) if p.get("displayName") == title]
    if len(matches) > 1:
        sys.stderr.write(
            "ERROR: alertPolicies list for %r returned more than one policy "
            "with that name — ambiguous, stopping\n" % title)
        sys.exit(1)
    page_token = data.get("nextPageToken")
    if not page_token:
        break

if matches:
    print(json.dumps(matches[0]))
PY
}

# apply_policy TITLE PAYLOAD — create-or-reconcile-in-place. Compares the
# WHOLE live condition (not just its filter) plus documentation and
# alertStrategy, so an edit to any of those actually reaches the live policy
# on a re-run instead of being masked by a filter-only match.
apply_policy() {
  local title="$1" payload="$2"
  local existing
  existing=$(find_policy "$title") || exit 1
  if [ -z "$existing" ]; then
    echo "==> creating '$title'"
    local response
    response=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d "$payload" "${API}/alertPolicies")
    echo "$response" | python3 -c "
import json,sys; d=json.load(sys.stdin)
if 'error' in d:
    print('   ERROR: ' + d['error']['message'])
    print('   re-run this script before retrying by hand — it checks find_policy() first')
    sys.exit(1)
print('   created')
"
    return
  fi

  local same
  same=$(python3 "$SCRIPT_DIR/alert_payloads.py" same-policy "$existing" "$payload")
  if [ "$same" = "True" ]; then
    echo "==> '$title' exists and matches — leaving it"
    return
  fi

  echo "==> '$title' exists but has drifted from this file — patching"
  local pname patch_body response
  pname=$(printf '%s' "$existing" | python3 -c "import json,sys; print(json.load(sys.stdin)['name'])")
  patch_body=$(python3 -c "
import json, sys
existing, want = json.loads(sys.argv[1]), json.loads(sys.argv[2])
# Keep the existing condition's own name — that is what makes this an UPDATE
# rather than a delete-and-recreate, so the policy keeps its id and any
# already-open incident stays attached to it.
cond = existing.get('conditions', [{}])[0]
name = cond.get('name')
cond.clear()
cond.update(want['conditions'][0])
if name:
    cond['name'] = name
print(json.dumps({
    'conditions': [cond],
    'alertStrategy': want['alertStrategy'],
    'documentation': want['documentation'],
}))
" "$existing" "$payload")
  response=$(curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "$patch_body" \
    "https://monitoring.googleapis.com/v3/${pname}?updateMask=conditions,alertStrategy,documentation")
  echo "$response" | python3 -c "
import json,sys; d=json.load(sys.stdin)
if 'error' in d:
    print('   ERROR: ' + d['error']['message']); sys.exit(1)
print('   patched')
"
}

# ── the policy ────────────────────────────────────────────────────────────
# Payload built by alert_payloads.py's log_match_policy(), not inline here —
# round-3 review (should-fix #3) moved it there so
# tests/test_deploy_alerts_payloads.py can check its shape offline. This
# script only ever calls the CLI form so both paths run the same code (see
# alert_payloads.py's module docstring).
TITLE="BTB-ALERT ${PROJECT} — ${JOB} reported a BTB_ALERT"
PAYLOAD=$(python3 "$SCRIPT_DIR/alert_payloads.py" log-match-policy "$TITLE" "$JOB" "$PROJECT" "$CHANNEL")

apply_policy "$TITLE" "$PAYLOAD"

# ── the log metric: one count per BTB_ALERT line from ${JOB} ────────────────
# Counts exactly the lines the log-match policy above already watches —
# metric_log_filter() in alert_payloads.py builds that filter so
# tests/test_deploy_alerts_payloads.py can check it offline; this script only
# ever calls the CLI form so both paths run the same code. No custom
# metricDescriptor: an unspecified one defaults to DELTA/INT64/no labels
# (Cloud Logging REST docs, projects.metrics), exactly a bare counter, which
# is all a threshold policy needs.
METRIC_NAME="${JOB//-/_}_btb_alert_count"
METRIC_FILTER=$(python3 "$SCRIPT_DIR/alert_payloads.py" metric-filter "$JOB")
METRIC_DESCRIBE_ERR="$(mktemp)"
trap 'rm -f "$METRIC_DESCRIBE_ERR"' EXIT
if gcloud logging metrics describe "$METRIC_NAME" --project "$PROJECT" >/dev/null 2>"$METRIC_DESCRIBE_ERR"; then
  EXISTING_METRIC_FILTER=$(gcloud logging metrics describe "$METRIC_NAME" --project "$PROJECT" --format='value(filter)')
  if [ "$EXISTING_METRIC_FILTER" = "$METRIC_FILTER" ]; then
    echo "==> metric '$METRIC_NAME' exists and matches — leaving it"
  else
    echo "==> metric '$METRIC_NAME' filter has drifted from this file — updating"
    gcloud logging metrics update "$METRIC_NAME" --project "$PROJECT" --log-filter="$METRIC_FILTER" >/dev/null
  fi
elif grep -q "NOT_FOUND" "$METRIC_DESCRIBE_ERR"; then
  echo "==> creating metric '$METRIC_NAME'"
  gcloud logging metrics create "$METRIC_NAME" --project "$PROJECT" \
    --description="One count per BTB_ALERT line from ${JOB}. Backs the renotifying metric-threshold policy below — see docs/briefs/alert-renotify-metric.md for why the log-match policy above cannot carry a 24h renotify itself." \
    --log-filter="$METRIC_FILTER" >/dev/null
else
  echo "ERROR: could not look up metric '$METRIC_NAME' (not a NOT_FOUND) — stopping, nothing changed:"
  cat "$METRIC_DESCRIBE_ERR"
  exit 1
fi

# ── the renotifying policy on top of it ──────────────────────────────────────
TITLE_METRIC="BTB-ALERT ${PROJECT} — ${JOB} reported a BTB_ALERT (renotifies every 24h)"
PAYLOAD_METRIC=$(python3 "$SCRIPT_DIR/alert_payloads.py" threshold-policy \
  "$TITLE_METRIC" "$JOB" "$PROJECT" "$CHANNEL" "$METRIC_NAME")
apply_policy "$TITLE_METRIC" "$PAYLOAD_METRIC"

# ── the silence policy: pages when ${JOB} stops running at all ──────────────
# The two policies above only page when the job runs and logs a BTB_ALERT
# line — if the job or its Scheduler trigger stops running entirely, those
# go quiet, and quiet reads as "all fine" (docs/briefs/poller-heartbeat.md,
# Product). This one watches Cloud Run's own built-in execution-count
# metric instead of a log line, so it needs no new log metric of its own —
# see that brief's Architecture, "Rejected alternative".
TITLE_SILENCE="BTB-ALERT ${PROJECT} — ${JOB} went silent (no successful run in 90 min)"
PAYLOAD_SILENCE=$(python3 "$SCRIPT_DIR/alert_payloads.py" absence-policy \
  "$TITLE_SILENCE" "$JOB" "$PROJECT" "$CHANNEL")
apply_policy "$TITLE_SILENCE" "$PAYLOAD_SILENCE"

# ── SERVICE POLICIES: the grant-helpdesk app itself ─────────────────────────
# coach-inbox-alert brief, slice B. Everything above this point watches
# poll-dataform-failures, a Cloud Run *job*. The app is a Cloud Run
# *service*, which Monitoring addresses differently
# (resource.type="cloud_run_revision" + service_name, not "cloud_run_job" +
# job_name) — same two-policy shape as above (log-match can't carry a 24h
# re-notify; a conditionThreshold on a backing log metric can), built by the
# service-scoped functions in alert_payloads.py so this block and
# tests/test_deploy_alerts_payloads.py share one code path, same as the job
# block above.
echo
echo "==> now applying policies for service ${SERVICE}"

TITLE_SERVICE="BTB-ALERT ${PROJECT} — ${SERVICE} reported a BTB_ALERT"
PAYLOAD_SERVICE=$(python3 "$SCRIPT_DIR/alert_payloads.py" service-log-match-policy \
  "$TITLE_SERVICE" "$SERVICE" "$PROJECT" "$CHANNEL")
apply_policy "$TITLE_SERVICE" "$PAYLOAD_SERVICE"

# ── the log metric: one count per BTB_ALERT line from ${SERVICE} ────────────
SERVICE_METRIC_NAME="${SERVICE//-/_}_btb_alert_count"
SERVICE_METRIC_FILTER=$(python3 "$SCRIPT_DIR/alert_payloads.py" service-metric-filter "$SERVICE")
SERVICE_METRIC_DESCRIBE_ERR="$(mktemp)"
# Replaces, not adds to, the job block's own EXIT trap above — bash keeps only
# the last handler registered for a given signal — so this one removes both
# temp files, or the job block's would leak.
trap 'rm -f "$METRIC_DESCRIBE_ERR" "$SERVICE_METRIC_DESCRIBE_ERR"' EXIT
if gcloud logging metrics describe "$SERVICE_METRIC_NAME" --project "$PROJECT" >/dev/null 2>"$SERVICE_METRIC_DESCRIBE_ERR"; then
  EXISTING_SERVICE_METRIC_FILTER=$(gcloud logging metrics describe "$SERVICE_METRIC_NAME" --project "$PROJECT" --format='value(filter)')
  if [ "$EXISTING_SERVICE_METRIC_FILTER" = "$SERVICE_METRIC_FILTER" ]; then
    echo "==> metric '$SERVICE_METRIC_NAME' exists and matches — leaving it"
  else
    echo "==> metric '$SERVICE_METRIC_NAME' filter has drifted from this file — updating"
    gcloud logging metrics update "$SERVICE_METRIC_NAME" --project "$PROJECT" --log-filter="$SERVICE_METRIC_FILTER" >/dev/null
  fi
elif grep -q "NOT_FOUND" "$SERVICE_METRIC_DESCRIBE_ERR"; then
  echo "==> creating metric '$SERVICE_METRIC_NAME'"
  gcloud logging metrics create "$SERVICE_METRIC_NAME" --project "$PROJECT" \
    --description="One count per BTB_ALERT line from the ${SERVICE} service. Backs the renotifying metric-threshold policy below — see docs/specs/modules/coach_inbox.md." \
    --log-filter="$SERVICE_METRIC_FILTER" >/dev/null
else
  echo "ERROR: could not look up metric '$SERVICE_METRIC_NAME' (not a NOT_FOUND) — stopping, nothing changed:"
  cat "$SERVICE_METRIC_DESCRIBE_ERR"
  exit 1
fi

# ── the renotifying policy on top of it ──────────────────────────────────────
TITLE_SERVICE_METRIC="BTB-ALERT ${PROJECT} — ${SERVICE} reported a BTB_ALERT (renotifies every 24h)"
PAYLOAD_SERVICE_METRIC=$(python3 "$SCRIPT_DIR/alert_payloads.py" service-threshold-policy \
  "$TITLE_SERVICE_METRIC" "$SERVICE" "$PROJECT" "$CHANNEL" "$SERVICE_METRIC_NAME")
apply_policy "$TITLE_SERVICE_METRIC" "$PAYLOAD_SERVICE_METRIC"

# ── DATAFORM SILENCE POLICY: the grant-helpdesk pipeline itself ─────────────
# docs/specs/modules/alert_payloads.md, R10. Everything above pages when
# something runs and logs a failure; a Dataform run that never starts writes
# nothing, so this pages on the SUCCEEDED completion line going absent for an
# hour. ORDER MATTERS: a log metric only counts entries written after it is
# created, and conditionAbsent only fires for a series Monitoring has already
# seen, so the metric is created first and the policy that names it second.
# On a cold deploy the policy may sit without a series until the first
# SUCCEEDED run lands — expected, do not seed anything.
echo
echo "==> now applying the Dataform silence policy"

DATAFORM_METRIC_NAME="grant_helpdesk_dataform_succeeded"
DATAFORM_METRIC_FILTER=$(python3 "$SCRIPT_DIR/alert_payloads.py" dataform-metric-filter)
DATAFORM_METRIC_DESCRIBE_ERR="$(mktemp)"
# Replaces the earlier EXIT trap (bash keeps only the last), so it lists all three.
trap 'rm -f "$METRIC_DESCRIBE_ERR" "$SERVICE_METRIC_DESCRIBE_ERR" "$DATAFORM_METRIC_DESCRIBE_ERR"' EXIT
if gcloud logging metrics describe "$DATAFORM_METRIC_NAME" --project "$PROJECT" >/dev/null 2>"$DATAFORM_METRIC_DESCRIBE_ERR"; then
  EXISTING_DATAFORM_METRIC_FILTER=$(gcloud logging metrics describe "$DATAFORM_METRIC_NAME" --project "$PROJECT" --format='value(filter)')
  if [ "$EXISTING_DATAFORM_METRIC_FILTER" = "$DATAFORM_METRIC_FILTER" ]; then
    echo "==> metric '$DATAFORM_METRIC_NAME' exists and matches — leaving it"
  else
    echo "==> metric '$DATAFORM_METRIC_NAME' filter has drifted from this file — updating"
    gcloud logging metrics update "$DATAFORM_METRIC_NAME" --project "$PROJECT" --log-filter="$DATAFORM_METRIC_FILTER" >/dev/null
  fi
elif grep -q "NOT_FOUND" "$DATAFORM_METRIC_DESCRIBE_ERR"; then
  echo "==> creating metric '$DATAFORM_METRIC_NAME'"
  gcloud logging metrics create "$DATAFORM_METRIC_NAME" --project "$PROJECT" \
    --description="One count per SUCCEEDED grant-helpdesk-5min Dataform run. Backs the silence policy below — see docs/specs/modules/alert_payloads.md." \
    --log-filter="$DATAFORM_METRIC_FILTER" >/dev/null
else
  echo "ERROR: could not look up metric '$DATAFORM_METRIC_NAME' (not a NOT_FOUND) — stopping, nothing changed:"
  cat "$DATAFORM_METRIC_DESCRIBE_ERR"
  exit 1
fi

TITLE_DATAFORM_SILENCE="BTB-ALERT ${PROJECT} — grant-helpdesk Dataform pipeline went silent (no successful run in 60 min)"
PAYLOAD_DATAFORM_SILENCE=$(python3 "$SCRIPT_DIR/alert_payloads.py" dataform-silence-policy \
  "$TITLE_DATAFORM_SILENCE" "$PROJECT" "$CHANNEL" "$DATAFORM_METRIC_NAME")
apply_policy "$TITLE_DATAFORM_SILENCE" "$PAYLOAD_DATAFORM_SILENCE"

# ── WATCH-DISCONNECTS: the weekly watch on lost coach sessions ──────────────
# docs/briefs/disconnect-resilience.md. jobs/watch_disconnects.py runs weekly
# and raises SESSION_LOST when coaches are losing whole sessions to dropped
# websockets faster than the agreed rate. Two policies, not the three the
# poller has: the renotifying metric one below, and a silence one. No
# log-match twin — that pair exists on poll-dataform-failures only because
# the log-match policy came first and is kept until the metric one is proven
# (docs/briefs/alert-renotify-metric.md). A new job starts with the proven
# shape instead of inheriting the transition.
WATCH_JOB="${WATCH_JOB:-watch-disconnects}"
# 8 days: its Scheduler trigger is weekly, so the window is one schedule plus
# a day of margin. SILENCE_WINDOW_SECONDS (90 min) is sized for the hourly
# poller and would page every single week if it were reused here.
WATCH_SILENCE_WINDOW_SECONDS="${WATCH_SILENCE_WINDOW_SECONDS:-691200}"

WATCH_METRIC_NAME="${WATCH_JOB//-/_}_btb_alert_count"
WATCH_METRIC_FILTER=$(python3 "$SCRIPT_DIR/alert_payloads.py" metric-filter "$WATCH_JOB")
WATCH_METRIC_DESCRIBE_ERR="$(mktemp)"
if gcloud logging metrics describe "$WATCH_METRIC_NAME" --project "$PROJECT" >/dev/null 2>"$WATCH_METRIC_DESCRIBE_ERR"; then
  EXISTING_WATCH_METRIC_FILTER=$(gcloud logging metrics describe "$WATCH_METRIC_NAME" --project "$PROJECT" --format='value(filter)')
  if [ "$EXISTING_WATCH_METRIC_FILTER" = "$WATCH_METRIC_FILTER" ]; then
    echo "==> metric '$WATCH_METRIC_NAME' exists and matches — leaving it"
  else
    echo "==> metric '$WATCH_METRIC_NAME' filter has drifted from this file — updating"
    gcloud logging metrics update "$WATCH_METRIC_NAME" --project "$PROJECT" --log-filter="$WATCH_METRIC_FILTER" >/dev/null
  fi
elif grep -q "NOT_FOUND" "$WATCH_METRIC_DESCRIBE_ERR"; then
  echo "==> creating metric '$WATCH_METRIC_NAME'"
  gcloud logging metrics create "$WATCH_METRIC_NAME" --project "$PROJECT" \
    --description="One count per BTB_ALERT line from ${WATCH_JOB}, the weekly watch on coach sessions lost to dropped websockets. See docs/briefs/disconnect-resilience.md." \
    --log-filter="$WATCH_METRIC_FILTER" >/dev/null
else
  echo "ERROR: could not look up metric '$WATCH_METRIC_NAME' (not a NOT_FOUND) — stopping, nothing changed:"
  cat "$WATCH_METRIC_DESCRIBE_ERR"
  rm -f "$WATCH_METRIC_DESCRIBE_ERR"
  exit 1
fi
rm -f "$WATCH_METRIC_DESCRIBE_ERR"

TITLE_WATCH="BTB-ALERT ${PROJECT} — ${WATCH_JOB} reported a BTB_ALERT (renotifies every 24h)"
PAYLOAD_WATCH=$(python3 "$SCRIPT_DIR/alert_payloads.py" threshold-policy \
  "$TITLE_WATCH" "$WATCH_JOB" "$PROJECT" "$CHANNEL" "$WATCH_METRIC_NAME")
apply_policy "$TITLE_WATCH" "$PAYLOAD_WATCH"

TITLE_WATCH_SILENCE="BTB-ALERT ${PROJECT} — ${WATCH_JOB} went silent (no successful run in 8 days)"
PAYLOAD_WATCH_SILENCE=$(python3 "$SCRIPT_DIR/alert_payloads.py" absence-policy \
  "$TITLE_WATCH_SILENCE" "$WATCH_JOB" "$PROJECT" "$CHANNEL" "$WATCH_SILENCE_WINDOW_SECONDS")
apply_policy "$TITLE_WATCH_SILENCE" "$PAYLOAD_WATCH_SILENCE"

echo
echo "Policies in ${PROJECT} (page 1 only — cosmetic, not a completeness check):"
curl -s -H "Authorization: Bearer $TOKEN" "${API}/alertPolicies" | python3 -c "
import json,sys
for p in json.load(sys.stdin).get('alertPolicies',[]):
    print('  -', p.get('displayName'))"
