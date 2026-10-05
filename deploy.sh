#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Grant Helpdesk — Deploy Script
#
# Usage:  ./deploy.sh
#
# What it does:
#   1. Runs smoke tests against live BigQuery
#   2. If any test fails → stops here, nothing is deployed
#   3. If all tests pass → deploys to Cloud Run (europe-west1)
#   4. Prints the live URL when done
#
# ─────────────────────────────────────────────────────────────────────────────

set -e  # Stop immediately if any command fails

PROJECT="bigtribebuilders"
REGION="europe-west1"
SERVICE="grant-helpdesk"
APP_URL="https://grant-helpdesk-170880920649.europe-west1.run.app"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Grant Helpdesk — Deploy"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: Smoke tests ───────────────────────────────────────────────────────
echo "🧪  Running smoke tests..."
echo ""

cd "$(dirname "$0")"  # always run from the project root

if LIVE_SMOKE=1 python3 -m pytest tests/ -v --tb=short; then
    echo ""
    echo "✅  All tests passed."
else
    echo ""
    echo "❌  Tests failed — deploy cancelled."
    echo "    Fix the failing tests before deploying."
    echo ""
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Step 2: Deploy to Cloud Run ───────────────────────────────────────────────
echo ""
echo "🚀  Deploying to Cloud Run..."
echo "    Project : $PROJECT"
echo "    Region  : $REGION"
echo "    Service : $SERVICE"
echo ""

gcloud run deploy "$SERVICE" \
    --source . \
    --region "$REGION" \
    --project "$PROJECT" \
    --quiet

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅  Deploy complete."
echo "    $APP_URL"
echo ""
