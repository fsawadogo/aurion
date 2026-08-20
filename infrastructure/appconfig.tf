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
                temperature                     = { type = "number", minimum = 0.0, maximum = 2.0 }
                max_tokens                      = { type = "integer", minimum = 100, maximum = 16000 }
                stage1_critique_timeout_seconds = { type = "number", minimum = 0.5, maximum = 15.0 }
              }
            }
            vision = {
              type                 = "object"
              required             = ["temperature", "max_tokens", "confidence_threshold"]
              additionalProperties = false
              properties = {
                temperature = { type = "number", minimum = 0.0, maximum = 2.0 }
                # #437 — raised 4000→8000 to match the Pydantic `le` (richer
                # clip descriptions on frontier vision models).
                max_tokens           = { type = "integer", minimum = 100, maximum = 8000 }
                confidence_threshold = { type = "string", enum = ["low", "medium", "high"] }
                # Gemini native-video clip tokenisation resolution. NOT in
                # `required` so older hosted documents stay deployable — the
                # backend Pydantic default ("low") applies when absent. MUST
                # match VisionModelParams.clip_media_resolution.
                clip_media_resolution = { type = "string", enum = ["default", "low", "medium", "high"] }
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
            # Availability ceiling, distinct from alerting.sla_stage1_ms (the
            # 30-second performance target). Optional for older hosted docs;
            # Pydantic and this schema annotation default it to 90 seconds.
            stage1_hard_deadline_ms = {
              type    = "integer"
              minimum = 30000
              maximum = 300000
              default = 90000
            }
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
            # Clip cadence floor (#324). Interval (seconds) at which iOS
            # extracts >=1 clip during recording regardless of spoken
            # triggers, so a silent physical exam still yields clip
            # captions. 0 = off (back-compat); dev runs at 30. Bounds
            # 0..300 MUST match the backend Pydantic Field in
            # backend/app/modules/config/schema.py. NOT in the pipeline
            # `required` list (precedent: longitudinal_context_max_encounters,
            # media_review_retention_days) so an older hosted document
            # without this key still validates under
            # additionalProperties = false — the backend Pydantic default
            # (0) supplies the value until the CLI hosted-version push
            # ships the key live (hosted content is CLI-managed; terraform
            # owns the schema validator only).
            clip_cadence_seconds = { type = "integer", minimum = 0, maximum = 300 }
            # Longitudinal patient context (#61, full slice). Cap on
            # the number of prior encounters Stage 1 note-gen feeds to
            # the LLM as additional context. Mirrors PipelineConfig in
            # backend/app/modules/config/schema.py.
            longitudinal_context_max_encounters = { type = "integer", minimum = 1, maximum = 10 }
            # Stage 1 entry guard (lane-backend/empty-transcript-guard).
            # Minimum cumulative transcript character count below which
            # Stage 1 is short-circuited with a
            # STAGE1_SKIPPED_LOW_TRANSCRIPT audit event — the provider
            # is NEVER called below this threshold. 0 disables only the
            # low-transcript branch; the missing/empty branch always
            # fires. Mirrors PipelineConfig in
            # backend/app/modules/config/schema.py.
            #
            # TODO(lane-backend/empty-transcript-guard): push a new hosted
            # configuration version via the AWS CLI to ship this key into
            # the live AppConfig document — terraform owns the schema
            # validator only (see comment block below on why hosted
            # versions + deployments are CLI-managed). Until that CLI
            # push lands, the backend keeps reading the Pydantic default
            # (20), which is byte-identical to what the new schema enforces.
            min_transcript_char_threshold = { type = "integer", minimum = 0, maximum = 1000 }
            # Windowed media retention (#338). Number of days the backend
            # treats as the in-review retention window for captured media —
            # the app-level purge-on-approval path is precise; this is the
            # max-window backstop. Bounds 1..30 MUST match the backend
            # Pydantic Field that lane B adds to PipelineConfig in
            # backend/app/modules/config/schema.py. NOT in the pipeline
            # `required` list (precedent: longitudinal_context_max_encounters)
            # so an older hosted document without this key still validates
            # under additionalProperties = false — the backend Pydantic
            # default supplies the value until the CLI hosted-version push
            # ships the key live.
            media_review_retention_days = { type = "integer", minimum = 1, maximum = 30 }
            # Video-import per-window frame sample rate (VID-03). Bounds 1..10
            # MUST match PipelineConfig.video_import_fps. NOT in `required` so
            # an older document validates — the Pydantic default (1) supplies it.
            video_import_fps = { type = "integer", minimum = 1, maximum = 10 }
            # Cadence-based frame extraction for uploaded videos. Interval (s) at
            # which the import samples a frame across the whole timeline
            # regardless of spoken triggers, so a SILENT exam still yields frames.
            # 0 = off (back-compat). Bounds 0..120 MUST match
            # PipelineConfig.video_import_cadence_seconds. NOT in `required`.
            video_import_cadence_seconds = { type = "integer", minimum = 0, maximum = 120 }
            # Hard ceiling on cadence frames per import (thins a long video so it
            # can't fan out into thousands of vision calls). Bounds 1..500 MUST
            # match PipelineConfig.video_import_max_cadence_frames. NOT required.
            video_import_max_cadence_frames = { type = "integer", minimum = 1, maximum = 500 }
            # Max evidence items captioned CONCURRENTLY in Stage 2. Bounds 1..32
            # MUST match PipelineConfig.vision_max_concurrency. NOT in `required`
            # so an older document validates — the Pydantic default (4) supplies
            # it. Caps the Gemini fan-out so a large frame set drains under the
            # vision rate limit instead of 429-storming.
            vision_max_concurrency = { type = "integer", minimum = 1, maximum = 32 }
            # MUST match PipelineConfig.video_import_preprocessing_concurrency
            # (#770). Absent here, `additionalProperties = false` makes AWS
            # reject EVERY deployment — including every Feature Flags save.
            video_import_preprocessing_concurrency = { type = "integer", minimum = 1, maximum = 32 }
            # Process-wide Gemini quota controls. Optional for older profiles;
            # backend defaults are fail-safe for the development key.
            vision_gemini_max_concurrency         = { type = "integer", minimum = 1, maximum = 8 }
            vision_gemini_max_retries             = { type = "integer", minimum = 0, maximum = 5 }
            vision_gemini_primary_timeout_seconds = { type = "number", minimum = 5, maximum = 120 }
            vision_gemini_circuit_breaker_seconds = { type = "integer", minimum = 1, maximum = 600 }
            vision_provider_usage_timeout_seconds = { type = "number", minimum = 0.1, maximum = 5 }
            vision_max_evidence_items             = { type = "integer", minimum = 1, maximum = 200 }
            vision_trigger_evidence_fraction      = { type = "number", minimum = 0.5, maximum = 1.0 }
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
            # Card-visibility flags (lane-full/card-visibility-flags).
            # All four default `false` in the AppConfig hosted version
            # the operator pushes after deploy — the post-pilot cards
            # (Orders, Coding & Billing, Patient Summary, EMR Write-Back)
            # stay hidden in iOS SessionNoteView until ADMIN flips the
            # matching flag via the web portal's /portal/admin/feature-
            # flags page. NOT in the `required` list above so an older
            # AppConfig document without these keys still validates
            # (backend Pydantic schema supplies the default).
            orders_card_enabled          = { type = "boolean" }
            coding_card_enabled          = { type = "boolean" }
            patient_summary_card_enabled = { type = "boolean" }
            emr_writeback_card_enabled   = { type = "boolean" }
            # Visual-evidence path flags (lane-backend/vision-evidence-feature-
            # flags). Gate the two video-vision paths independently so the
            # pipeline can be steered from AppConfig without a redeploy:
            # clip (Gemini) interpretation vs legacy frame-by-frame video.
            # NOT in `required` so an older document without these keys still
            # validates (backend Pydantic schema defaults both `true`).
            clip_video_interpretation_enabled = { type = "boolean" }
            frame_by_frame_video_enabled      = { type = "boolean" }
            # Windowed media retention (#338). Gates the in-review retention
            # window behaviour. Default-OFF: the hosted document the operator
            # pushes leaves this false (and prod stays unchanged) so the
            # feature only activates once explicitly enabled. NOT in the
            # feature_flags `required` list (precedent: the card flags) so an
            # older document without the key still validates under
            # additionalProperties = false — the backend Pydantic schema
            # supplies the default.
            media_review_retention_enabled = { type = "boolean" }
            # Conversational template authoring — note-derived seed (tpl-from-note).
            # NOT in `required` so an older document without the key still validates
            # under additionalProperties = false — the backend Pydantic schema
            # defaults it false (the note-to-template path stays dark until enabled).
            template_authoring_chat_enabled = { type = "boolean" }
            # Note-review "fix this note" chat (note-review-assist). NOT in
            # `required` so an older document without the key still validates
            # under additionalProperties = false — the backend defaults it false.
            note_review_chat_enabled = { type = "boolean" }
            # Web-portal encounter-video import (VID-01..11). Master gate +
            # the zero-face-frame drop policy. NOT in `required` so older
            # documents without the keys still validate under
            # additionalProperties = false — the backend Pydantic schema
            # defaults both (video_import_enabled false, drop True).
            video_import_enabled               = { type = "boolean" }
            multi_clip_import_enabled          = { type = "boolean" }
            note_options_enabled               = { type = "boolean" }
            video_import_drop_zero_face_frames = { type = "boolean" }
            # Specialty STYLE GUIDANCE layer in the live Stage 1 note prompt
            # (incl. per-physician guidance overrides). NOT in `required` so an
            # older document without the key still validates under
            # additionalProperties = false — the backend Pydantic schema
            # defaults it false (specialty layer stays dark until enabled).
            specialty_style_in_prompt_enabled = { type = "boolean" }
            # Grounded Synthesis Mode (v3.2, #552). MUST be here — the backend
            # dumps the full FeatureFlagsConfig on every save and
            # additionalProperties = false rejects unknown keys (cf. #530). The
            # backend Pydantic schema defaults it false (mode stays dark until
            # GS-9 sign-off).
            grounded_synthesis_enabled = { type = "boolean" }
            # Template Engine · generation core (Cohort 7). Same reason as
            # above: the backend dumps the full FeatureFlagsConfig on save and
            # additionalProperties = false rejects unknown keys. NOT in
            # `required` so older hosted documents keep validating.
            template_engine_enabled = { type = "boolean" }
            # On-device visual measurement gate (#63). Had drifted out of this
            # validator — with additionalProperties = false that rejected EVERY
            # feature-flags hosted-version write (the backend publishes the full
            # FeatureFlagsConfig dump). NOT in `required` so older documents
            # without the key still validate; the backend defaults it false.
            measurement_enabled = { type = "boolean" }
            # Prompt Studio (create & share, #524). Master gate + the role
            # allowlist permitted to use it. NOT in `required` so older
            # documents validate — the backend defaults the gate false and the
            # allowlist to ["ADMIN"]. These MUST be here (additionalProperties =
            # false) or the portal Feature Flags save is rejected by AWS.
            prompt_studio_enabled = { type = "boolean" }
            prompt_studio_roles   = { type = "array", items = { type = "string" } }
            # Clinician AI-Prompts display scope (ps-fu5). NOT in `required` so
            # an older hosted document without the key still validates — the
            # backend Pydantic schema defaults it false (all categories shown).
            clinician_prompts_note_only = { type = "boolean" }
            # Cross-clinician Patient Chart (#604). Master gate for the
            # elevated-role aggregated patient view + supervisory validate.
            # NOT in `required` so an older hosted document without the key
            # still validates under additionalProperties = false — the backend
            # Pydantic schema defaults it false (feature stays dark). MUST be
            # here (additionalProperties = false) or the portal Feature Flags
            # save is rejected by AWS (the backend dumps the full config).
            cross_clinician_chart_enabled = { type = "boolean" }
            # Grounded visual findings — video produces cited exam findings
            # (Stage-2 vision shifts descriptive→grounded, source_id=frame_id
            # invariant). It narrows grounded_synthesis_enabled; BOTH flags are
            # required in the doctor pipeline. NOT in `required` so older
            # documents validate under additionalProperties = false — the
            # backend Pydantic schema defaults it false.
            grounded_visual_findings_enabled = { type = "boolean" }
            # Fusion B (parallel-then-merge). NOT `required`; backend defaults it
            # false. Gates any future LIVE use of parallel fusion — the A/B
            # comparison in the Grounded Lab runs regardless of this flag.
            parallel_fusion_enabled = { type = "boolean" }
            # Correction memory — logs in-app note edits. NOT `required`; backend
            # defaults it false. Gates capture only.
            correction_memory_enabled = { type = "boolean" }
            # Inject accepted correction rules into note generation. NOT
            # `required`; backend defaults it false.
            correction_rules_in_prompt_enabled = { type = "boolean" }
            # Standalone visual evidence — video can carry a note when audio is
            # empty/thin (video-import path). NOT `required`; backend defaults it
            # false. Face-less-frame retention needs compliance sign-off to enable.
            visual_evidence_standalone_enabled  = { type = "boolean" }
            keep_low_confidence_visual_findings = { type = "boolean" }
          }
        }
        # Synthesized-alert detector thresholds (#76; detectors shipped in
        # PR #408). NOT in the root `required` list so every existing hosted
        # document (which predates the block) still validates under
        # additionalProperties = false — the backend Pydantic schema
        # (AlertingConfig) supplies the defaults (30000 / 300000 / 24).
        # Bounds MUST mirror backend/app/modules/config/schema.py.
        alerting = {
          type                 = "object"
          additionalProperties = false
          properties = {
            sla_stage1_ms   = { type = "integer", minimum = 1000, maximum = 3600000 }
            sla_stage2_ms   = { type = "integer", minimum = 1000, maximum = 86400000 }
            purge_gap_hours = { type = "integer", minimum = 1, maximum = 336 }
          }
        }
        # Per-provider AI model-ID overrides (#437). NOT in the root `required`
        # list — older hosted documents predate it (same precedent as alerting),
        # so they still validate under additionalProperties = false; the backend
        # Pydantic ModelVersionsConfig supplies the None defaults. This block
        # MUST be declared so the Gemini 3.1 Pro flip (#438), which pushes a
        # hosted doc WITH model_versions.gemini set, validates. Keys mirror
        # backend/app/modules/config/schema.py ModelVersionsConfig.
        model_versions = {
          type                 = "object"
          additionalProperties = false
          properties = {
            gemini    = { type = "string" }
            openai    = { type = "string" }
            anthropic = { type = "string" }
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
