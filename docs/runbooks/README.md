# Aurion — Operational Runbooks

Used during real incidents and routine pilot operations. Each runbook
assumes the operator has `AWS_PROFILE=aurion-dev` set, is signed in
with MFA, and can read `.claude/state/backlog.md` for current context.

## Index

| Runbook | When to use |
|---|---|
| [incident-response.md](incident-response.md) | Something is broken in prod — error spike, ALB 5xx, service down, suspected breach |
| [dsar.md](dsar.md) | A patient / physician submits a Quebec Law 25 access or deletion request |
| [backup-restore-drill.md](backup-restore-drill.md) | Quarterly drill to prove RDS PITR actually restores. Pre-pilot **once**, then quarterly |
| [cognito-user-management.md](cognito-user-management.md) | Add / remove pilot users, reset MFA when a doctor loses their phone, force sign-out |
| [web-portal-deployment.md](web-portal-deployment.md) | First-time Amplify provisioning + deploy / rollback for the admin portal |
| [pilot-launch-checklist.md](pilot-launch-checklist.md) | Go / no-go review before first physician sign-in |

## Conventions

- **AWS region**: always `ca-central-1`. Commands that omit `--region` use the profile default.
- **AWS profile**: `aurion-dev` for the pilot. Production-GA migrates to IAM Identity Center per [the Phase 5 IIC plan](../../infrastructure/bootstrap/AWS_ACCOUNT_SETUP.md).
- **Severity levels** (see incident-response.md):
  - **SEV-1**: PHI exposure, total outage, consent gate bypass
  - **SEV-2**: degraded service, single-physician outage, masking failure on a single frame
  - **SEV-3**: cosmetic / non-PHI bug, slow but functional

## Maintenance

Runbooks rot fast. If you fix something here, also update the file —
a runbook that lies to the operator at 3am is worse than no runbook.
