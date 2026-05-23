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

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

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

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

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

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

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

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "aurion-${var.environment}-provider-fallback-alarm"
  }
}

# =============================================================================
# Operational Alarms (Phase 4) — AWS built-in metrics, no app changes needed
# =============================================================================
# The four alarms above are business-metric alarms (PutMetric from the
# app). These five are operational — they watch AWS-emitted metrics that
# tell us whether the platform is breathing, independent of app logic.

# -----------------------------------------------------------------------------
# Alarm 5: ALB 5xx rate
# Fires when the ALB sees ≥10 5xx responses over a 5-minute window.
# Indicates backend instability — usually means ECS tasks are crashing
# or the task definition is wrong.
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "aurion-${var.environment}-alb-5xx-high"
  alarm_description   = "ALB returning 5xx responses — backend tasks unhealthy"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 10
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/ApplicationELB"
  metric_name = "HTTPCode_Target_5XX_Count"
  statistic   = "Sum"
  period      = 300
  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "aurion-${var.environment}-alb-5xx-alarm"
  }
}

# -----------------------------------------------------------------------------
# Alarm 6: RDS CPU > 80% sustained
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "aurion-${var.environment}-rds-cpu-high"
  alarm_description   = "RDS CPU > 80% for 10 minutes — query or connection storm"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 80
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/RDS"
  metric_name = "CPUUtilization"
  statistic   = "Average"
  period      = 300
  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "aurion-${var.environment}-rds-cpu-alarm"
  }
}

# -----------------------------------------------------------------------------
# Alarm 7: RDS free storage < 5 GB
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "rds_storage_low" {
  alarm_name          = "aurion-${var.environment}-rds-storage-low"
  alarm_description   = "RDS free storage below 5 GB — running out of disk"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  threshold           = 5 * 1024 * 1024 * 1024 # 5 GB in bytes
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/RDS"
  metric_name = "FreeStorageSpace"
  statistic   = "Average"
  period      = 300
  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "aurion-${var.environment}-rds-storage-alarm"
  }
}

# -----------------------------------------------------------------------------
# Alarm 8: RDS connections > 80
# Pilot RDS is db.t3.medium with max_connections ~= 120 default. 80
# leaves headroom; >80 is a leak or runaway.
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "aurion-${var.environment}-rds-connections-high"
  alarm_description   = "RDS database connections > 80 — possible connection leak"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 80
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/RDS"
  metric_name = "DatabaseConnections"
  statistic   = "Average"
  period      = 300
  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "aurion-${var.environment}-rds-connections-alarm"
  }
}

# -----------------------------------------------------------------------------
# Alarm 9: ECS service has no healthy tasks
# Fires immediately if running task count drops to 0. This is the "site
# is down" alarm.
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "ecs_healthy_tasks" {
  alarm_name          = "aurion-${var.environment}-ecs-tasks-zero"
  alarm_description   = "ECS aurion-api service has zero running tasks"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  threshold           = 1
  treat_missing_data  = "breaching"

  namespace   = "AWS/ECS"
  metric_name = "RunningTaskCount"
  statistic   = "Average"
  period      = 60
  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.api.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "aurion-${var.environment}-ecs-tasks-alarm"
  }
}
