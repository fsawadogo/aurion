# =============================================================================
# CloudTrail — audit trail for every AWS API call
# =============================================================================
# Phase 4 of the production rollout. Required for Quebec Law 25 breach
# notification readiness (SOC2 CC6.1, CC7.2 control), HIPAA Security
# Rule §164.312(b) — and just plain good practice. Without CloudTrail we
# have no record of who did what at the AWS API level.
#
# Single multi-region trail writing to the audit bucket. log_file_validation
# = true means CloudTrail produces a digest file so tampering with the
# log objects can be detected post-hoc.

resource "aws_cloudtrail" "main" {
  name           = "aurion-${var.environment}"
  s3_bucket_name = aws_s3_bucket.audit_logs.id
  s3_key_prefix  = "cloudtrail"

  # Capture API events from every region — even though we only deploy
  # in ca-central-1, an attacker spinning up resources in another region
  # would otherwise go unrecorded.
  is_multi_region_trail = true

  # Global service events (IAM, Cognito, CloudFront, Route 53) only
  # appear in us-east-1. include_global_service_events captures them
  # in the trail anyway.
  include_global_service_events = true

  enable_logging = true

  # Digest file — daily-rolled SHA-256 of the day's log objects. Lets
  # the auditor verify nothing was retroactively edited.
  enable_log_file_validation = true

  # Encrypt log objects with the main KMS key. AWS will use a default
  # AES-256 encryption otherwise; KMS gives us audit + rotation.
  kms_key_id = aws_kms_key.main.arn

  tags = {
    Name = "aurion-cloudtrail-${var.environment}"
  }

  # CloudTrail validates the bucket policy at create time; depend on it
  # explicitly so apply order is right.
  depends_on = [aws_s3_bucket_policy.audit_logs]
}
