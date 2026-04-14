#!/bin/bash
set -e

echo "==> Aurion LocalStack init starting..."

# ── S3 Buckets ──────────���────────────────────────────────────────────────────
echo "--> Creating S3 buckets..."

awslocal s3 mb s3://aurion-audio-local
awslocal s3 mb s3://aurion-frames-local
awslocal s3 mb s3://aurion-eval-local

awslocal s3api put-bucket-lifecycle-configuration \
  --bucket aurion-audio-local \
  --lifecycle-configuration '{
    "Rules": [{"ID": "expire-audio", "Status": "Enabled",
      "Expiration": {"Days": 1}, "Filter": {"Prefix": ""}}]
  }'

awslocal s3api put-bucket-lifecycle-configuration \
  --bucket aurion-frames-local \
  --lifecycle-configuration '{
    "Rules": [{"ID": "expire-frames", "Status": "Enabled",
      "Expiration": {"Days": 1}, "Filter": {"Prefix": ""}}]
  }'

echo "--> S3 buckets created."

# ── DynamoDB — Audit Log ─────────────────────────────────────────────────────
echo "--> Creating DynamoDB audit log table..."

awslocal dynamodb create-table \
  --table-name aurion-audit-log-local \
  --attribute-definitions \
    AttributeName=session_id,AttributeType=S \
    AttributeName=event_timestamp,AttributeType=S \
  --key-schema \
    AttributeName=session_id,KeyType=HASH \
    AttributeName=event_timestamp,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region ca-central-1

echo "--> DynamoDB table created."

# ── AppConfig ──────────���───────────────────────────��─────────────────────────
echo "--> Creating AppConfig..."

APP_ID=$(awslocal appconfig create-application \
  --name aurion --query "Id" --output text)

ENV_ID=$(awslocal appconfig create-environment \
  --application-id "$APP_ID" --name local \
  --query "Id" --output text)

PROFILE_ID=$(awslocal appconfig create-configuration-profile \
  --application-id "$APP_ID" --name aurion-config \
  --location-uri hosted --query "Id" --output text)

CONFIG=$(cat <<'EOF'
{
  "providers": {
    "transcription": "whisper",
    "note_generation": "anthropic",
    "vision": "openai"
  },
  "model_params": {
    "note_generation": { "temperature": 0.1, "max_tokens": 2000 },
    "vision": { "temperature": 0.1, "max_tokens": 500, "confidence_threshold": "medium" }
  },
  "pipeline": {
    "stage1_skip_window_seconds": 60,
    "frame_window_clinic_ms": 3000,
    "frame_window_procedural_ms": 7000,
    "screen_capture_fps": 2,
    "video_capture_fps": 1
  },
  "feature_flags": {
    "screen_capture_enabled": true,
    "note_versioning_enabled": true,
    "session_pause_resume_enabled": true,
    "per_session_provider_override": true
  }
}
EOF
)

VERSION=$(awslocal appconfig create-hosted-configuration-version \
  --application-id "$APP_ID" \
  --configuration-profile-id "$PROFILE_ID" \
  --content-type "application/json" \
  --content "$CONFIG" \
  --query "VersionNumber" --output text)

awslocal appconfig start-deployment \
  --application-id "$APP_ID" \
  --environment-id "$ENV_ID" \
  --configuration-profile-id "$PROFILE_ID" \
  --configuration-version "$VERSION" \
  --deployment-strategy-id AppConfig.AllAtOnce

mkdir -p /tmp/aurion-config
echo "$APP_ID" > /tmp/aurion-config/app_id
echo "$ENV_ID" > /tmp/aurion-config/env_id
echo "$PROFILE_ID" > /tmp/aurion-config/profile_id

echo "--> AppConfig created. App ID: $APP_ID"

# ── Cognito User Pool ─────��─────────────────────��─────────────────────────────
echo "--> Creating Cognito user pool..."

POOL_ID=$(awslocal cognito-idp create-user-pool \
  --pool-name aurion-local --query "UserPool.Id" --output text)

CLIENT_ID=$(awslocal cognito-idp create-user-pool-client \
  --user-pool-id "$POOL_ID" \
  --client-name aurion-local-client \
  --no-generate-secret \
  --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH \
  --query "UserPoolClient.ClientId" --output text)

echo "--> Cognito pool: $POOL_ID | client: $CLIENT_ID"

# ── KMS Key ──────��───────────────────────────────��────────────────────────────
echo "--> Creating KMS key..."
awslocal kms create-key --description "Aurion local dev encryption key" \
  --query "KeyMetadata.KeyId" --output text

# ── Secrets Manager ──────────���─────────────────────────────��──────────────────
echo "--> Seeding Secrets Manager..."

awslocal secretsmanager create-secret \
  --name aurion/openai-api-key \
  --secret-string "${OPENAI_API_KEY:-placeholder}"

awslocal secretsmanager create-secret \
  --name aurion/anthropic-api-key \
  --secret-string "${ANTHROPIC_API_KEY:-placeholder}"

awslocal secretsmanager create-secret \
  --name aurion/google-ai-api-key \
  --secret-string "${GOOGLE_AI_API_KEY:-placeholder}"

awslocal secretsmanager create-secret \
  --name aurion/assemblyai-api-key \
  --secret-string "${ASSEMBLYAI_API_KEY:-placeholder}"

echo "==> Aurion LocalStack init complete."
echo "    S3:       aurion-audio-local, aurion-frames-local, aurion-eval-local"
echo "    DynamoDB: aurion-audit-log-local"
echo "    AppConfig: aurion / local (App ID: $APP_ID)"
echo "    Cognito:  $POOL_ID"
