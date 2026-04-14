# =============================================================================
# CloudWatch — Dashboard and Alarms
# =============================================================================
# Monitors the 4 critical operational metrics:
#   1. Stage 1 note generation latency (target < 60s)
#   2. PHI masking pipeline failures (target: zero)
#   3. Consent block failures (target: zero — hard safety requirement)
#   4. AI provider fallback events (early warning for provider instability)
# =============================================================================

locals {
  cw_namespace = "Aurion/${var.environment}"
}

# =============================================================================
# Dashboard
# =============================================================================

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "Aurion-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1: Latency metrics
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Stage 1 Latency (ms)"
          metrics = [["${local.cw_namespace}", "Stage1Latency", "Service", "note_gen", { stat = "Average", period = 300 }]]
          view    = "timeSeries"
          region  = var.region
          yAxis   = { left = { min = 0 } }
          annotations = {
            horizontal = [
              {
                label = "SLA threshold (60s)"
                value = 60000
                color = "#d62728"
              }
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Stage 2 Latency (ms)"
          metrics = [["${local.cw_namespace}", "Stage2Latency", "Service", "vision", { stat = "Average", period = 300 }]]
          view    = "timeSeries"
          region  = var.region
          yAxis   = { left = { min = 0 } }
        }
      },
      # Row 2: Safety metrics
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "Masking Pass Rate (%)"
          metrics = [["${local.cw_namespace}", "MaskingPassRate", "Service", "masking", { stat = "Average", period = 300 }]]
          view    = "timeSeries"
          region  = var.region
          yAxis   = { left = { min = 0, max = 100 } }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "API Error Rate"
          metrics = [["${local.cw_namespace}", "ErrorRate", "Service", "api", { stat = "Sum", period = 300 }]]
          view    = "timeSeries"
          region  = var.region
          yAxis   = { left = { min = 0 } }
        }
      },
      # Row 3: Operational indicators
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 8
        height = 4
        properties = {
          title   = "Provider Fallbacks (last hour)"
          metrics = [["${local.cw_namespace}", "ProviderFallbackTriggered", "Service", "providers", { stat = "Sum", period = 300 }]]
          view    = "singleValue"
          region  = var.region
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 12
        width  = 8
        height = 4
        properties = {
          title   = "Masking Failures (last hour)"
          metrics = [["${local.cw_namespace}", "MaskingPipelineFailure", "Service", "masking", { stat = "Sum", period = 60 }]]
          view    = "singleValue"
          region  = var.region
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 12
        width  = 8
        height = 4
        properties = {
          title   = "Consent Block Failures (last hour)"
          metrics = [["${local.cw_namespace}", "ConsentBlockFailure", "Service", "session", { stat = "Sum", period = 60 }]]
          view    = "singleValue"
          region  = var.region
        }
      }
    ]
  })
}

# =============================================================================
# Alarms
# =============================================================================

# -----------------------------------------------------------------------------
# Alarm 1: Stage 1 Latency > 60 seconds
# Fires when average note generation latency exceeds 60s for 3 consecutive
# 5-minute evaluation periods. This is the primary UX quality signal.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "stage1_latency" {
  alarm_name          = "aurion-${var.environment}-stage1-latency-high"
  alarm_description   = "Stage 1 note generation latency exceeds 60 seconds"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 60000 # 60 seconds in milliseconds
  treat_missing_data  = "notBreaching"

  namespace   = local.cw_namespace
  metric_name = "Stage1Latency"
  statistic   = "Average"
  period      = 300
  dimensions = {
    Service = "note_gen"
  }

  tags = {
    Name = "aurion-${var.environment}-stage1-latency-alarm"
  }
}

# -----------------------------------------------------------------------------
# Alarm 2: Masking Pipeline Failure
# Fires immediately on any masking failure. A single unmasked frame is a
# compliance incident — zero tolerance.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "masking_failure" {
  alarm_name          = "aurion-${var.environment}-masking-failure"
  alarm_description   = "Masking pipeline failure detected - unmasked frame may have been processed"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 1
  treat_missing_data  = "notBreaching"

  namespace   = local.cw_namespace
  metric_name = "MaskingPipelineFailure"
  statistic   = "Sum"
  period      = 60
  dimensions = {
    Service = "masking"
  }

  tags = {
    Name = "aurion-${var.environment}-masking-failure-alarm"
  }
}

# -----------------------------------------------------------------------------
# Alarm 3: Consent Block Failure
# Fires immediately if recording starts without confirmed consent. This is a
# hard safety requirement — consent_confirmed must be in audit log before any
# audio, video, or screen data is captured.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "consent_block_failure" {
  alarm_name          = "aurion-${var.environment}-consent-block-failure"
  alarm_description   = "Consent block bypassed - recording started without confirmed consent"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 1
  treat_missing_data  = "notBreaching"

  namespace   = local.cw_namespace
  metric_name = "ConsentBlockFailure"
  statistic   = "Sum"
  period      = 60
  dimensions = {
    Service = "session"
  }

  tags = {
    Name = "aurion-${var.environment}-consent-block-failure-alarm"
  }
}

# -----------------------------------------------------------------------------
# Alarm 4: Provider Fallback Triggered
# Fires when 3 or more fallback events occur in a 5-minute period. Indicates
# the primary AI provider may be degraded or unavailable.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "provider_fallback" {
  alarm_name          = "aurion-${var.environment}-provider-fallback"
  alarm_description   = "AI provider fallback triggered - primary provider unavailable"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 3
  treat_missing_data  = "notBreaching"

  namespace   = local.cw_namespace
  metric_name = "ProviderFallbackTriggered"
  statistic   = "Sum"
  period      = 300
  dimensions = {
    Service = "providers"
  }

  tags = {
    Name = "aurion-${var.environment}-provider-fallback-alarm"
  }
}
