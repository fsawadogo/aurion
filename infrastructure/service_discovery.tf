# =============================================================================
# Service Discovery (AWS Cloud Map) — internal DNS for the Whisper service
# =============================================================================
# The API (Fargate) reaches the self-hosted Whisper ASR service by a stable
# private DNS name instead of a task IP. Both tasks run `awsvpc`, so Cloud Map
# registers each Whisper task's ENI as an A record under this namespace; the
# API resolves `whisper.aurion-<env>.local` and connects on container port
# 9000.
#
# This is what makes `providers.transcription = "whisper"` in AppConfig
# actually work — flip the AppConfig key to switch between Whisper (self-
# hosted, audio stays in ca-central-1) and AssemblyAI (cloud) with no code
# change. Whisper still has to be running: its ECS service `desired_count`
# is 0 in dev for cost (scale to ≥1 to use it) and 1 in prod.

resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "aurion-${var.environment}.local"
  description = "Internal service discovery for Aurion ${var.environment}"
  vpc         = aws_vpc.main.id

  tags = {
    Name = "aurion-sd-namespace-${var.environment}"
  }
}

resource "aws_service_discovery_service" "whisper" {
  name = "whisper"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id

    dns_records {
      type = "A"
      ttl  = 10
    }

    routing_policy = "MULTIVALUE"
  }

  # ECS drives instance health via the service-registries integration, so a
  # custom (ECS-reported) health check is the right model here — Cloud Map
  # only advertises tasks ECS considers healthy.
  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name = "aurion-sd-whisper-${var.environment}"
  }
}

# Stable URL the API uses for the Whisper ASR webservice. Referenced by the
# API task definition's WHISPER_API_URL env (see ecs.tf).
locals {
  whisper_api_url = "http://whisper.${aws_service_discovery_private_dns_namespace.main.name}:9000"
}
