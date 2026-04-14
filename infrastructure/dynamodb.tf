# =============================================================================
# DynamoDB — Immutable Audit Log
# =============================================================================
# Append-only audit trail for all session lifecycle events, AI provider calls,
# PHI masking status, config changes, and purge confirmations.
# No update or delete operations are permitted at the application layer.
# =============================================================================

resource "aws_dynamodb_table" "audit_log" {
  name         = "aurion-audit-log-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"

  # Partition key: session_id groups all events for a single session
  hash_key = "session_id"

  # Sort key: event_timestamp orders events chronologically within a session
  range_key = "event_timestamp"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "event_timestamp"
    type = "S"
  }

  # Point-in-time recovery — required for compliance. Enables restoration to
  # any second within the last 35 days if data corruption occurs.
  point_in_time_recovery {
    enabled = true
  }

  # Encryption — customer-managed KMS key
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.main.arn
  }

  # Deletion protection for prod
  deletion_protection_enabled = var.environment == "prod"

  tags = {
    Name = "aurion-audit-log-${var.environment}"
  }
}
