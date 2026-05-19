# =============================================================================
# KMS Key — encrypts the Terraform state objects in S3
# =============================================================================
# Dedicated key, not the main app KMS key. Rationale: the state bucket should
# survive (or be recoverable) even if the main module's KMS key were ever
# accidentally scheduled for deletion. Keeping them separate avoids that
# tight-coupling failure mode.

resource "aws_kms_key" "state" {
  description             = "Aurion — encrypts Terraform remote state objects"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name = "aurion-terraform-state-key"
  }
}

resource "aws_kms_alias" "state" {
  name          = local.kms_alias_name
  target_key_id = aws_kms_key.state.key_id
}

# =============================================================================
# S3 Bucket — Terraform remote state
# =============================================================================

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket

  # `force_destroy = false` — even in a teardown, we won't let `terraform
  # destroy` blindly empty + delete this bucket. State has to be moved off
  # by hand first. Same protection pattern as `deletion_protection` on RDS.
  force_destroy = false

  tags = {
    Name = local.state_bucket
  }
}

# Versioning ENABLED on the state bucket. Note this diverges from the app-
# data buckets (audio / frames) which have versioning explicitly DISABLED
# per CLAUDE.md — those carry PHI and versioning would create undeleteable
# PHI copies. The state bucket carries no PHI; versioning is a recovery
# net for "I applied something terrible, roll back the state file."
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Belt-and-suspenders bucket policy: deny any request that isn't TLS.
# Public-access-block already blocks anonymous access; this denies even
# authenticated requests that downgrade to HTTP. Matches the standard
# AWS Foundational Security Best Practices control S3.5.
resource "aws_s3_bucket_policy" "state_tls_only" {
  bucket = aws_s3_bucket.state.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.state.arn,
          "${aws_s3_bucket.state.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

# Expire old non-current versions to keep bucket size predictable.
# A 90-day window is long enough to recover from a bad apply that wasn't
# noticed for a sprint, short enough not to balloon storage costs.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    # Clean up failed multipart uploads (e.g. from interrupted applies).
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# =============================================================================
# DynamoDB — Terraform state lock table
# =============================================================================
# Terraform writes a row keyed by LockID when `terraform plan/apply` runs,
# deletes it when the operation finishes. Pay-per-request because the
# request rate is "occasional human" — provisioned capacity would be waste.

resource "aws_dynamodb_table" "locks" {
  name         = local.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  # PITR isn't necessary — locks are ephemeral and the cost outweighs the
  # benefit. If a lock somehow corrupts, `terraform force-unlock` is the
  # recovery path.

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.state.arn
  }

  # Reject deletion outside of an explicit teardown. Same guard rail as
  # the bucket: locks have to be moved off-table by hand first.
  deletion_protection_enabled = true

  tags = {
    Name = local.lock_table
  }
}
