# =============================================================================
# Aurion Clinical AI — Input Variables
# =============================================================================

variable "environment" {
  description = "Deployment environment — dev or prod. Controls multi-AZ, scaling, retention policies."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "Environment must be 'dev' or 'prod'."
  }
}

variable "region" {
  description = "AWS region. Aurion data residency requires ca-central-1 (Canada)."
  type        = string
  default     = "ca-central-1"
}

# -----------------------------------------------------------------------------
# RDS
# -----------------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS PostgreSQL instance class."
  type        = string
  default     = "db.t3.medium"
}

variable "multi_az" {
  description = "Enable multi-AZ for RDS and redundant NAT gateways. True for prod."
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# ECS — FastAPI Fargate Service
# -----------------------------------------------------------------------------

variable "ecs_cpu" {
  description = "CPU units for the FastAPI Fargate task (1024 = 1 vCPU)."
  type        = number
  default     = 512
}

variable "ecs_memory" {
  description = "Memory (MiB) for the FastAPI Fargate task."
  type        = number
  default     = 1024
}

# -----------------------------------------------------------------------------
# ECS — Whisper GPU Service
# -----------------------------------------------------------------------------

variable "whisper_instance_type" {
  description = "EC2 instance type for the Whisper GPU service. g4dn.xlarge provides an NVIDIA T4."
  type        = string
  default     = "g4dn.xlarge"
}

# -----------------------------------------------------------------------------
# Container Images (SHA-pin in prod, mutable tag in dev)
# -----------------------------------------------------------------------------

variable "api_image_tag" {
  description = "ECR image tag for the FastAPI container. Defaults to 'latest' for dev ergonomics; production deploys MUST pass an immutable commit SHA via `-var=\"api_image_tag=<sha>\"` (or via CI/CD env override). The ECR repo `image_tag_mutability = MUTABLE` lets dev keep moving; prod stays SHA-pinned by convention, enforced at the deploy pipeline."
  type        = string
  default     = "latest"

  validation {
    condition     = length(var.api_image_tag) > 0
    error_message = "api_image_tag must be a non-empty string."
  }
}

variable "whisper_image_tag" {
  description = "Public Whisper ASR webservice image tag. Pinned to a specific version (not 'latest') for reproducibility — model weights bundled with the image, so a tag swap silently changes inference behavior."
  type        = string
  default     = "1.5.0"
}

# -----------------------------------------------------------------------------
# DNS + TLS (Phase 2)
# -----------------------------------------------------------------------------

variable "root_domain" {
  description = "Apex domain for the Route 53 hosted zone (e.g. 'aurionclinical.com'). All env-specific api_domain values live under this. Once the zone is created, point the registrar's NS records at the `route53_nameservers` output."
  type        = string
}

variable "api_domain" {
  description = "Fully qualified domain name for the API endpoint in this environment (e.g. 'api.aurionclinical.com' for prod, 'api-dev.aurionclinical.com' for dev). TLS cert is issued for this exact name; the ALB A-alias targets it."
  type        = string
}

variable "manage_root_zone" {
  description = "Whether this env's Terraform state owns the Route 53 hosted zone for root_domain. Set to true in EXACTLY ONE env (typically dev — the first env to apply). Other envs read the zone via data source. Zone has prevent_destroy enabled so a dev teardown won't take prod DNS with it."
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# WAF (Phase 2)
# -----------------------------------------------------------------------------

variable "waf_rate_limit_per_5min" {
  description = "WAFv2 rate-based rule threshold: max requests per 5-minute window per source IP. AWS allows 100..20,000,000. Pilot default is 2000 (~6.6 req/s sustained) — bump if clinicians hit it during sustained capture sessions."
  type        = number
  default     = 2000

  validation {
    condition     = var.waf_rate_limit_per_5min >= 100 && var.waf_rate_limit_per_5min <= 20000000
    error_message = "waf_rate_limit_per_5min must be between 100 and 20,000,000 per AWS WAF limits."
  }
}
