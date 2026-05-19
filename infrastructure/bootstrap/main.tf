# =============================================================================
# Aurion — Terraform State Bootstrap
# =============================================================================
# Chicken-and-egg bootstrap: provisions the S3 bucket, DynamoDB lock table,
# and KMS key that the MAIN Terraform module (one directory up) uses as its
# remote backend.
#
# This bootstrap module is itself NOT remotely backed — its `terraform.tfstate`
# lives next to this file. The bootstrap state is small (4 resources, no
# secrets) and rarely changes, so the trade-off is acceptable: do one
# `terraform apply` per AWS account, commit nothing locally, and forget.
#
# Apply sequence is documented in README.md.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Intentionally NO `backend "s3" {}` here — this module IS the bucket.
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project            = "aurion"
      Component          = "terraform-state"
      DataClassification = "operational"
      ManagedBy          = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id     = data.aws_caller_identity.current.account_id
  state_bucket   = "aurion-terraform-state-${local.account_id}"
  lock_table     = "aurion-terraform-locks"
  kms_alias_name = "alias/aurion-terraform-state"
}
