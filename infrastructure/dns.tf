# =============================================================================
# DNS — Route 53 hosted zone + API A-alias
# =============================================================================
# Phase 2 of the production rollout. Owns the apex hosted zone for
# `var.root_domain` plus the env-specific A-alias (`var.api_domain`) that
# points at the ALB.
#
# Zone-ownership model: exactly ONE env (set via `manage_root_zone = true`,
# typically dev) actually creates the hosted zone. Other envs look it up
# via data source. This is a single-zone-shared-by-envs setup — works
# because each env's A-alias has a distinct name (api-dev vs api).
#
# After the first apply, take the `route53_nameservers` output and set
# those NS records at your registrar for `var.root_domain`. Until that's
# done, the cert validation (in acm.tf) will hang on Route 53 propagation.

resource "aws_route53_zone" "main" {
  count = var.manage_root_zone ? 1 : 0
  name  = var.root_domain

  # Guard rail: a `terraform destroy` in the owning env would otherwise
  # wipe the apex zone, taking every other env's DNS with it. Forcing a
  # manual `lifecycle` removal first is the intended speed bump.
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = var.root_domain
  }
}

data "aws_route53_zone" "main" {
  count        = var.manage_root_zone ? 0 : 1
  name         = var.root_domain
  private_zone = false
}

locals {
  route53_zone_id     = var.manage_root_zone ? aws_route53_zone.main[0].zone_id : data.aws_route53_zone.main[0].zone_id
  route53_nameservers = var.manage_root_zone ? aws_route53_zone.main[0].name_servers : data.aws_route53_zone.main[0].name_servers
}

# A-alias from `var.api_domain` to the ALB.
# Note: this resource is defined here (DNS module) rather than in ecs.tf
# so all DNS lives in one file. The ALB is referenced by ARN from ecs.tf.
resource "aws_route53_record" "api" {
  zone_id = local.route53_zone_id
  name    = var.api_domain
  type    = "A"

  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = true
  }
}
