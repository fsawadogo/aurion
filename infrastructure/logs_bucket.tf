# =============================================================================
# Audit Log Bucket — central destination for CloudTrail / VPC Flow Logs /
# S3 access logs.
# =============================================================================
# Phase 4 of the production rollout. Single bucket so the compliance
# officer / SOC2 auditor has one place to look. Bucket lives next to
# the PHI buckets but holds no PHI itself — only AWS API audit, network
# flows, and access logs from the PHI buckets.
#
# Retention: 7 years (Quebec Law 25 + medical-records keep-clear).
# Lifecycle moves objects to Glacier after 90d to control cost.

resource "aws_s3_bucket" "audit_logs" {
  bucket = "aurion-audit-logs-${var.environment}-${data.aws_caller_identity.current.account_id}"

  # Same hard guard the state bucket has — terraform destroy can't wipe
  # an audit-log bucket. Manual move-and-recreate is the only path.
  force_destroy = false

  tags = {
    Name               = "aurion-audit-logs-${var.environment}"
    DataClassification = "audit"
  }
}

resource "aws_s3_bucket_versioning" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "audit_logs" {
  bucket                  = aws_s3_bucket.audit_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  rule {
    id     = "glacier-after-90d-expire-after-7y"
    status = "Enabled"
    filter {}

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      # 2555 days ≈ 7 years — matches Quebec medical-records retention.
      days = 2555
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Bucket policy: deny non-TLS + grant the three log delivery services
# (CloudTrail, VPC Flow Logs, S3 logging service principal) write access
# to their respective prefixes.
resource "aws_s3_bucket_policy" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.audit_logs.arn,
          "${aws_s3_bucket.audit_logs.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
      # CloudTrail control-plane — needs to verify the bucket ACL +
      # write objects under cloudtrail/ prefix.
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.audit_logs.arn
      },
      {
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.audit_logs.arn}/cloudtrail/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" }
        }
      },
      # VPC Flow Logs delivery service (service-principal pattern is
      # different — uses delivery.logs.amazonaws.com, NOT vpc-flow-logs).
      {
        Sid       = "AWSLogDeliveryWrite"
        Effect    = "Allow"
        Principal = { Service = "delivery.logs.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.audit_logs.arn}/flowlogs/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" }
        }
      },
      {
        Sid       = "AWSLogDeliveryAclCheck"
        Effect    = "Allow"
        Principal = { Service = "delivery.logs.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.audit_logs.arn
      },
      # S3 server-access-logging — the logging principal needs PutObject
      # under the s3-access/ prefix. Used by the audio/frames/eval bucket
      # logging configs.
      {
        Sid       = "AWSS3LogDelivery"
        Effect    = "Allow"
        Principal = { Service = "logging.s3.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.audit_logs.arn}/s3-access/*"
        Condition = {
          ArnLike = {
            "aws:SourceArn" = "arn:aws:s3:::aurion-*-${var.environment}-${data.aws_caller_identity.current.account_id}"
          }
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
    ]
  })
}
