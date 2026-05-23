# =============================================================================
# Cognito — User Pool, App Client, Role Groups
# =============================================================================
# Shared authentication for both the iOS app and the web admin portal.
# Roles: CLINICIAN, EVAL_TEAM, COMPLIANCE_OFFICER, ADMIN
# =============================================================================

resource "aws_cognito_user_pool" "main" {
  name = "aurion-${var.environment}"

  # Admin-only signup — no self-registration
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # Sign in with email
  username_attributes = ["email"]

  # Auto-verify email
  auto_verified_attributes = ["email"]

  # Password policy — strong defaults for clinical application
  password_policy {
    minimum_length                   = 12
    require_uppercase                = true
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  # Multi-factor authentication.
  #
  # Required for every user in both envs. Clinical app handling PHI:
  # the cost of a stolen password is too high to leave MFA optional.
  # SMS deliberately omitted — SIM-swap risk is real, TOTP via an
  # authenticator app (1Password / Authy / Google Authenticator /
  # iOS-built-in) is the appropriate factor here.
  mfa_configuration = "ON"

  software_token_mfa_configuration {
    enabled = true
  }

  # Account recovery via email only
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Schema — email is the primary identifier
  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 5
      max_length = 128
    }
  }

  deletion_protection = var.environment == "prod" ? "ACTIVE" : "INACTIVE"

  tags = {
    Name = "aurion-user-pool-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# App Client — No secret (public client for iOS app and web SPA)
# -----------------------------------------------------------------------------

resource "aws_cognito_user_pool_client" "main" {
  name         = "aurion-client-${var.environment}"
  user_pool_id = aws_cognito_user_pool.main.id

  # No client secret — required for public clients (iOS, web SPA)
  generate_secret = false

  # Auth flows. Refresh token is the only one needed for the hosted-UI
  # OAuth Authorization Code path; SRP / PASSWORD remain for backwards
  # compatibility with the local-dev backend flow until that's deleted.
  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH"
  ]

  # Prevent user enumeration attacks
  prevent_user_existence_errors = "ENABLED"

  # ---------------------------------------------------------------------------
  # OAuth — Authorization Code flow with PKCE, for Cognito hosted UI.
  # ---------------------------------------------------------------------------
  # iOS launches the hosted login page in ASWebAuthenticationSession,
  # Cognito handles the password + TOTP MFA flow, and redirects back to
  # the app with an auth code which iOS exchanges for tokens at /oauth2/token.
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile", "aws.cognito.signin.user.admin"]

  callback_urls = [
    "aurion://oauth-callback",
    "http://localhost:3000/api/auth/callback/cognito",
    # Web portal — wired now so the hosted-UI integration can land later
    # without a Cognito redeploy. Until the web side actually launches
    # the hosted UI flow, the existing /auth/login path keeps working.
    "https://${var.web_portal_subdomain}/api/auth/callback/cognito",
  ]
  logout_urls = [
    "aurion://oauth-logout",
    "http://localhost:3000/auth/signed-out",
    "https://${var.web_portal_subdomain}/auth/signed-out",
  ]
  supported_identity_providers = ["COGNITO"]

  # Token validity
  access_token_validity  = 1  # 1 hour
  id_token_validity      = 1  # 1 hour
  refresh_token_validity = 30 # 30 days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

# -----------------------------------------------------------------------------
# Hosted UI Domain
# -----------------------------------------------------------------------------
# Public sign-in page at `aurion-<env>.auth.ca-central-1.amazoncognito.com`.
# Free with the user pool — no custom cert or Route 53 setup needed. A
# custom domain (login.aurionclinical.com) is a follow-up; the AWS-managed
# subdomain is acceptable for the pilot since the URL is only rendered
# briefly inside ASWebAuthenticationSession.

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "aurion-${var.environment}"
  user_pool_id = aws_cognito_user_pool.main.id
}

# -----------------------------------------------------------------------------
# User Groups — Application Roles
# -----------------------------------------------------------------------------

resource "aws_cognito_user_group" "clinician" {
  name         = "CLINICIAN"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Aurion CLINICIAN role - physicians using the iOS app"
}

resource "aws_cognito_user_group" "eval_team" {
  name         = "EVAL_TEAM"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Aurion EVAL_TEAM role - internal quality review team"
}

resource "aws_cognito_user_group" "compliance_officer" {
  name         = "COMPLIANCE_OFFICER"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Aurion COMPLIANCE_OFFICER role - audit log and PHI masking review"
}

resource "aws_cognito_user_group" "admin" {
  name         = "ADMIN"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Aurion ADMIN role - full access including user management"
}
