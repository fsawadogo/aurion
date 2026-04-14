---
name: localstack-setup
description: >
  Load when setting up local development, writing docker-compose.yml, creating
  the LocalStack init script, configuring .env, or debugging local stack issues.
  Contains complete docker-compose.yml, LocalStack setup.sh init script,
  .env.example, first-time setup commands, full pipeline test script, and
  common issues table. Auto-invoked when editing docker-compose.yml,
  scripts/localstack-init/, or .env.example.
user-invocable: true
---

# Aurion LocalStack and Local Development Setup

## Architecture

Everything testable locally before any cloud deployment. No AWS account needed for backend development.

| Service | Port | What It Is |
|---|---|---|
| `aurion-api` | 8000 | FastAPI application — full backend |
| `postgres` | 5432 | PostgreSQL — session metadata, notes, pilot metrics |
| `localstack` | 4566 | AWS emulation — S3, DynamoDB, AppConfig, Cognito, KMS, Textract |
| `whisper` | 8001 | Whisper v3 — real transcription locally (CPU mode) |
| `mailhog` | 8025 | Email catcher — web UI at localhost:8025 |

Web portal runs separately: `cd web && npm run dev` → `localhost:3000`

---

## `docker-compose.yml` — Generate Exactly This File

**Path:** `backend/docker-compose.yml`

```yaml
version: "3.9"

services:

  # ── FastAPI Backend ──────────────────────────────────────────────────────
  aurion-api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: aurion-api
    ports:
      - "8000:8000"
    environment:
      - APP_ENV=local
      - LOG_LEVEL=DEBUG
      - DATABASE_URL=postgresql+asyncpg://aurion:aurion@postgres:5432/aurion
      - AWS_ACCESS_KEY_ID=test
      - AWS_SECRET_ACCESS_KEY=test
      - AWS_DEFAULT_REGION=ca-central-1
      - AWS_ENDPOINT_URL=http://localstack:4566
      - COGNITO_USER_POOL_ID=local_pool
      - COGNITO_CLIENT_ID=local_client
      - WHISPER_API_URL=http://whisper:8001
      - SCREEN_OCR_LOCAL_MODE=true
    env_file:
      - .env                          # AI provider keys loaded from here
    volumes:
      - ./app:/app/app                # Hot reload — code changes apply instantly
    depends_on:
      postgres:
        condition: service_healthy
      localstack:
        condition: service_healthy
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  # ── PostgreSQL ───────────────────────────────────────────────────────────
  postgres:
    image: postgres:15-alpine
    container_name: aurion-postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: aurion
      POSTGRES_PASSWORD: aurion
      POSTGRES_DB: aurion
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U aurion"]
      interval: 5s
      timeout: 5s
      retries: 10

  # ── LocalStack — AWS Emulation ───────────────────────────────────────────
  localstack:
    image: localstack/localstack:latest
    container_name: aurion-localstack
    ports:
      - "4566:4566"
    environment:
      - SERVICES=s3,dynamodb,appconfig,cognito-idp,kms,textract,secretsmanager
      - DEFAULT_REGION=ca-central-1
      - DOCKER_HOST=unix:///var/run/docker.sock
      - LOCALSTACK_AUTH_TOKEN=${LOCALSTACK_AUTH_TOKEN:-}
    volumes:
      - ./scripts/localstack-init:/etc/localstack/init/ready.d
      - localstack_data:/var/lib/localstack
      - /var/run/docker.sock:/var/run/docker.sock
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4566/_localstack/health"]
      interval: 10s
      timeout: 5s
      retries: 15
      start_period: 30s

  # ── Whisper Transcription ────────────────────────────────────────────────
  whisper:
    image: onerahmet/openai-whisper-asr-webservice:latest
    container_name: aurion-whisper
    ports:
      - "8001:9000"
    environment:
      - ASR_MODEL=base           # 'base' for local speed. 'large-v3' for accuracy testing.
      - ASR_ENGINE=openai_whisper
    # Uncomment for NVIDIA GPU:
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1
    #           capabilities: [gpu]

  # ── Mailhog — Email Catcher ──────────────────────────────────────────────
  mailhog:
    image: mailhog/mailhog
    container_name: aurion-mailhog
    ports:
      - "1025:1025"   # SMTP
      - "8025:8025"   # Web UI

volumes:
  postgres_data:
  localstack_data:
```

---

## LocalStack Init Script — Generate Exactly This File

**Path:** `backend/scripts/localstack-init/setup.sh`

Runs automatically every time LocalStack starts. Creates all AWS resources the backend expects.

```bash
#!/bin/bash
set -e

echo "==> Aurion LocalStack init starting..."

# ── S3 Buckets ───────────────────────────────────────────────────────────────
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

# ── AppConfig ────────────────────────────────────────────────────────────────
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

# ── Cognito User Pool ─────────────────────────────────────────────────────────
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

# ── KMS Key ───────────────────────────────────────────────────────────────────
echo "--> Creating KMS key..."
awslocal kms create-key --description "Aurion local dev encryption key" \
  --query "KeyMetadata.KeyId" --output text

# ── Secrets Manager ───────────────────────────────────────────────────────────
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
```

```bash
chmod +x backend/scripts/localstack-init/setup.sh
```

---

## `.env.example` — Copy to `.env` Before Starting

```bash
# AI Providers — real API keys, called from your local machine
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_AI_API_KEY=...
ASSEMBLYAI_API_KEY=...

# Provider selection — overrides AppConfig in local dev
AURION_PROVIDER_TRANSCRIPTION=whisper
AURION_PROVIDER_NOTE_GENERATION=anthropic
AURION_PROVIDER_VISION=openai

# LocalStack — fixed values (always test/test)
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_DEFAULT_REGION=ca-central-1
AWS_ENDPOINT_URL=http://localhost:4566

# Database
DATABASE_URL=postgresql+asyncpg://aurion:aurion@localhost:5432/aurion

# Cognito — mocked locally
COGNITO_USER_POOL_ID=local_pool
COGNITO_CLIENT_ID=local_client

# App
APP_ENV=local
LOG_LEVEL=DEBUG
SCREEN_OCR_LOCAL_MODE=true   # Returns fixture data instead of calling Textract
```

**Never commit `.env` to git.**

---

## First-Time Setup

```bash
# 1. Copy env file and add real AI provider keys
cp backend/.env.example backend/.env

# 2. Start all services
cd backend && docker-compose up -d

# 3. Wait for LocalStack (~20–30 seconds)
curl http://localhost:4566/_localstack/health

# 4. Seed dev data
python scripts/seed_dev.py

# 5. Verify
curl http://localhost:8000/health
# Returns: {"status": "ok", "version": "0.1.0", "providers": {...}}

# 6. Open API docs
open http://localhost:8000/docs
```

---

## Seed Script — `backend/scripts/seed_dev.py`

Creates:
- Dev clinician user (`clinician@aurion.local`, role: CLINICIAN)
- Eval team user (`eval@aurion.local`, role: EVAL_TEAM)
- Admin user (`admin@aurion.local`, role: ADMIN)
- Compliance user (`compliance@aurion.local`, role: COMPLIANCE_OFFICER)
- All 5 specialty templates in DB (empty `visual_trigger_keywords`)
- Default AppConfig document loaded into LocalStack

---

## Switching Providers Locally

**Via `.env` (restart required):**
```bash
AURION_PROVIDER_NOTE_GENERATION=gemini
docker-compose restart aurion-api
```

**Via AppConfig in LocalStack (no restart — 30s polling):**
```bash
awslocal appconfig put-configuration \
  --application aurion --environment local \
  --configuration '{"providers": {"note_generation": "gemini"}}'
```

**Via Admin API (immediate):**
```bash
curl -X PATCH http://localhost:8000/api/v1/admin/config/providers \
  -H "Authorization: Bearer <dev_token>" \
  -H "Content-Type: application/json" \
  -d '{"note_generation": "gemini"}'
```

---

## Full Pipeline Test Script — `backend/scripts/test_pipeline.py`

Runs complete session end-to-end using synthetic fixtures. No real patient data.

```
Fixtures in backend/scripts/fixtures/:
  sample_audio.wav         5-minute orthopedic consultation (synthetic)
  sample_frames/           10 masked clinical frames (synthetic)
  sample_screen_lab.png    Synthetic lab result screen
  sample_screen_imaging.png  Synthetic imaging viewer screen

Steps:
  1.  POST /api/v1/sessions                    → Create session
  2.  POST /api/v1/sessions/{id}/consent       → Confirm consent
  3.  POST /api/v1/sessions/{id}/start         → Start recording
  4.  POST /api/v1/sessions/{id}/stop          → Stop recording
  5.  POST /api/v1/transcription/{id}          → Submit audio → Whisper
  6.  GET  /api/v1/notes/{id}/stage1           → Receive Stage 1 draft
  7.  POST /api/v1/notes/{id}/approve-stage1   → Approve Stage 1
  8.  POST /api/v1/vision/{id}                 → Submit frames → vision provider
  9.  GET  /api/v1/notes/{id}/full             → Receive full note
  10. POST /api/v1/notes/{id}/approve          → Final approval
  11. POST /api/v1/notes/{id}/export           → Export DOCX → cleanup triggered
  12. GET  /api/v1/audit/{id}                  → Verify complete audit trail
```

---

## Test Structure

```
backend/tests/
├── unit/          # No external deps — mock everything
│   ├── test_session.py
│   ├── test_note_gen.py
│   ├── test_vision.py
│   ├── test_screen.py
│   ├── test_trigger_classifier.py
│   └── test_providers.py
├── integration/   # Requires docker-compose up
│   ├── test_transcription_pipeline.py
│   ├── test_audit_log.py
│   ├── test_s3_cleanup.py
│   └── test_appconfig.py
└── e2e/
    └── test_full_session.py
```

```bash
# Unit tests (no Docker needed)
cd backend && pytest tests/unit/ -v

# Integration tests (requires docker-compose up)
cd backend && pytest tests/integration/ -v

# Full pipeline
cd backend && pytest tests/e2e/ -v

# With coverage
cd backend && pytest --cov=app --cov-report=html tests/
```

---

## iOS Local Connection

```swift
// Config.swift
#if DEBUG
let apiBaseURL = "http://localhost:8000"
let wsBaseURL  = "ws://localhost:8000"
#else
let apiBaseURL = ProcessInfo.processInfo.environment["API_BASE_URL"] ?? ""
#endif
```

**Physical device on same WiFi:** use Mac's local IP instead of `localhost`.

---

## Common Issues

| Issue | Cause | Fix |
|---|---|---|
| LocalStack not ready | Slow startup | Wait 30s. Check `curl localhost:4566/_localstack/health` |
| AppConfig not updating | Polling interval | Wait 30s or use admin API |
| Whisper too slow | CPU mode | Set `AURION_PROVIDER_TRANSCRIPTION=assemblyai` locally for speed |
| iOS can't reach localhost | Not on same WiFi | Use Mac's local IP address |
| S3 bucket not found | Seed not run | Run `python scripts/seed_dev.py` |
| DB connection refused | Postgres not ready | Wait for `docker-compose ps` to show postgres as healthy |
| Textract not working | LocalStack Community | Set `SCREEN_OCR_LOCAL_MODE=true` to use fixture data |
| Plugin skill not appearing | Cache stale | `rm -rf ~/.claude/plugins/cache` then `/reload-plugins` |
