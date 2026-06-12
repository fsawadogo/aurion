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

  validation {
    # Data-residency guardrail: every PHI store (S3 buckets, KMS keys, RDS,
    # DynamoDB) is created in var.region. An accidental tfvars override to a
    # US/EU region would silently relocate patient data out of Canada and
    # break the residency commitment. Pin to the ca-* prefix (ca-central-1
    # today, ca-west-1 if we ever add a second Canadian region).
    condition     = startswith(var.region, "ca-")
    error_message = "region must be a Canadian AWS region (ca-* prefix) for data residency."
  }
}

# -----------------------------------------------------------------------------
# Media Retention — S3 lifecycle TTL for raw audio + masked frames (#338)
# -----------------------------------------------------------------------------

variable "media_retention_days" {
  description = "Max-window TTL (in whole days) for the audio + frames S3 buckets' expiration lifecycle rules (#338). Dev uses 7 to give the eval team a review window over recent captures; prod stays at 1 (unchanged). S3 lifecycle expiration is whole-bucket and whole-day granular, so this is only the worst-case backstop ceiling — the precise deletion path is the app-level purge-on-approval that removes raw audio right after transcription and frames right after export. Raw audio is PHI, so the window is capped intentionally. Eval bucket is exempt (no lifecycle rule)."
  type        = number
  default     = 1
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
  description = "ECR image tag (immutable commit SHA) for the FastAPI container. REQUIRED — no default. CI passes the freshly-built SHA (`-var=\"api_image_tag=<sha>\"`); any out-of-band `terraform apply` must pass the CURRENTLY-DEPLOYED SHA (read it from `aws ecs describe-task-definition --task-definition aurion-api-<env> --query taskDefinition.containerDefinitions[0].image`). The default used to be 'latest', which silently shipped a STALE image on a bare apply (rev 100, 2026-06-07): its `alembic upgrade head` failed with \"Can't locate revision '0031'\" because :latest predated the live DB migration. Removing the default makes a bare apply fail fast instead of regressing the image (#326)."
  type        = string

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

variable "compliance_report_recipients" {
  description = "Comma-separated recipient list for the #77 scheduled compliance-report delivery notice (e.g. 'compliance@aurionclinical.com'). Empty = no-op (reports stay portal-only). Not a secret — plain addresses; injected as the COMPLIANCE_REPORT_RECIPIENTS task env. The notice carries metadata + a portal link only (never report bytes); delivery also requires the Resend email service configured."
  type        = string
  default     = ""
}

variable "amplify_github_access_token" {
  description = "Reserved for a future flip back to the Amplify GitHub source connector (platform = WEB_COMPUTE). Currently unused — the portal ships via the manual-deploy path (platform = WEB) driven by .github/workflows/web.yml + web/scripts/deploy.sh, which uploads a static bundle to Amplify via aws amplify create-deployment. Kept in the schema so the flip-back is a single PR (set the variable, change platform, restore build_spec) — no variable-rename churn."
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
