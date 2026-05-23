# =============================================================================
# SNS — Alarm Routing
# =============================================================================
# Single topic that every CloudWatch alarm (operational + business) routes
# to. Email subscription for the pilot (one mailbox); pre-GA the recommended
# upgrade is a PagerDuty / Opsgenie HTTPS subscription so off-hours pages
# actually wake someone up.
#
# KMS-encrypted at rest with the main app key so audit logs of the publish
# events stay encrypted; CloudWatch's service principal has a key grant
# via the policy on the key itself (set by AWS by default for service-
# enrolled services).

resource "aws_sns_topic" "alerts" {
  name              = "aurion-alerts-${var.environment}"
  kms_master_key_id = aws_kms_key.main.id

  tags = {
    Name = "aurion-alerts-${var.environment}"
  }
}

# Topic policy — let CloudWatch publish alarms here. Without this, the
# alarm_actions wired in cloudwatch.tf would silently no-op (CloudWatch
# returns success but SNS rejects the message).
resource "aws_sns_topic_policy" "alerts_cloudwatch" {
  arn = aws_sns_topic.alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudWatchAlarmsToPublish"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.alerts.arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:cloudwatch:${var.region}:${data.aws_caller_identity.current.account_id}:alarm:*"
          }
        }
      }
    ]
  })
}

# Email subscription. AWS sends a confirmation email; the subscription
# stays in `pending_confirmation` until clicked. Until confirmed, alarms
# fire silently — this is the one manual step required to close the loop.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alerts_email

  # Don't recreate on every plan if the subscription is still pending
  # confirmation. Without this, terraform tries to delete + recreate
  # the unconfirmed sub every apply.
  lifecycle {
    ignore_changes = [confirmation_timeout_in_minutes]
  }
}
