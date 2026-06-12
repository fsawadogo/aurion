## Task
Replace AWS SES with Resend as the transactional email sender (CTO: "use
Resend for the email service instead of SES"). Unblocks #76 (alert email
sink), #77 (compliance scheduled delivery), and half of #349 — all of which
were gated on SES production access (#399, DENIED).

## Why
SES production access was denied (#399) → SES stuck in sandbox (verified
recipients only), so password-reset email never reached arbitrary pilot
users and #76/#77 delivery couldn't ship. Resend is an HTTP email API with
no AWS-sandbox gate: verify a domain + use an API key, then send to anyone.

## Approach
- NEW `core/email_sender.py` — provider-agnostic `async send_email(to,
  subject, text_body, html_body, from_address)` dispatching by
  `EMAIL_PROVIDER` (default `resend`): Resend via httpx POST /emails
  (Bearer key); SES via boto3 (moved here, kept as an option). Lives in
  core/ so auth + alerts + compliance share it (CLAUDE.md no-cross-module).
  PHI/secret discipline: never logs recipient, body, or key — only provider
  + HTTP status / exception class.
- `auth/email.py` — keeps the dev log-only credential path + message
  builders; delegates transport to core.email_sender. boto3 SES client
  moves out.
- Terraform (dev): `secrets.tf` adds `aurion/$env/resend-api-key`
  (placeholder, ignore_changes — operator rotates the real key in);
  `ecs.tf` taskdef adds `EMAIL_PROVIDER=resend` env + `RESEND_API_KEY`
  secret. SES SNS/bounce plumbing (#399) left dormant, not removed.
- Safe to ship pre-key: forgot-password already swallows send failures
  (returns 204), so a placeholder key degrades to "logged failure", never
  a 500 or token leak — same posture as SES-sandbox failures today.

## Acceptance criteria
- [ ] AC-1: send_email routes to Resend by default; httpx POST carries
      {from,to,subject,text,html} + Bearer key — unit test.
- [ ] AC-2: EMAIL_PROVIDER=ses still works (boto3 send_email) — unit test.
- [ ] AC-3: missing RESEND_API_KEY / non-2xx / unknown provider → EmailSendError;
      recipient/body/key never logged — unit test.
- [ ] AC-4: password-reset dev log-only path unchanged; enabled path
      delegates to the sender — existing integration tests stay green.
- [ ] AC-5: terraform fmt + validate clean; 80% coverage; ruff clean.

## Out of scope
- Building the #76 alert-email + #77 compliance-delivery sinks (now
  UNBLOCKED — separate slices).
- Removing SES Terraform (identity/SNS/bounce) — left dormant.
- Provisioning the Resend account / verifying the domain / setting the API
  key — human steps (runbook: docs/runbooks/resend-email-setup.md).

## Test plan (executable)
1. cd backend && python3 -m pytest tests/unit/test_email_sender.py -q
2. cd backend && python3 -m pytest -q   (full unit suite, incl. password-reset)
3. cd infrastructure && terraform fmt -check && terraform validate

## Security implications
- API key only from Secrets Manager (never env/code/logs) — same rule as
  the AI provider keys.
- No PHI in email bodies (password-reset carries name + link only) or logs.
- Descriptive mode / audit / consent unaffected (transactional email only).
