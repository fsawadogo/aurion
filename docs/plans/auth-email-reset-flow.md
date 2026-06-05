# AUTH-EMAIL-RESET-WIRING — web pages + ECS env + SES IAM

**Lane:** web · **Branch:** `lane-web/auth-email-reset-flow`
**Linked work:** PR #234 (backend auth-pivot) shipped
`/auth/forgot-password` + `/auth/reset-password` but the email-sending +
landing-page sides are unwired. This plan closes them.

## Task

`AUTH-EMAIL-RESET-WIRING` — wire the self-serve password-reset flow
end-to-end so the moment SES is verified for `aurionclinical.com` the
flow works for pilot users.

## Why

Marie + Perry + Uzziel + Freddy + Antoine receive temp passwords from
the CTO. If any of them forgets it during the pilot, the only unblock
is what this PR ships: a `/forgot-password` page that hits the existing
backend route, an SES-sent email containing a link that lands on a new
`/reset-password` page, and the IAM + env-var glue that lets the
backend actually send the email.

Quotes the constraint from CLAUDE.md → "Audit log: append-only. No
update or delete. Ever." and "PHI never in logs, errors, API
responses". Reset tokens are credential material; the same hygiene
applies.

## Approach

**Files touched:**

- `web/lib/api.ts` — add `requestPasswordReset(email)` +
  `resetPassword(token, newPassword)` helpers. ONE pair of helpers for
  both pages.
- `web/components/auth/AuthScreenShell.tsx` (new) — the shared premium
  chrome (gold halo, navy gradient, logo lockup, card) that login,
  forgot-password, and reset-password all render inside. Dedupes the
  big JSX block in login/page.tsx.
- `web/lib/password-validation.ts` (new) — ONE rule: 8+ chars, matches
  confirm. Used by reset-password page (and lined up for iOS-side
  reuse via the same length constant).
- `web/app/(auth)/login/page.tsx` — refactor to use AuthScreenShell;
  add "Forgot password?" link; surface `?reset=success` toast.
- `web/app/(auth)/forgot-password/page.tsx` (new) — email field +
  account-existence-neutral confirmation.
- `web/app/(auth)/reset-password/page.tsx` (new) — `?token=` consume,
  new+confirm password, POST `/api/v1/auth/reset-password`, redirect
  on 204.
- `web/messages/en.json` + `fr.json` — `Auth.resetPassword.*`,
  `Auth.forgotPassword.*`, `Auth.loginToast.*` namespaces.
- `infrastructure/ecs.tf` — three new `environment` entries on the
  `aurion-api` container: `AUTH_EMAIL_ENABLED`, `AUTH_EMAIL_FROM`,
  `AUTH_PASSWORD_RESET_URL_BASE` (NOTE: backend reads
  `AUTH_PASSWORD_RESET_URL_BASE`, NOT `AUTH_RESET_LINK_BASE_URL` per
  `backend/app/modules/auth/email.py:48` — task spec was off by one
  name; matched to actual code).
- `infrastructure/ecs.tf` — new `aws_iam_role_policy` attached to
  `aws_iam_role.api_task` granting `ses:SendEmail`/`ses:SendRawEmail`
  scoped to the `aurionclinical.com` identity ARN.
- `web/tests/ResetPasswordPage.spec.tsx`,
  `ForgotPasswordPage.spec.tsx`, `LoginResetToast.spec.tsx` —
  regression suite.

## Acceptance criteria

- [ ] AC-1: `/forgot-password` route renders the premium UI, accepts
  an email, POSTs to `/api/v1/auth/forgot-password`, then ALWAYS shows
  the same neutral confirmation regardless of API response (verified
  by `ForgotPasswordPage.spec.tsx`).
- [ ] AC-2: `/reset-password?token=<t>` renders the new-password form;
  `/reset-password` (no token) renders an error banner with no form
  (verified by `ResetPasswordPage.spec.tsx`).
- [ ] AC-3: password < 8 chars OR mismatch with confirm → inline error,
  zero API calls (verified by `ResetPasswordPage.spec.tsx`).
- [ ] AC-4: happy path POST → 204 → `router.push('/login?reset=success')`
  (verified by `ResetPasswordPage.spec.tsx`).
- [ ] AC-5: backend 400 `Invalid or expired reset token.` →
  surfaces the message inline; "expired" / "consumed" hint text appears
  (verified by `ResetPasswordPage.spec.tsx`).
- [ ] AC-6: `/login?reset=success` → green toast at top of login,
  auto-dismisses after 5s (verified by `LoginResetToast.spec.tsx`).
- [ ] AC-7: EN + FR catalogs both contain `Auth.resetPassword.*` and
  `Auth.forgotPassword.*` namespaces with matching key sets (verified
  by i18n parity tests in each spec file).
- [ ] AC-8: `terraform plan -var-file=environments/dev.tfvars` shows
  exactly two adds: container env block expanded with the three
  `AUTH_EMAIL_*` vars + new `aws_iam_role_policy.api_task_ses`.
- [ ] AC-9: `cd web && npm run lint` clean,
  `cd web && npm run build` clean static export,
  `cd web && npx vitest run` all pass.

## DRY / SOLID check

- **Existing helpers to reuse**: `fetchWithAuth` (not used — these
  endpoints are public), `Button`, `AurionLogoLockup`,
  `withIntl` test helper, the `useTranslations` next-intl wrapper, the
  `aurion-chrome-navy` + `form-input` Tailwind utilities, the
  `useRouter` + `useSearchParams` mock pattern from PatientDetailPage
  spec.
- **New helpers introduced?**:
  1. `requestPasswordReset` + `resetPassword` in `lib/api.ts` — these
     are the FIRST two public-auth endpoints from the portal, so the
     helpers themselves aren't a "third copy"; they're the canonical
     one.
  2. `AuthScreenShell` — this IS the third copy of the auth chrome
     (login, forgot-password, reset-password), so it justifies the
     abstraction per §6c.
  3. `lib/password-validation.ts` — ONE rule for the web side. The
     backend already enforces 8-128 via Pydantic
     (`ResetPasswordRequest.new_password: Field(min_length=8,
     max_length=128)`), so the web check matches.
- **iOS UI tasks only — `mobile-ios-design` consulted**: n/a (web
  lane).

## Out of scope

- SES domain verification + DKIM tokens (CTO is doing this out-of-band
  at Cloudflare).
- SES individual recipient verification (CTO is collecting + submitting
  the 5 pilot emails to SES sandbox).
- SES production-access request (separate AWS support ticket post-pilot
  if needed; sandbox handles the 5 pilot users).
- iOS-side reset flow (iOS uses TestFlight + temp passwords; if pilot
  iOS users hit a forgot path, they fall back to the web portal which
  this PR ships).
- Backend changes — PR #234 already shipped the routes.
- AppConfig hosted version updates (CLI-managed; orthogonal concern
  per `memory/reference-appconfig-cli-managed`).

## Test plan (executable)

1. `cd web && npm run lint`
2. `cd web && npm run build`
3. `cd web && npx vitest run tests/ResetPasswordPage.spec.tsx tests/ForgotPasswordPage.spec.tsx tests/LoginResetToast.spec.tsx`
4. `cd web && npx vitest run` (full regression)
5. `cd infrastructure && terraform fmt -check`
6. `cd infrastructure && terraform validate`
7. `cd infrastructure && terraform plan -var-file=environments/dev.tfvars | tail -40` — verify ONLY the three env-var adds + the new IAM policy.
8. Manual visual smoke: `cd web && npm run dev`, visit
   `/forgot-password` and `/reset-password?token=test` — both render the
   premium UI, both submit and fail gracefully without a backend.

## Security implications

- Reset tokens (raw, query-string-borne) are credential material. The
  reset-password page MUST NOT echo the token in any
  log/console/analytics. The page reads the token via
  `useSearchParams`, holds it in component state, sends it once in the
  POST body, never logs it.
- The forgot-password confirmation copy is account-existence-neutral
  ("If that email is on file, a reset link is on its way."). Backend
  already returns 204 in both branches; the web copy must not leak the
  branch.
- The SES IAM policy scopes `ses:SendEmail` to the verified identity
  ARN (`identity/aurionclinical.com` + `identity/*@aurionclinical.com`),
  not `*`. A bug or attacker that injects an arbitrary `From:` address
  still can't relay through SES.
- Backend audit events `PASSWORD_RESET_REQUESTED` + `PASSWORD_CHANGED`
  carry `target_user_id` only, never the token or the email; verified
  in `backend/app/api/v1/auth.py:467-505`.

## Pre-merge checklist (human action required)

- [ ] SES domain identity `aurionclinical.com` verified in
      `ca-central-1` (DKIM tokens added to Cloudflare DNS).
- [ ] 5 pilot recipient emails verified at SES sandbox level (perry,
      marie, uzziel, freddy, antoine).
- [ ] SES production-access requested if pilot grows past 5 users
      (otherwise sandbox is fine).
- [ ] Post-merge smoke: hit `/forgot-password` with a verified email,
      check inbox, click link, set new password, sign in.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
