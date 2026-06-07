# =============================================================================
# S3 Buckets — Audio, Frames, Eval
# =============================================================================
# All buckets use KMS encryption, block all public access, enforce SSL,
# and have versioning disabled (as specified in CLAUDE.md).
# =============================================================================

# -----------------------------------------------------------------------------
# KMS Key — Shared encryption key for all Aurion resources
# -----------------------------------------------------------------------------

resource "aws_kms_key" "main" {
  description             = "Aurion ${var.environment} encryption key for S3, RDS, DynamoDB, and audit services"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  # Key policy — account root + service-principal grants for CloudTrail
  # (encrypt log files) and CloudWatch Logs (when we add log streaming
  # later). Without this, those services can't use the key even though
  # the IAM identity has decrypt rights on it.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableIAMUserPermissions"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudTrailEncrypt"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action = [
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
        ]
        Resource = "*"
        Condition = {
          StringLike = {
            "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:aws:cloudtrail:*:${data.aws_caller_identity.current.account_id}:trail/*"
          }
        }
      },
    ]
  })

  tags = {
    Name = "aurion-key-${var.environment}"
  }
}

resource "aws_kms_alias" "main" {
  name          = "alias/aurion-key-${var.environment}"
  target_key_id = aws_kms_key.main.key_id
}

# =============================================================================
# Audio Bucket — Raw audio uploads, 1-day TTL
# =============================================================================

resource "aws_s3_bucket" "audio" {
  bucket        = "aurion-audio-${var.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment == "dev"

  tags = {
    Name = "aurion-audio-${var.environment}"
  }
}

resource "aws_s3_bucket_versioning" "audio" {
  bucket = aws_s3_bucket.audio.id
  versioning_configuration {
    status = "Disabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "audio" {
  bucket = aws_s3_bucket.audio.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id

  rule {
    id     = "expire-audio"
    status = "Enabled"

    filter {}

    expiration {
      days = var.media_retention_days
    }
  }
}

resource "aws_s3_bucket_policy" "audio_ssl" {
  bucket = aws_s3_bucket.audio.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceSSL"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.audio.arn,
          "${aws_s3_bucket.audio.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# =============================================================================
# Frames Bucket — Masked video/screen frames, 1-day TTL
# =============================================================================

resource "aws_s3_bucket" "frames" {
  bucket        = "aurion-frames-${var.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment == "dev"

  tags = {
    Name = "aurion-frames-${var.environment}"
  }
}

resource "aws_s3_bucket_versioning" "frames" {
  bucket = aws_s3_bucket.frames.id
  versioning_configuration {
    status = "Disabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frames" {
  bucket = aws_s3_bucket.frames.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "frames" {
  bucket = aws_s3_bucket.frames.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "frames" {
  bucket = aws_s3_bucket.frames.id

  rule {
    id     = "expire-frames"
    status = "Enabled"

    filter {}

    expiration {
      days = var.media_retention_days
    }
  }
}

resource "aws_s3_bucket_policy" "frames_ssl" {
  bucket = aws_s3_bucket.frames.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceSSL"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.frames.arn,
          "${aws_s3_bucket.frames.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# =============================================================================
# Eval Bucket — Evaluation frames, no expiration, restricted access
# =============================================================================

resource "aws_s3_bucket" "eval" {
  bucket        = "aurion-eval-${var.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment == "dev"

  tags = {
    Name = "aurion-eval-${var.environment}"
  }
}

resource "aws_s3_bucket_versioning" "eval" {
  bucket = aws_s3_bucket.eval.id
  versioning_configuration {
    status = "Disabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "eval" {
  bucket = aws_s3_bucket.eval.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "eval" {
  bucket = aws_s3_bucket.eval.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# No lifecycle rule — eval data is retained indefinitely

resource "aws_s3_bucket_policy" "eval_ssl" {
  bucket = aws_s3_bucket.eval.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceSSL"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.eval.arn,
          "${aws_s3_bucket.eval.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# =============================================================================
# Access logging on the 3 PHI buckets (Phase 4)
# =============================================================================
# Every GET / PUT on audio/frames/eval lands a log line in the audit
# bucket. Catches the "who downloaded what" question that DSAR + breach
# investigations need to answer.
#
# Destination is the central audit bucket; prefix segregates per-source.

resource "aws_s3_bucket_logging" "audio" {
  bucket        = aws_s3_bucket.audio.id
  target_bucket = aws_s3_bucket.audit_logs.id
  target_prefix = "s3-access/audio/"
}

resource "aws_s3_bucket_logging" "frames" {
  bucket        = aws_s3_bucket.frames.id
  target_bucket = aws_s3_bucket.audit_logs.id
  target_prefix = "s3-access/frames/"
}

resource "aws_s3_bucket_logging" "eval" {
  bucket        = aws_s3_bucket.eval.id
  target_bucket = aws_s3_bucket.audit_logs.id
  target_prefix = "s3-access/eval/"
}
