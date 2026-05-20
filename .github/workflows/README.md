# GitHub Actions — Aurion CI/CD

Three workflows:

| File | Trigger | What it does |
|---|---|---|
| `ci.yml` | PR + push to main | lint + test always. On main: build + push image to ECR + `terraform apply` against dev. |
| `deploy-prod.yml` | manual `workflow_dispatch` | Deploys a specific image tag to prod via `terraform apply -var-file=prod.tfvars`. Gated by GitHub Environment approval. |
| `ios-testflight.yml` | PR + push to main (paths `ios/**`) | iPhone-simulator build always. On main: archive + export + TestFlight upload (skips silently if Apple Dev secrets are unset). |

Authentication is **OIDC-only** — no long-lived AWS keys live in
GitHub Secrets. The IAM roles + OIDC trust are provisioned by
`infrastructure/github_oidc.tf`.

## Required GitHub Secrets

Set these in **Settings → Secrets and variables → Actions → Repository secrets**.

### AWS deploy (set after the Phase 1 + Phase 2 + Phase 3 Terraform applies)

| Secret | Value | Source |
|---|---|---|
| `AWS_ACCOUNT_ID` | 12-digit account ID (no dashes) | `aws sts get-caller-identity --query Account --output text` |
| `AWS_DEPLOY_ROLE_DEV` | ARN of `AurionGitHubDeployerDev` | `terraform output github_deployer_dev_role_arn` |
| `AWS_DEPLOY_ROLE_PROD` | ARN of `AurionGitHubDeployerProd` | `terraform output github_deployer_prod_role_arn` |
| `ECR_REGISTRY` | `<account_id>.dkr.ecr.ca-central-1.amazonaws.com` | `terraform output ecr_registry` |

### App Store Connect (set after Apple Developer Program membership is active, ~48h after payment)

| Secret | Value | Source |
|---|---|---|
| `APP_STORE_CONNECT_KEY_ID` | 10-char key identifier | App Store Connect → Users and Access → Integrations → Keys → "Aurion CI" key |
| `APP_STORE_CONNECT_ISSUER_ID` | UUID | Same screen, top of the Keys tab |
| `APP_STORE_CONNECT_KEY_P8` | base64-encoded `.p8` file | `base64 -i AuthKey_XXXXXX.p8 \| pbcopy` after downloading the .p8 from App Store Connect |

The `.p8` file is downloadable **exactly once** when the key is created.
Re-download is not possible; if you lose it, revoke and create a new key.

**Role required**: "Admin" (or "App Manager" if you want narrower scope —
both can upload to TestFlight).

## GitHub Environment setup (one-time, for prod gate)

Repo **Settings → Environments → New environment** → name it `prod`.
Add a protection rule:

- **Required reviewers**: yourself (+ anyone else who should approve prod deploys)
- **Wait timer**: 0 min (the manual approval is the gate; a timer just adds friction)
- **Deployment branches**: select "Selected branches", add `main`

This is what makes the prod deploy actually require human approval —
the OIDC trust on `AurionGitHubDeployerProd` keys off
`environment:prod` in the OIDC subject claim.

## Order of operations after the first AWS apply

1. Run the bootstrap (`infrastructure/bootstrap/`) — one-time.
2. Apply Phase 2 dev (`infrastructure/`, dev.tfvars) — issues TLS cert, sets up WAF, creates OIDC provider + roles.
3. `terraform output` to get the role ARNs + ECR registry — set as GitHub Secrets.
4. Create the `prod` GitHub Environment with required reviewer.
5. Push to main → watch `ci.yml` deploy to dev automatically.
6. After ~48h, get App Store Connect API key, set the 3 Apple secrets, watch `ios-testflight.yml` upload on the next iOS-touching push.
7. When ready to ship prod: manual `Deploy — Prod` workflow run, pick an image tag, approve in the environment gate.
