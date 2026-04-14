# =============================================================================
# Aurion Clinical AI — Terraform Root Configuration
# =============================================================================
# Replaces the AWS CDK TypeScript stack. Provisions all infrastructure for the
# Aurion MVP: VPC, ECS (Fargate + GPU), RDS PostgreSQL, DynamoDB, S3, Cognito,
# AppConfig, and CloudWatch monitoring.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # -------------------------------------------------------------------------
  # S3 Remote State Backend
  # Uncomment after creating the state bucket manually or via a bootstrap script:
  #   aws s3 mb s3://aurion-terraform-state-<ACCOUNT_ID> --region ca-central-1
  #   aws dynamodb create-table --table-name aurion-terraform-locks \
  #     --attribute-definitions AttributeName=LockID,AttributeType=S \
  #     --key-schema AttributeName=LockID,KeyType=HASH \
  #     --billing-mode PAY_PER_REQUEST --region ca-central-1
  # -------------------------------------------------------------------------
  # backend "s3" {
  #   bucket         = "aurion-terraform-state-<ACCOUNT_ID>"
  #   key            = "aurion/terraform.tfstate"
  #   region         = "ca-central-1"
  #   dynamodb_table = "aurion-terraform-locks"
  #   encrypt        = true
  # }
}

# =============================================================================
# AWS Provider
# =============================================================================

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project            = "aurion"
      Environment        = var.environment
      DataClassification = "phi-adjacent"
      ManagedBy          = "terraform"
    }
  }
}

# =============================================================================
# Data Sources
# =============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
