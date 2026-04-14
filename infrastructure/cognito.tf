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

  # Auth flows
  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH"
  ]

  # Prevent user enumeration attacks
  prevent_user_existence_errors = "ENABLED"

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
