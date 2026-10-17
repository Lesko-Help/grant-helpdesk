#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# watch-disconnects — deploy the weekly watch on lost coach sessions
#
# Usage:  jobs/deploy-watch-disconnects.sh [--drill]
#
# In:  nothing (every value below has a default; override by environment).
# Out: the Cloud Run job, its image, and its weekly Scheduler trigger, created
#      or reconciled in place. Re-runnable: a second run on an unchanged repo
#      changes nothing.
# Why: docs/briefs/disconnect-resilience.md. The app now keeps a coach's
#      session alive for 30 minutes after her websocket drops; this is how we
#      find out whether that held, without waiting for her to complain again.
#
# The alert policies are NOT here — they live with every other policy in
# jobs/deploy-alerts.sh, which must be run after this script the first time.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT="${PROJECT:-bigtribebuilders}"
REGION="${REGION:-europe-west1}"
JOB="${JOB:-watch-disconnects}"
SERVICE="${SERVICE:-grant-helpdesk}"
IMAGE="${IMAGE:-${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${JOB}:latest}"

# The job's own identity. roles/editor on this account already covers reading
# the request log (logging.logEntries.list), so this script grants nothing —
# checked 2026-10-16. If that role is ever narrowed, the job needs
# roles/logging.viewer and will say SOURCE_FAILED until it gets it.
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-170880920649-compute@developer.gserviceaccount.com}"

# Twice a day, 08:17 and 20:17. Not weekly, although weekly is all the review
# needs: a conditionAbsent heartbeat has to have a window longer than the gap
# between runs AND under Monitoring's 23h30m ceiling, so a job that runs less
# often than about once a day cannot be watched for silence at all (learned
# live 2026-10-17 - see docs/briefs/watch-silence-window.md). Each run is one
# Cloud Logging read, so the cost of running 14x more often is nil, and a
# regression now reaches Martin within 12 hours instead of a week.
# Not :00: every scheduler in every project fires on the hour.
SCHEDULE="${SCHEDULE:-17 8,20 * * *}"
TIMEZONE="${TIMEZONE:-Europe/Brussels}"
SCHEDULER_JOB="${SCHEDULER_JOB:-${JOB}-weekly}"

WINDOW_DAYS="${WINDOW_DAYS:-7}"
# Must match .streamlit/config.toml's server.disconnectedSessionTTL — it is
# the line between "she saw a flicker" and "she lost her screen".
TTL_SECONDS="${TTL_SECONDS:-1800}"
MAX_RESETS_PER_DAY="${MAX_RESETS_PER_DAY:-5}"
# One guaranteed review mail, on one named day: both of that day's runs raise
# a line, and the threshold policy aligns over 24h and renotifies every 24h,
# so Monitoring opens one incident and sends one mail. A date, not a flag, so
# nobody has to remember to switch it off - and ON one date rather than UNTIL
# one, because UNTIL plus a 12-hourly schedule would mail every day for a week.
REPORT_ALWAYS_ON="${REPORT_ALWAYS_ON:-2026-10-23}"

if [ "${1:-}" = "--drill" ]; then
  cat <<DRILL

Break it on purpose (global CLAUDE.md rule 5), then check the mail arrived:

  gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait \\
      --update-env-vars MAX_RESETS_PER_DAY=0

  A threshold of 0 makes any lost session at all cross the line, so a real run
  over real data raises a real BTB_ALERT SESSION_LOST line. Nothing is faked
  and nothing is left behind: --update-env-vars is an override for this one
  execution, so the job's own env still says
  MAX_RESETS_PER_DAY=$MAX_RESETS_PER_DAY on the next scheduled run.

  Not --args: that REPLACES the container's args, and the image sets its
  command through CMD, so the override would try to exec
  "--max-resets-per-day" instead of python and fail before the code runs.

  Expect mail with subject:
    [ALERT - No severity] BTB-ALERT $PROJECT — $JOB reported a BTB_ALERT (renotifies every 24h)

  If no mail arrives, the policy is missing — run jobs/deploy-alerts.sh.

DRILL
  exit 0
fi

echo "==> building $IMAGE"
BUILD_CONFIG="$(mktemp -t watch-disconnects-build.XXXXXX.yaml)"
trap 'rm -f "$BUILD_CONFIG"' EXIT
# An explicit build config, because the build context (jobs/) holds several
# Dockerfiles and `gcloud builds submit --tag` would pick the one named
# plain "Dockerfile" — which builds a different job entirely.
cat > "$BUILD_CONFIG" <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "Dockerfile.watch_disconnects", "-t", "${IMAGE}", "."]
images: ["${IMAGE}"]
YAML
gcloud builds submit "$SCRIPT_DIR" --project "$PROJECT" --config "$BUILD_CONFIG" --quiet

echo "==> deploying job '$JOB' (creates it the first time, updates it after)"
gcloud run jobs deploy "$JOB" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT" \
  --service-account "$SERVICE_ACCOUNT" \
  --max-retries 1 \
  --task-timeout 600s \
  --set-env-vars "PROJECT=${PROJECT},SERVICE=${SERVICE},WINDOW_DAYS=${WINDOW_DAYS},TTL_SECONDS=${TTL_SECONDS},MAX_RESETS_PER_DAY=${MAX_RESETS_PER_DAY},REPORT_ALWAYS_ON=${REPORT_ALWAYS_ON}" \
  --quiet

RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"

if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  echo "==> reconciling Scheduler trigger '$SCHEDULER_JOB'"
  VERB="update"
else
  echo "==> creating Scheduler trigger '$SCHEDULER_JOB'"
  VERB="create"
fi
gcloud scheduler jobs "$VERB" http "$SCHEDULER_JOB" \
  --location "$REGION" \
  --project "$PROJECT" \
  --schedule "$SCHEDULE" \
  --time-zone "$TIMEZONE" \
  --uri "$RUN_URI" \
  --http-method POST \
  --oauth-service-account-email "$SERVICE_ACCOUNT" \
  --quiet

echo
echo "==> done. Next run:"
gcloud scheduler jobs describe "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT" \
  --format="value(schedule, timeZone, scheduleTime)"
echo
echo "Alert policies for this job live in jobs/deploy-alerts.sh — run it next."
echo "To prove the alert fires: jobs/deploy-watch-disconnects.sh --drill"
