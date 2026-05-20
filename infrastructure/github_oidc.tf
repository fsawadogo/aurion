# =============================================================================
# GitHub Actions ↔ AWS OIDC trust
# =============================================================================
# Phase 3 of the production rollout. Lets the CI/CD workflows in this
# repo assume short-lived AWS credentials via OIDC, with no long-lived
# access keys stored as GitHub Secrets.
#
# Two roles are created:
#   - `AurionGitHubDeployerDev`  — assumed by pushes to `main`
#   - `AurionGitHubDeployerProd` — assumed by `workflow_dispatch`-triggered
#                                  prod deploys ONLY (the workflow author
#                                  is the human gate)
#
# The OIDC provider is account-wide — one provider, multiple roles. The
# `provider`-level trust path is the same; the per-role `condition` block
# is what scopes who can use which role.

# -----------------------------------------------------------------------------
# Provider variables
# -----------------------------------------------------------------------------

variable "github_org" {
  description = "GitHub organization / user that owns this repo. Used in the OIDC trust policy `sub` condition."
  type        = string
  default     = "fsawadogo"
}

variable "github_repo" {
  description = "GitHub repo name (without owner). Combined with github_org to scope the OIDC trust."
  type        = string
  default     = "aurion"
}

# -----------------------------------------------------------------------------
# OIDC Identity Provider
# -----------------------------------------------------------------------------
# Account-scoped. Created once and reused across all GitHub-Actions roles
# in this account. AWS verifies the provider's TLS cert chain on each
# AssumeRoleWithWebIdentity, so the `thumbprint_list` doesn't need to be
# updated when GitHub rotates its certs — Amazon handles that internally
# as long as the cert is valid for token.actions.githubusercontent.com.

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Name = "github-actions-oidc"
  }
}

# -----------------------------------------------------------------------------
# Dev deployer role — assumed by pushes to `main`
# -----------------------------------------------------------------------------

resource "aws_iam_role" "github_deployer_dev" {
  name = "AurionGitHubDeployerDev"

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
            # Lock to this exact repo + branch. The `:ref:` form below
            # would also work to restrict by tag/branch separately, but
            # `:environment:dev` is more explicit if you adopt GitHub
            # Environments later.
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main",
            ]
          }
        }
      }
    ]
  })

  tags = {
    Name = "AurionGitHubDeployerDev"
  }
}

# Broad dev permissions — terraform apply against dev tfvars touches
# every service. Tighten before pilot if you want; pre-pilot, admin is
# acceptable for the dev account.
resource "aws_iam_role_policy_attachment" "github_deployer_dev_admin" {
  role       = aws_iam_role.github_deployer_dev.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# -----------------------------------------------------------------------------
# Prod deployer role — manual workflow_dispatch only
# -----------------------------------------------------------------------------
# The trust policy here intentionally does NOT include the `main` branch
# `sub`. Instead it requires `:environment:prod`, which means the workflow
# must declare `environment: prod` AND that environment must exist in
# GitHub repo settings (with a protection rule requiring manual approval).
# Belt and suspenders: an attacker who somehow ran code on `main` still
# couldn't deploy to prod via this role.

resource "aws_iam_role" "github_deployer_prod" {
  name = "AurionGitHubDeployerProd"

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
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:environment:prod"
          }
        }
      }
    ]
  })

  tags = {
    Name = "AurionGitHubDeployerProd"
  }
}

resource "aws_iam_role_policy_attachment" "github_deployer_prod_admin" {
  role       = aws_iam_role.github_deployer_prod.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
