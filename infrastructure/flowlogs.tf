# =============================================================================
# VPC Flow Logs
# =============================================================================
# Phase 4 of the production rollout. Captures every IP-level connection
# in/out of the VPC for forensics. Required by SOC2 CC6.6 + a non-trivial
# input to any breach-notification investigation under Law 25.
#
# Destination: the audit bucket's flowlogs/ prefix. ALL traffic types
# (ACCEPT + REJECT). Aggregation interval: 60s (default; 10s available
# for ENA-enabled instances but we don't need that resolution).

resource "aws_flow_log" "vpc" {
  vpc_id                   = aws_vpc.main.id
  traffic_type             = "ALL"
  log_destination_type     = "s3"
  log_destination          = "${aws_s3_bucket.audit_logs.arn}/flowlogs"
  max_aggregation_interval = 60

  # Default format works fine for a single-VPC pilot. The flow-logs
  # service principal needs s3:PutObject under the flowlogs/ prefix —
  # granted in logs_bucket.tf.
  tags = {
    Name = "aurion-vpc-flowlogs-${var.environment}"
  }

  depends_on = [aws_s3_bucket_policy.audit_logs]
}
