# =============================================================================
# Marketing site — peritwin.com — AWS Amplify Hosting (manual-deploy mode)
# =============================================================================
# The public marketing site (github.com/forwauzz/aurion, Next.js static
# export) deployed on the same architecture as the admin portal:
# Amplify `platform = WEB`, bundles shipped from that repo's GitHub
# Actions via `aws amplify create-deployment` (see the website repo's
# .github/workflows/deploy.yml). No GitHub connector, no PAT.
#
# DNS: peritwin.com's zone is authoritative at Cloudflare (the apex
# cannot NS-delegate a single name the way portal.peritwin.com does),
# so this file does NOT create a Route 53 zone. After apply, create at
# Cloudflare (all DNS-only / grey cloud):
#   1. the ACM validation CNAME    → output marketing_cert_validation_record
#   2. apex flattened CNAME        → output marketing_domain_records
#   3. www CNAME                   → output marketing_domain_records
#
# CI auth: a dedicated OIDC role trusted ONLY by the website repo's main
# branch, with permissions limited to deploying this one Amplify app —
# the marketing repo must not hold keys that can touch clinical infra.

variable "marketing_domain" {
  description = "Apex domain for the public marketing site."
  type        = string
  default     = "peritwin.com"
}

variable "marketing_domain_alt" {
  description = <<-EOT
    Second apex domain that serves the SAME marketing site (dual-domain, like
    portal.peritwin.com + portal.aurionclinical.com share one Amplify app).
    Added as a second domain association on the same app + main branch. Its
    zone is authoritative at Cloudflare; cut its DNS over from the old Netlify
    site to Amplify using the marketing_alt_* outputs below.
  EOT
  type        = string
  default     = "peritwin.ai"
}

variable "marketing_github_org" {
  description = "GitHub owner of the marketing-site repo (OIDC trust scope)."
  type        = string
  default     = "forwauzz"
}

variable "marketing_github_repo" {
  description = "Marketing-site repo name (OIDC trust scope)."
  type        = string
  default     = "aurion"
}

# -----------------------------------------------------------------------------
# Amplify app
# -----------------------------------------------------------------------------

resource "aws_amplify_app" "marketing" {
  name        = "peritwin-marketing-${var.environment}"
  description = "PeriTwin public marketing site (${var.environment}). Static Next.js export, manual-deploy from github.com/${var.marketing_github_org}/${var.marketing_github_repo} CI."

  platform             = "WEB"
  iam_service_role_arn = aws_iam_role.amplify_service.arn

  # Locale entry: the site has no root page (next-intl localePrefix =
  # "always"), so bounce the bare origin to the default locale at the CDN.
  custom_rule {
    source = "/"
    target = "/en/"
    status = "302"
  }

  # Static export ships a real 404 page.
  custom_rule {
    source = "/<*>"
    target = "/404.html"
    status = "404"
  }

  tags = {
    Name = "peritwin-marketing-${var.environment}"
  }
}

resource "aws_amplify_branch" "marketing_main" {
  app_id      = aws_amplify_app.marketing.id
  branch_name = "main"

  description = "Deploy target for the website repo's main branch."

  # Manual-deploy mode: no auto-build (nothing is connected to build).
  enable_auto_build = false

  tags = {
    Name = "peritwin-marketing-main"
  }
}

# -----------------------------------------------------------------------------
# Custom domain — apex + www
# -----------------------------------------------------------------------------
# wait_for_verification = false: verification depends on the Cloudflare
# records above being created AFTER this apply, so blocking here would
# deadlock the first apply.

resource "aws_amplify_domain_association" "marketing" {
  app_id      = aws_amplify_app.marketing.id
  domain_name = var.marketing_domain

  wait_for_verification = false

  sub_domain {
    branch_name = aws_amplify_branch.marketing_main.branch_name
    prefix      = ""
  }

  sub_domain {
    branch_name = aws_amplify_branch.marketing_main.branch_name
    prefix      = "www"
  }
}

# Second custom domain — peritwin.ai (apex + www), SAME app + branch, so it
# serves the identical marketing site. Mirrors the portal's dual-domain setup.
# Amplify provisions a separate ACM cert for this domain; its validation +
# per-subdomain CNAMEs are surfaced via the marketing_alt_* outputs and must be
# created at Cloudflare (DNS-only), replacing the old Netlify records.
resource "aws_amplify_domain_association" "marketing_alt" {
  app_id      = aws_amplify_app.marketing.id
  domain_name = var.marketing_domain_alt

  wait_for_verification = false

  sub_domain {
    branch_name = aws_amplify_branch.marketing_main.branch_name
    prefix      = ""
  }

  sub_domain {
    branch_name = aws_amplify_branch.marketing_main.branch_name
    prefix      = "www"
  }
}

# -----------------------------------------------------------------------------
# OIDC deployer role for the website repo
# -----------------------------------------------------------------------------
# Reuses the existing GitHub OIDC provider (github_oidc.tf). Deliberately
# NOT the AurionGitHubDeployerDev role: that one carries AdministratorAccess
# for terraform applies. This role can deploy exactly one Amplify app.

resource "aws_iam_role" "marketing_deployer" {
  name = "PeritwinMarketingDeployer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.marketing_github_org}/${var.marketing_github_repo}:ref:refs/heads/main",
            ]
          }
        }
      }
    ]
  })

  tags = {
    Name = "PeritwinMarketingDeployer"
  }
}

resource "aws_iam_role_policy" "marketing_deployer" {
  name = "amplify-manual-deploy"
  role = aws_iam_role.marketing_deployer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AmplifyManualDeploy"
        Effect = "Allow"
        Action = [
          "amplify:CreateDeployment",
          "amplify:StartDeployment",
          "amplify:GetJob",
          "amplify:ListJobs",
          "amplify:GetBranch",
        ]
        Resource = [
          aws_amplify_app.marketing.arn,
          "${aws_amplify_app.marketing.arn}/*",
        ]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Outputs — consumed when wiring the website repo + Cloudflare
# -----------------------------------------------------------------------------

output "marketing_amplify_app_id" {
  description = "Set as the AMPLIFY_APP_ID secret in the website repo."
  value       = aws_amplify_app.marketing.id
}

output "marketing_deployer_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN secret in the website repo."
  value       = aws_iam_role.marketing_deployer.arn
}

output "marketing_default_domain" {
  description = "Amplify default hostname — site is live at main.<this> before DNS cutover."
  value       = aws_amplify_app.marketing.default_domain
}

output "marketing_cert_validation_record" {
  description = "ACM validation CNAME to create at Cloudflare (DNS-only)."
  value       = aws_amplify_domain_association.marketing.certificate_verification_dns_record
}

output "marketing_domain_records" {
  description = "Per-subdomain DNS records to create at Cloudflare (apex uses CNAME flattening, DNS-only)."
  value       = [for s in aws_amplify_domain_association.marketing.sub_domain : s.dns_record]
}

output "marketing_alt_cert_validation_record" {
  description = "peritwin.ai — ACM validation CNAME to create at Cloudflare (DNS-only)."
  value       = aws_amplify_domain_association.marketing_alt.certificate_verification_dns_record
}

output "marketing_alt_domain_records" {
  description = "peritwin.ai — per-subdomain DNS records to create at Cloudflare (apex CNAME flattening, DNS-only). REPLACES the old Netlify records."
  value       = [for s in aws_amplify_domain_association.marketing_alt.sub_domain : s.dns_record]
}
