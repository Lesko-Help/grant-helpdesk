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

# Fridays at 08:17. Not 08:00: every scheduler in every project fires on the
# hour. Europe/Brussels to match the sibling triggers in this project.
SCHEDULE="${SCHEDULE:-17 8 * * 5}"
TIMEZONE="${TIMEZONE:-Europe/Brussels}"
SCHEDULER_JOB="${SCHEDULER_JOB:-${JOB}-weekly}"

WINDOW_DAYS="${WINDOW_DAYS:-7}"
# Must match .streamlit/config.toml's server.disconnectedSessionTTL — it is
# the line between "she saw a flicker" and "she lost her screen".
TTL_SECONDS="${TTL_SECONDS:-1800}"
MAX_RESETS_PER_DAY="${MAX_RESETS_PER_DAY:-5}"
# One guaranteed review mail: the first scheduled run (2026-10-23) reports
# whatever the numbers say, then the job falls back to threshold-only on its
# own. A date, not a flag, so nobody has to remember to switch it off.
REPORT_ALWAYS_UNTIL="${REPORT_ALWAYS_UNTIL:-2026-10-24}"

if [ "${1:-}" = "--drill" ]; then
  cat <<DRILL

Break it on purpose (global CLAUDE.md rule 5), then check the mail arrived:

  gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait \\
      --args="--max-resets-per-day,0"

  A threshold of 0 makes any lost session at all cross the line, so a real run
  over real data raises a real BTB_ALERT SESSION_LOST line. Nothing is faked
  and nothing is left behind: the job's own env still says
  MAX_RESETS_PER_DAY=$MAX_RESETS_PER_DAY on the next scheduled run.

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
  --set-env-vars "PROJECT=${PROJECT},SERVICE=${SERVICE},WINDOW_DAYS=${WINDOW_DAYS},TTL_SECONDS=${TTL_SECONDS},MAX_RESETS_PER_DAY=${MAX_RESETS_PER_DAY},REPORT_ALWAYS_UNTIL=${REPORT_ALWAYS_UNTIL}" \
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
