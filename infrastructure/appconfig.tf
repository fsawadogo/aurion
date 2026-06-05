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

  # JSON Schema validator — mirrors backend/app/modules/config/schema.py
  # Any deployment with an invalid provider key, out-of-range parameter, or
  # missing required field is rejected by AppConfig before it reaches the
  # running app. CLAUDE.md's "Schema validation rejects bad keys" checkpoint
  # depends on this block.
  validator {
    type = "JSON_SCHEMA"
    content = jsonencode({
      "$schema"            = "http://json-schema.org/draft-07/schema#"
      title                = "AurionAppConfig"
      type                 = "object"
      required             = ["providers", "model_params", "pipeline", "feature_flags"]
      additionalProperties = false
      properties = {
        providers = {
          type                 = "object"
          required             = ["transcription", "note_generation", "vision"]
          additionalProperties = false
          properties = {
            transcription   = { type = "string", enum = ["whisper", "assemblyai"] }
            note_generation = { type = "string", enum = ["openai", "anthropic", "gemini"] }
            vision          = { type = "string", enum = ["openai", "anthropic", "gemini"] }
            # Phase 1 dual-mode (Cohort 5): the vision provider used for
            # clip-kind evidence. Independent of the frame provider so
            # clinics can route motion-heavy work to Gemini (native video)
            # while keeping cheap still-frame work on OpenAI/Anthropic.
            vision_clip = { type = "string", enum = ["openai", "anthropic", "gemini"] }
          }
        }
        model_params = {
          type                 = "object"
          required             = ["note_generation", "vision"]
          additionalProperties = false
          properties = {
            note_generation = {
              type                 = "object"
              required             = ["temperature", "max_tokens"]
              additionalProperties = false
              properties = {
                temperature = { type = "number", minimum = 0.0, maximum = 2.0 }
                max_tokens  = { type = "integer", minimum = 100, maximum = 16000 }
              }
            }
            vision = {
              type                 = "object"
              required             = ["temperature", "max_tokens", "confidence_threshold"]
              additionalProperties = false
              properties = {
                temperature          = { type = "number", minimum = 0.0, maximum = 2.0 }
                max_tokens           = { type = "integer", minimum = 100, maximum = 4000 }
                confidence_threshold = { type = "string", enum = ["low", "medium", "high"] }
              }
            }
          }
        }
        pipeline = {
          type = "object"
          required = [
            "stage1_skip_window_seconds",
            "frame_window_clinic_ms",
            "frame_window_procedural_ms",
            "screen_capture_fps",
            "video_capture_fps",
          ]
          additionalProperties = false
          properties = {
            stage1_skip_window_seconds = { type = "integer", minimum = 10, maximum = 600 }
            frame_window_clinic_ms     = { type = "integer", minimum = 500, maximum = 30000 }
            frame_window_procedural_ms = { type = "integer", minimum = 1000, maximum = 60000 }
            screen_capture_fps         = { type = "integer", minimum = 1, maximum = 10 }
            video_capture_fps          = { type = "integer", minimum = 1, maximum = 10 }
            # Phase 1 dual-mode (Cohort 5): pipeline knobs for the clip
            # path. visual_evidence_mode is the top-level switch — the
            # iOS dispatcher routes per-trigger only when mode == "hybrid".
            visual_evidence_mode     = { type = "string", enum = ["frames_only", "clips_only", "hybrid"] }
            clip_window_ms           = { type = "integer", minimum = 1000, maximum = 30000 }
            clip_ring_buffer_seconds = { type = "integer", minimum = 5, maximum = 60 }
            clip_trigger_kinds       = { type = "array", items = { type = "string" } }
            # Longitudinal patient context (#61, full slice). Cap on
            # the number of prior encounters Stage 1 note-gen feeds to
            # the LLM as additional context. Mirrors PipelineConfig in
            # backend/app/modules/config/schema.py.
            longitudinal_context_max_encounters = { type = "integer", minimum = 1, maximum = 10 }
          }
        }
        feature_flags = {
          type = "object"
          required = [
            "screen_capture_enabled",
            "note_versioning_enabled",
            "session_pause_resume_enabled",
            "per_session_provider_override",
          ]
          additionalProperties = false
          properties = {
            screen_capture_enabled        = { type = "boolean" }
            note_versioning_enabled       = { type = "boolean" }
            session_pause_resume_enabled  = { type = "boolean" }
            per_session_provider_override = { type = "boolean" }
            meta_wearables_enabled        = { type = "boolean" }
            # Phase 1 dual-mode (Cohort 5): gates the per-session
            # visual_evidence_mode override path (P1-7). False disables
            # the override even when the global mode is hybrid/clips_only.
            per_session_visual_evidence_mode_override = { type = "boolean" }
          }
        }
      }
    })
  }

  tags = {
    Name = "aurion-appconfig-profile-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Hosted Configuration Version + Deployment — managed via AWS CLI, not Terraform
# -----------------------------------------------------------------------------
#
# The AWS provider's `aws_appconfig_hosted_configuration_version` resource has
# a long-running InvalidSignatureException bug: the em-dash (U+2014) in the
# description string corrupts the SigV4 canonical string at the SDK layer, so
# every `terraform apply` that touches this resource hits a 403.
#
# We hit this:
#   2026-06-03 — Cohort 5 hybrid keys; CLI workaround pushed v5
#   2026-06-04 — #61 longitudinal_context key; CLI workaround pushed v6
#   2026-06-04 — PR #234 auth-pivot deploy died at terraform apply, leaving
#                the new backend image queued in ECR but never rolled to ECS
#   2026-06-05 — PR #236's `lifecycle.ignore_changes` didn't help: Terraform
#                was in CREATE mode because the resource was never imported
#                into state, so ignore_changes had nothing to ignore yet
#
# Decision: stop pretending Terraform owns these two resources. The hosted
# version + its deployment live in AWS, are recreated via the AWS CLI when
# we need new content, and Terraform never touches them again.
#
# The schema validator on `aws_appconfig_configuration_profile.main` (above)
# is STILL Terraform-managed — it's the gate that rejects bad content shapes
# at create-hosted-version time. We're only handing off the "publish new
# content" step.
#
# Workflow when an AppConfig key needs adding / changing:
#
#   1. Update the schema validator in this file (the profile resource works
#      fine in Terraform). Open a PR, merge, deploy.
#
#   2. Push the new content via CLI:
#
#        aws appconfig create-hosted-configuration-version \
#          --application-id a8wykyf \
#          --configuration-profile-id 3f4zwpr \
#          --content fileb:///tmp/new.json --content-type application/json \
#          --description "your reason" /tmp/meta.json
#
#   3. Deploy it via CLI (deployment strategy stays Terraform-managed):
#
#        aws appconfig start-deployment \
#          --application-id a8wykyf --environment-id dyjjd5e \
#          --configuration-profile-id 3f4zwpr \
#          --configuration-version <N> \
#          --deployment-strategy-id go3hmzn
#
# Rollback: live AppConfig still has every prior version. To roll back, run
# `start-deployment` again with the previous --configuration-version.
#
# The current live hosted version + deployment that this block used to manage
# remain in AWS untouched — we just stop tracking them in state. Removed
# blocks tell Terraform "remove from state on next apply, do NOT destroy."

removed {
  from = aws_appconfig_hosted_configuration_version.main

  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_appconfig_deployment.initial

  lifecycle {
    destroy = false
  }
}

# -----------------------------------------------------------------------------
# Deployment Strategy — AllAtOnce (immediate)
# -----------------------------------------------------------------------------
# Still Terraform-managed — it's just a configuration object, never recreated,
# never hits the InvalidSignatureException path.

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
