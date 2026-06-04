# =============================================================================
# Secrets Manager — Provider API Keys
# =============================================================================
# CLAUDE.md (Phase 8 + Non-Negotiable Technical Rules) requires every provider
# API key to live in Secrets Manager — never in environment variables, .env
# files, or code. The ECS task execution role already has permission to read
# any `aurion/*` secret (see ecs.tf — aws_iam_role_policy.ecs_exec_secrets).
#
# Secret values are NOT stored in Terraform state. The `secret_version`
# resources below seed each secret with the literal string "PLACEHOLDER —
# set via console" so apply succeeds on a fresh account; the operator rotates
# the real key in via:
#
#   aws secretsmanager put-secret-value \
#     --secret-id aurion/$ENV/openai-api-key \
#     --secret-string "$(op read 'op://Aurion/OpenAI API Key/credential')"
#
# `lifecycle.ignore_changes = [secret_string]` prevents Terraform from
# overwriting the rotated value on subsequent applies.
# =============================================================================

locals {
  provider_secrets = {
    openai     = "OpenAI API key — note generation and vision providers"
    anthropic  = "Anthropic API key — Claude note generation and vision providers"
    google_ai  = "Google AI API key — Gemini note generation and vision providers"
    assemblyai = "AssemblyAI API key — transcription provider (Whisper alternative)"
  }
}

resource "aws_secretsmanager_secret" "provider_api_key" {
  for_each = local.provider_secrets

  name        = "aurion/${var.environment}/${replace(each.key, "_", "-")}-api-key"
  description = each.value
  kms_key_id  = aws_kms_key.main.id

  # 7-day recovery window in dev for fast rebuild; 30-day in prod for safety.
  recovery_window_in_days = var.environment == "prod" ? 30 : 7

  tags = {
    Name        = "aurion-${each.key}-key-${var.environment}"
    Provider    = each.key
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "provider_api_key" {
  for_each = local.provider_secrets

  secret_id     = aws_secretsmanager_secret.provider_api_key[each.key].id
  secret_string = "PLACEHOLDER - set via 'aws secretsmanager put-secret-value'"

  lifecycle {
    # The real key is rotated in via console / CLI / 1Password integration.
    # Terraform must not clobber it on the next apply.
    ignore_changes = [secret_string]
  }
}

# -----------------------------------------------------------------------------
# Outputs — secret ARNs for the ECS task definition (see ecs.tf)
# -----------------------------------------------------------------------------

output "secret_arn_openai_api_key" {
  description = "ARN of the OpenAI API key secret"
  value       = aws_secretsmanager_secret.provider_api_key["openai"].arn
}

output "secret_arn_anthropic_api_key" {
  description = "ARN of the Anthropic API key secret"
  value       = aws_secretsmanager_secret.provider_api_key["anthropic"].arn
}

output "secret_arn_google_ai_api_key" {
  description = "ARN of the Google AI (Gemini) API key secret"
  value       = aws_secretsmanager_secret.provider_api_key["google_ai"].arn
}

output "secret_arn_assemblyai_api_key" {
  description = "ARN of the AssemblyAI API key secret"
  value       = aws_secretsmanager_secret.provider_api_key["assemblyai"].arn
}

# -----------------------------------------------------------------------------
# Patient identifier HMAC key (#61, full slice)
# -----------------------------------------------------------------------------
# Backs `app/core/identifier_hash.py`. The new
# `sessions.external_reference_id_hash` column (Alembic 0027) stores an
# HMAC-SHA256 of the patient identifier so the per-physician prior-
# encounters lookup can hit an indexed equality predicate. The key MUST
# be a 32-byte secret; the placeholder below ships as a literal string so
# `terraform apply` succeeds on a fresh account. Operator rotates the
# real key in via:
#
#   aws secretsmanager put-secret-value \
#     --secret-id aurion/$ENV/identifier-hmac-key \
#     --secret-string "$(openssl rand -base64 32)"
#
# `lifecycle.ignore_changes = [secret_string]` prevents Terraform from
# clobbering the rotated value on subsequent applies, same pattern as
# the provider API keys above.
#
# Rotating the key is a breaking change for the indexed lookup: every
# hash in the DB becomes incomparable until back-filled. A dual-write
# rotation window is deferred to a future PR; for the pilot the single
# key is set once and left alone.

resource "aws_secretsmanager_secret" "identifier_hmac_key" {
  name        = "aurion/${var.environment}/identifier-hmac-key"
  description = "HMAC-SHA256 key for the deterministic patient identifier hash column (#61). 32 random bytes, base64-encoded."
  kms_key_id  = aws_kms_key.main.id

  recovery_window_in_days = var.environment == "prod" ? 30 : 7

  tags = {
    Name        = "aurion-identifier-hmac-key-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "identifier_hmac_key" {
  secret_id     = aws_secretsmanager_secret.identifier_hmac_key.id
  secret_string = "PLACEHOLDER - rotate via 'openssl rand -base64 32 | aws secretsmanager put-secret-value'"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

output "secret_arn_identifier_hmac_key" {
  description = "ARN of the patient identifier HMAC key secret"
  value       = aws_secretsmanager_secret.identifier_hmac_key.arn
}
