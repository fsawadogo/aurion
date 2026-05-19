# Aurion — Terraform State Bootstrap

This module provisions the S3 bucket, DynamoDB lock table, and KMS key
that the main Terraform module (`../`) uses for remote state.

It exists because the main module can't store its own state in a bucket
it hasn't created yet — classic chicken-and-egg. The bootstrap is small,
runs once per AWS account, and its own state stays local.

## Prerequisites

- AWS credentials for the target account (`aws sts get-caller-identity`
  should show the right account ID).
- `terraform >= 1.5.0` on PATH.
- IAM permissions: S3 (create + tag bucket), DynamoDB (create table),
  KMS (create key + alias). The default `AdministratorAccess` role is
  sufficient.

## Apply (one-time per account)

```bash
cd infrastructure/bootstrap

terraform init
terraform plan
terraform apply   # ~30 seconds — creates KMS key, S3 bucket, DDB table
```

You should see four resources created: `aws_kms_key.state`,
`aws_kms_alias.state`, `aws_s3_bucket.state`,
`aws_dynamodb_table.locks` (plus the bucket sub-resources).

## Emit the backend config files

The main module reads its backend settings from
`../backends/{env}.s3.tfbackend`. Generate both:

```bash
terraform output -raw backend_dev  > ../backends/dev.s3.tfbackend
terraform output -raw backend_prod > ../backends/prod.s3.tfbackend
```

These files are gitignored (`../backends/.gitignore` allows only
`.gitignore` itself through). The account ID lives in them; treat as
private to the repo even though it's not strictly a secret.

## Migrate the main module to remote backend

After the bootstrap is applied and the `.tfbackend` files exist:

```bash
cd infrastructure
terraform init -reconfigure -backend-config=backends/dev.s3.tfbackend

# Confirm "yes" when Terraform offers to copy the local state to S3.
```

Verify with:

```bash
terraform plan -var-file=environments/dev.tfvars   # → No changes.
```

Switching to prod later:

```bash
terraform init -reconfigure -backend-config=backends/prod.s3.tfbackend
```

## What this module deliberately doesn't do

- **No `bucket` policy granting cross-account access.** The pilot is
  single-account; multi-account org-wide bootstrap is a later concern.
- **No object lock / WORM.** Compliance archive-mode isn't part of the
  pilot — the audit log itself lives in DynamoDB (immutable by app-code
  contract), not in this state bucket.
- **No remote backend for ITSELF.** The bootstrap's state is small and
  rarely changes. If the laptop running this dies, re-running
  `terraform import` against the existing AWS resources is recovery
  enough. Don't try to make it remotely backed — that's a recursion.

## Teardown (last resort)

State bucket has `force_destroy = false` and the lock table has
`deletion_protection_enabled = true`. To actually tear this down:

1. Move state of the main module elsewhere or `terraform destroy` first.
2. Manually empty the state bucket.
3. Disable DynamoDB deletion protection on the lock table.
4. `terraform destroy` here.

The friction is intentional.
