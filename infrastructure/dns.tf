# =============================================================================
# DNS — Route 53 hosted zone (per-env subdomain) + API A-alias
# =============================================================================
# Phase 2 of the production rollout, revised for subdomain delegation.
#
# Apex (aurionclinical.com) stays at Cloudflare. Each env delegates ONLY its
# own API subdomain to Route 53:
#   - dev:  api-dev.aurionclinical.com
#   - prod: api.aurionclinical.com
#
# At Cloudflare, the user creates 4 NS records (one-time per env) pointing
# that subdomain at the AWS nameservers from `output route53_nameservers`.
# Cloudflare keeps managing everything else under the apex (the future
# marketing site, etc.) — clean separation.
#
# Trade-off vs apex-delegation: each env has its own zone instead of sharing
# one. Slightly more state, no cross-env coupling, simpler to reason about.

resource "aws_route53_zone" "main" {
  # Zone NAME == the API domain — the A record below sits at the zone APEX.
  name = var.api_domain

  tags = {
    Name = var.api_domain
  }
}

# A-alias at the zone apex → ALB. Single-name zone, single record (plus the
# NS + SOA Route 53 auto-creates).
resource "aws_route53_record" "api" {
  zone_id = aws_route53_zone.main.zone_id
  name    = var.api_domain
  type    = "A"

  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = true
  }
}

# Re-exposed as a local so the rest of the module (acm.tf) doesn't have to
# branch on whether the zone came from a resource or a data source. With the
# subdomain-delegation model, every env owns its own zone, so the path is
# uniform.
locals {
  route53_zone_id     = aws_route53_zone.main.zone_id
  route53_nameservers = aws_route53_zone.main.name_servers
}
