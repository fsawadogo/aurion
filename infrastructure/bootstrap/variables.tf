variable "region" {
  description = "AWS region for the state bucket + lock table. Match the main module's data-residency region (ca-central-1 for Quebec Law 25)."
  type        = string
  default     = "ca-central-1"
}
