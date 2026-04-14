# =============================================================================
# AppConfig — Runtime Configuration for Provider Switching and Feature Flags
# =============================================================================
# Polled every 30 seconds by the FastAPI backend. Changes take effect on new
# sessions without a redeploy. Provider keys, model params, pipeline settings,
# and feature flags are all managed here.
# =============================================================================

# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------

resource "aws_appconfig_application" "main" {
  name        = "aurion"
  description = "Aurion Clinical AI configuration - ${var.environment}"

  tags = {
    Name = "aurion-appconfig-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------

resource "aws_appconfig_environment" "main" {
  name           = var.environment
  description    = "Aurion ${var.environment} environment"
  application_id = aws_appconfig_application.main.id

  tags = {
    Name = "aurion-appconfig-env-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Configuration Profile
# -----------------------------------------------------------------------------

resource "aws_appconfig_configuration_profile" "main" {
  name           = "aurion-config"
  description    = "Aurion runtime configuration - providers, model params, feature flags"
  application_id = aws_appconfig_application.main.id
  location_uri   = "hosted"
  type           = "AWS.Freeform"

  tags = {
    Name = "aurion-appconfig-profile-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Hosted Configuration Version — Default Aurion Config
# -----------------------------------------------------------------------------

resource "aws_appconfig_hosted_configuration_version" "main" {
  application_id           = aws_appconfig_application.main.id
  configuration_profile_id = aws_appconfig_configuration_profile.main.configuration_profile_id
  content_type             = "application/json"
  description              = "Initial Aurion configuration"

  content = jsonencode({
    providers = {
      transcription   = "whisper"
      note_generation = "anthropic"
      vision          = "openai"
    }
    model_params = {
      note_generation = {
        temperature = 0.1
        max_tokens  = 2000
      }
      vision = {
        temperature          = 0.1
        max_tokens           = 500
        confidence_threshold = "medium"
      }
    }
    pipeline = {
      stage1_skip_window_seconds = 60
      frame_window_clinic_ms     = 3000
      frame_window_procedural_ms = 7000
      screen_capture_fps         = 2
      video_capture_fps          = 1
    }
    feature_flags = {
      screen_capture_enabled        = true
      note_versioning_enabled       = true
      session_pause_resume_enabled  = true
      per_session_provider_override = true
    }
  })
}

# -----------------------------------------------------------------------------
# Deployment Strategy — AllAtOnce (immediate)
# -----------------------------------------------------------------------------

resource "aws_appconfig_deployment_strategy" "all_at_once" {
  name                           = "aurion-all-at-once-${var.environment}"
  description                    = "Deploy configuration immediately to all targets"
  deployment_duration_in_minutes = 0
  growth_factor                  = 100
  growth_type                    = "LINEAR"
  replicate_to                   = "NONE"
  final_bake_time_in_minutes     = 0

  tags = {
    Name = "aurion-deploy-strategy-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Deployment — Deploy the initial configuration
# -----------------------------------------------------------------------------

resource "aws_appconfig_deployment" "initial" {
  application_id           = aws_appconfig_application.main.id
  environment_id           = aws_appconfig_environment.main.environment_id
  configuration_profile_id = aws_appconfig_configuration_profile.main.configuration_profile_id
  configuration_version    = aws_appconfig_hosted_configuration_version.main.version_number
  deployment_strategy_id   = aws_appconfig_deployment_strategy.all_at_once.id
  description              = "Initial deployment"

  tags = {
    Name = "aurion-appconfig-deployment-${var.environment}"
  }
}
