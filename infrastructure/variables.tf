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
