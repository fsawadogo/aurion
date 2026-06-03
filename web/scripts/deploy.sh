#!/usr/bin/env bash
# =============================================================================
# Aurion web portal — local Amplify deploy (DEPLOY-WEB)
# =============================================================================
# Workstation equivalent of the deploy job in .github/workflows/web.yml.
# Use after `aws sso login` (or with any creds that grant amplify:*)
# when you need to push a fix without going through CI.
#
# Usage:
#   bash web/scripts/deploy.sh <APP_ID>
#   AMPLIFY_APP_ID=<APP_ID> bash web/scripts/deploy.sh
#
# Get the app ID from terraform output:
#   cd infrastructure && terraform output -raw amplify_app_id
#
# Prerequisites:
#   - aws CLI v2 with creds for the dev account
#   - jq
#   - The static bundle built locally: `cd web && npm run build`
#
# Notes:
#   - The script assumes you ran `npm run build` in web/ first.
#     It does NOT trigger the build itself — keeps the script
#     focused on the deploy step + avoids a costly accidental rebuild.
#   - Amplify processes the bundle asynchronously after
#     start-deployment returns. The script prints the console URL
#     so you can watch progress; it does NOT block.

set -euo pipefail

# -----------------------------------------------------------------------------
# Args + env
# -----------------------------------------------------------------------------

APP_ID="${1:-${AMPLIFY_APP_ID:-}}"
BRANCH="${AMPLIFY_BRANCH:-main}"
AWS_REGION="${AWS_REGION:-ca-central-1}"

if [[ -z "$APP_ID" ]]; then
  echo "error: Amplify app ID required" >&2
  echo "  bash web/scripts/deploy.sh <APP_ID>" >&2
  echo "  or set AMPLIFY_APP_ID env var" >&2
  echo "" >&2
  echo "Get it from terraform:" >&2
  echo "  cd infrastructure && terraform output -raw amplify_app_id" >&2
  exit 1
fi

# Resolve repo root + the out/ directory. The script can be invoked
# from anywhere; resolve relative to its own location.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$WEB_DIR/out"
ZIP_PATH="$WEB_DIR/out.zip"

if [[ ! -d "$OUT_DIR" ]]; then
  echo "error: $OUT_DIR is missing. Run \`cd web && npm run build\` first." >&2
  exit 1
fi

if [[ ! -f "$OUT_DIR/index.html" ]]; then
  echo "error: $OUT_DIR/index.html not found — the build looks empty." >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# Sanity checks
# -----------------------------------------------------------------------------

command -v aws >/dev/null || { echo "error: aws CLI not on PATH" >&2; exit 1; }
command -v jq >/dev/null || { echo "error: jq not on PATH" >&2; exit 1; }

aws sts get-caller-identity --output text >/dev/null || {
  echo "error: AWS credentials not configured. Run \`aws sso login\` first." >&2
  exit 1
}

# -----------------------------------------------------------------------------
# Build the zip
# -----------------------------------------------------------------------------

echo "Zipping $OUT_DIR → $ZIP_PATH"
rm -f "$ZIP_PATH"
# Run inside $OUT_DIR so paths in the zip are relative to the bundle
# root — Amplify unpacks at the branch root, so index.html etc. land
# where it expects.
(cd "$OUT_DIR" && zip -qr "$ZIP_PATH" .)
ls -lh "$ZIP_PATH"

# -----------------------------------------------------------------------------
# Create + start the deployment
# -----------------------------------------------------------------------------

echo "Creating deployment slot for app $APP_ID / branch $BRANCH..."
RESP=$(aws amplify create-deployment \
  --region "$AWS_REGION" \
  --app-id "$APP_ID" \
  --branch-name "$BRANCH" \
  --output json)

JOB_ID=$(echo "$RESP" | jq -r '.jobId')
ZIP_URL=$(echo "$RESP" | jq -r '.zipUploadUrl')
echo "  job $JOB_ID created"

echo "Uploading bundle to pre-signed URL..."
curl --fail --silent --show-error \
  -X PUT \
  -H 'Content-Type: application/zip' \
  --upload-file "$ZIP_PATH" \
  "$ZIP_URL"
echo "  upload complete"

echo "Starting deployment..."
aws amplify start-deployment \
  --region "$AWS_REGION" \
  --app-id "$APP_ID" \
  --branch-name "$BRANCH" \
  --job-id "$JOB_ID" \
  --output text \
  --query 'jobSummary.status'

echo ""
echo "Deployment $JOB_ID started for $APP_ID branch $BRANCH"
echo "Console URL:"
echo "  https://$AWS_REGION.console.aws.amazon.com/amplify/apps/$APP_ID/branches/$BRANCH"
