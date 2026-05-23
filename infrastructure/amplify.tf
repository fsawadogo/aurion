# =============================================================================
# Web Admin Portal — AWS Amplify Hosting
# =============================================================================
# W010 — provisions the Next.js admin portal at var.web_portal_subdomain.
#
# Architecture:
#   GitHub (fsawadogo/aurion, web/) ── Amplify webhook on push
#                                    │
#                                    └─→ Amplify build (Next.js SSR via Lambda@Edge)
#                                          │
#                                          └─→ Amplify CDN → portal-<env>.aurionclinical.com
#                                                              ↓ /api/v1/* calls
#                                                            api-<env>.aurionclinical.com (existing ALB)
#
# DNS pattern mirrors api domain: apex stays at Cloudflare, this subdomain
# delegates 4 NS records to a per-env Route 53 zone. After
# `terraform apply`, surface the new nameservers via `output portal_nameservers`
# and add them to Cloudflare as NS records for var.web_portal_subdomain.
#
# The app resources are gated on var.amplify_github_access_token so plan/apply
# can run cleanly while the PAT is being provisioned (or rotated). When the
# variable is null, the zone + ACM cert still exist (cheap, idempotent), but
# the app + branch + domain wiring are skipped.

# -----------------------------------------------------------------------------
# Route 53 hosted zone for the portal subdomain
# -----------------------------------------------------------------------------

resource "aws_route53_zone" "portal" {
  name = var.web_portal_subdomain

  tags = {
    Name = var.web_portal_subdomain
  }
}

# -----------------------------------------------------------------------------
# Amplify App
# -----------------------------------------------------------------------------

resource "aws_amplify_app" "web_portal" {
  count = var.amplify_github_access_token == null ? 0 : 1

  name        = "aurion-portal-${var.environment}"
  description = "Aurion admin / compliance / eval web portal (${var.environment})"

  repository           = "https://github.com/${var.github_org}/${var.github_repo}"
  access_token         = var.amplify_github_access_token
  platform             = "WEB_COMPUTE" # Next.js SSR via Lambda@Edge
  iam_service_role_arn = aws_iam_role.amplify_service[0].arn

  enable_branch_auto_build    = true
  enable_branch_auto_deletion = false
  enable_basic_auth           = false

  # Build inside the web/ subdirectory only — repo root is a monorepo.
  build_spec = <<-YAML
    version: 1
    applications:
      - appRoot: web
        frontend:
          phases:
            preBuild:
              commands:
                - npm ci
            build:
              commands:
                - npm run build
          artifacts:
            baseDirectory: .next
            files:
              - '**/*'
          cache:
            paths:
              - node_modules/**/*
              - .next/cache/**/*
  YAML

  # NEXT_PUBLIC_API_URL is the one config the browser bundle reads at build
  # time. Backend stays on api-<env>.aurionclinical.com, so the portal needs
  # to point at the same env's API. Branch-level overrides can flip this for
  # PR previews if/when those land.
  environment_variables = {
    NEXT_PUBLIC_API_URL       = "https://${var.api_domain}"
    AMPLIFY_MONOREPO_APP_ROOT = "web"
  }

  # Disallow indexing the portal — it's an admin tool, not public.
  custom_headers = <<-HEADERS
    customHeaders:
      - pattern: '**/*'
        headers:
          - key: 'X-Robots-Tag'
            value: 'noindex, nofollow'
          - key: 'Strict-Transport-Security'
            value: 'max-age=63072000; includeSubDomains; preload'
          - key: 'X-Content-Type-Options'
            value: 'nosniff'
          - key: 'X-Frame-Options'
            value: 'DENY'
          - key: 'Referrer-Policy'
            value: 'strict-origin-when-cross-origin'
  HEADERS

  tags = {
    Name = "aurion-portal-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Amplify branch — main only for now. PR-preview branches deferred to a
# follow-up once the portal stabilises.
# -----------------------------------------------------------------------------

resource "aws_amplify_branch" "main" {
  count = var.amplify_github_access_token == null ? 0 : 1

  app_id      = aws_amplify_app.web_portal[0].id
  branch_name = "main"

  framework = "Next.js - SSR"
  stage     = var.environment == "prod" ? "PRODUCTION" : "DEVELOPMENT"

  enable_auto_build = true
}

# -----------------------------------------------------------------------------
# Custom domain — portal-<env>.aurionclinical.com → Amplify default subdomain
# -----------------------------------------------------------------------------

resource "aws_amplify_domain_association" "portal" {
  count = var.amplify_github_access_token == null ? 0 : 1

  app_id                = aws_amplify_app.web_portal[0].id
  domain_name           = var.web_portal_subdomain
  wait_for_verification = false

  sub_domain {
    branch_name = aws_amplify_branch.main[0].branch_name
    prefix      = "" # apex of the zone — i.e. portal-dev.aurionclinical.com itself
  }
}

# -----------------------------------------------------------------------------
# IAM service role for Amplify (build + log access)
# -----------------------------------------------------------------------------

data "aws_iam_policy_document" "amplify_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["amplify.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "amplify_service" {
  count = var.amplify_github_access_token == null ? 0 : 1

  name               = "AurionAmplifyService-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.amplify_assume.json
}

resource "aws_iam_role_policy_attachment" "amplify_backend" {
  count      = var.amplify_github_access_token == null ? 0 : 1
  role       = aws_iam_role.amplify_service[0].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess-Amplify"
}
