# Runbook — Resend email setup (replaces SES)

Aurion sends transactional email (password reset today; alert delivery #76
and compliance-report delivery #77 once they build on this) via
**Resend** instead of AWS SES. SES production access was denied (#399), so
SES is stuck in its sandbox (verified recipients only). Resend has no
AWS-sandbox gate: verify a sending domain, create an API key, send to
anyone.

The code + Terraform are already in place (`app/core/email_sender.py`,
`EMAIL_PROVIDER=resend`, the `aurion/<env>/resend-api-key` secret + taskdef
wiring). What remains are the **account / domain / key** steps below — they
need a human with Resend + DNS access. Until the key is set, sends fail
gracefully (forgot-password still returns 204 and logs a redacted failure);
nothing 500s and no token leaks.

## 1. Create the Resend account + verify the sending domain
1. Sign up at https://resend.com (use the Aurion ops account).
2. **Domains → Add Domain → `aurionclinical.com`** (or a subdomain like
   `mail.aurionclinical.com`).
3. Resend shows DNS records to add (SPF `TXT`, DKIM `CNAME`/`TXT`, and a
   `MX`/return-path for bounces). Add them at the `aurionclinical.com` DNS
   provider and wait for Resend to mark the domain **Verified**.
   - The `AUTH_EMAIL_FROM` value (`noreply@aurionclinical.com`) must be on
     this verified domain.

## 2. Create an API key
1. **API Keys → Create API Key** — scope **Sending access**, name it
   `aurion-<env>` (e.g. `aurion-dev`).
2. Copy the `re_…` value (shown once).

## 3. Put the key in Secrets Manager
The ECS task reads `RESEND_API_KEY` from `aurion/<env>/resend-api-key`
(created by Terraform with a placeholder; `ignore_changes` keeps Terraform
from clobbering the real value):

```bash
aws secretsmanager put-secret-value \
  --region ca-central-1 \
  --secret-id aurion/dev/resend-api-key \
  --secret-string "re_your_real_key_here"
```

Pass the key via `--secret-string` from a file or a secrets manager, never
inline in shell history if you can avoid it. **Never** paste it into a
commit, a log, or a run-task command (the #398 leak vector).

## 4. Roll the task so it picks up the key
ECS injects secrets at task start, so force a new deployment (or let the
next `main` merge redeploy):

```bash
aws ecs update-service --region ca-central-1 \
  --cluster aurion-dev --service <api-service> --force-new-deployment
```

## 5. Verify delivery
- Trigger a password reset for a real address and confirm it arrives.
- Check the task logs for `Email sent via Resend (recipient redacted)` (the
  success line is intentionally PHI-free).

## Config reference
| Setting | Where | Value |
|---|---|---|
| `AUTH_EMAIL_ENABLED` | taskdef env | `true` (prod/dev); `false` locally = log-only |
| `EMAIL_PROVIDER` | taskdef env | `resend` (default) · `ses` to fall back |
| `AUTH_EMAIL_FROM` | taskdef env | `noreply@aurionclinical.com` (on the verified domain) |
| `RESEND_API_KEY` | Secrets Manager → taskdef secret | the `re_…` key |
| `RESEND_API_BASE` | env (optional) | defaults to `https://api.resend.com` |

## Notes
- **SES is not removed** — `EMAIL_PROVIDER=ses` still works, and the SES
  identity / SNS bounce plumbing (#399) is left in Terraform, dormant. We
  can delete it once Resend is proven in the pilot.
- **#76 / #77 are now unblocked** — the alert-email sink and the compliance
  scheduled-delivery legs can call `app.core.email_sender.send_email(...)`
  directly; they were the slices gated on SES production access.
