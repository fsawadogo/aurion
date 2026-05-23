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

variable "api_domain" {
  description = "Fully qualified domain name for this env's API endpoint (e.g. 'api.aurionclinical.com' for prod, 'api-dev.aurionclinical.com' for dev). Used as BOTH the Route 53 hosted-zone name AND the apex A-alias inside that zone. TLS cert is issued for this exact name. The apex (aurionclinical.com) is managed at Cloudflare; each env delegates ONLY its subdomain to Route 53 by setting 4 NS records at Cloudflare for var.api_domain."
  type        = string
}

# -----------------------------------------------------------------------------
# Web Portal — Amplify Hosting (W010)
# -----------------------------------------------------------------------------

variable "web_portal_subdomain" {
  description = "Fully qualified domain name for the web admin portal (e.g. 'portal-dev.aurionclinical.com' for dev, 'portal.aurionclinical.com' for prod). Same delegation pattern as var.api_domain — apex stays at Cloudflare, this subdomain delegates 4 NS records to Route 53 (zone created by amplify.tf)."
  type        = string
  default     = "portal-dev.aurionclinical.com"
}

variable "amplify_github_access_token" {
  description = "Classic GitHub PAT with 'repo' scope for the AWS Amplify GitHub source connector. Set via TF_VAR_amplify_github_access_token in the deploy environment — never check into VCS. Required only for the initial Amplify app creation; rotation is via Amplify console, not Terraform. Leave null to skip the app+branch resources (lets the rest of the module plan cleanly while this is being provisioned)."
  type        = string
  default     = null
  sensitive   = true
}

# -----------------------------------------------------------------------------
# WAF (Phase 2)
# -----------------------------------------------------------------------------

variable "alerts_email" {
  description = "Email address that receives CloudWatch alarm notifications via SNS. Subscription is created in pending-confirmation state — confirm via the email link before alarms can route. Pre-pilot a single ops mailbox is fine; pre-GA route to PagerDuty / Opsgenie instead."
  type        = string
  default     = "faical.sawadogo@aurionclinical.com"
}

variable "waf_rate_limit_per_5min" {
  description = "WAFv2 rate-based rule threshold: max requests per 5-minute window per source IP. AWS allows 100..20,000,000. Pilot default is 2000 (~6.6 req/s sustained) — bump if clinicians hit it during sustained capture sessions."
  type        = number
  default     = 2000

  validation {
    condition     = var.waf_rate_limit_per_5min >= 100 && var.waf_rate_limit_per_5min <= 20000000
    error_message = "waf_rate_limit_per_5min must be between 100 and 20,000,000 per AWS WAF limits."
  }
}
