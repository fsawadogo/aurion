# =============================================================================
# WAFv2 — Web ACL protecting the API ALB
# =============================================================================
# Phase 2 of the production rollout. Three AWS managed rule groups plus
# a per-IP rate limit. Scope is REGIONAL — required for ALB association
# (CLOUDFRONT scope is only for CloudFront).
#
# Default action is `allow {}` — rules block what they match. This is
# the standard "block-list with managed rules" pattern. If you ever flip
# to default `block {}`, every legitimate request needs an explicit
# allow rule (operationally painful, not recommended for an API ALB).
#
# All rule groups log to CloudWatch via the per-rule visibility_config;
# the overall ACL also logs aggregate metrics. Sampled requests are
# enabled so the WAF console can show "what got blocked and why."

resource "aws_wafv2_web_acl" "api" {
  name        = "aurion-api-waf-${var.environment}"
  description = "WAF protecting the Aurion API ALB. AWS managed rule sets + per-IP rate limit."
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # ---------------------------------------------------------------------------
  # Rule 1 — AWS Common Rule Set
  # OWASP top 10 coverage: XSS, RFI, generic bad request patterns.
  # ---------------------------------------------------------------------------
  rule {
    name     = "AWS-CommonRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"

        # SizeRestrictions_BODY blocks any request body over 8 KB. Aurion's
        # Stage 1 audio uploads (POST /transcription/{id}) and Stage 2 frame
        # uploads (POST /frames/{id}) are multipart bodies far larger than
        # that — even the 2 s minimum recording is ~64 KB of WAV — so this
        # rule 403'd every upload at the WAF before the request ever reached
        # the API. Count instead of block: oversized bodies are still logged
        # to CloudWatch, but allowed through. The per-IP rate limit (rule
        # 100) remains the DoS backstop, and every other Common Rule Set
        # protection (XSS, LFI, RFI, bad-bot) stays in blocking mode.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aurion-waf-common-${var.environment}"
      sampled_requests_enabled   = true
    }
  }

  # ---------------------------------------------------------------------------
  # Rule 2 — Known Bad Inputs
  # CVE-style attack strings, log4shell-class JNDI lookups, SSRF probes.
  # ---------------------------------------------------------------------------
  rule {
    name     = "AWS-KnownBadInputs"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aurion-waf-badinputs-${var.environment}"
      sampled_requests_enabled   = true
    }
  }

  # ---------------------------------------------------------------------------
  # Rule 3 — Amazon IP Reputation
  # Known scanners, anonymizing proxies, hosting providers used for
  # malware C2. Conservative; rare false positives.
  # ---------------------------------------------------------------------------
  rule {
    name     = "AWS-IPReputation"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aurion-waf-ipreputation-${var.environment}"
      sampled_requests_enabled   = true
    }
  }

  # ---------------------------------------------------------------------------
  # Rule 100 — Per-IP rate limit
  # Higher priority number = lower precedence. The rate limit fires only
  # if the managed rules didn't already block.
  # ---------------------------------------------------------------------------
  rule {
    name     = "RateLimitPerIP"
    priority = 100

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit_per_5min
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aurion-waf-ratelimit-${var.environment}"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "aurion-waf-${var.environment}"
    sampled_requests_enabled   = true
  }

  tags = {
    Name = "aurion-api-waf-${var.environment}"
  }
}

# Attach to the ALB. The association is regional, same region as the
# ALB itself.
resource "aws_wafv2_web_acl_association" "api" {
  resource_arn = aws_lb.api.arn
  web_acl_arn  = aws_wafv2_web_acl.api.arn
}
