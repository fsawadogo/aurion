# =============================================================================
# ACM — TLS certificate for the API
# =============================================================================
# Phase 2 of the production rollout. ACM issues a public cert for
# `var.api_domain`, validated automatically via DNS records in the
# Route 53 zone managed by `dns.tf`.
#
# Cert lives in the same region as the ALB (`var.region` = ca-central-1).
# ACM certs for ALB attachments must be regional; only CloudFront needs
# us-east-1.

resource "aws_acm_certificate" "api" {
  domain_name       = var.api_domain
  validation_method = "DNS"

  # ACM cert renewals are seamless via DNS validation, but Terraform
  # can churn the cert when the SANs list changes. `create_before_destroy`
  # means the new cert is issued + validated BEFORE the old one is
  # released, avoiding a brief no-cert window on the ALB.
  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "aurion-api-cert-${var.environment}"
  }
}

# DNS validation records — auto-created in Route 53. One record per
# domain (one here since we don't request SANs).
resource "aws_route53_record" "api_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.api.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id         = local.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

# Validation completion — blocks the listener (in ecs.tf) on this so
# the HTTPS listener never references a still-validating cert.
resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for r in aws_route53_record.api_cert_validation : r.fqdn]

  # ACM validation can take 5-10 minutes the first time. Default
  # Terraform timeout is 45 min; explicit here so it's visible.
  timeouts {
    create = "30m"
  }
}
