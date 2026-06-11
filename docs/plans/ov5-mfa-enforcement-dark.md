## Task
OV-5 — MFA enforcement MECHANISM (#397), ships dark

## Why
#397: TOTP MFA is opt-in today — a clinician who never enrolls logs in
with a password only. CLAUDE.md/pilot posture wants a second factor before
real PHI. This ships the MECHANISM so the CTO flips POLICY (not code)
before pilot. Global default OFF → byte-identical behavior on merge;
"enforce" is a per-user admin toggle the CTO sets.

## Approach
- models: `UserModel.mfa_required` (bool, default False, not null).
- migration 0037: add column default false.
- login gate (auth.py): a user with `mfa_required AND mfa_enrolled_at is
  None` cannot finish password login — return a new
  LoginEnrollmentRequiredResponse (enroll_required=true + a scoped
  enrollment challenge token, mirroring the mfa_challenge pattern) instead
  of tokens. Already-enrolled users keep the existing mfa_required
  challenge path unchanged.
- admin: UpdateUserRequest gains optional `mfa_required`; repo update_user
  handles it + emits it in the changes dict (USER_UPDATED audit already
  carries changes); UserResponse surfaces it. Portal Users page: a
  "Require MFA" toggle per row (web half).
- DARK: no global default flip, no auto-enable. The column is False for
  everyone until an admin toggles a user. Mechanism present, policy off.

## Acceptance criteria
- [ ] AC-1: login with mfa_required=True + not enrolled → enrollment-
      required response, NO tokens — pytest
- [ ] AC-2: login with mfa_required=False (default) → unchanged (tokens or
      existing mfa challenge if enrolled) — pytest
- [ ] AC-3: admin PATCH sets mfa_required + it lands in the USER_UPDATED
      changes dict — pytest
- [ ] AC-4: portal Users toggle calls updateUser with mfa_required — vitest
- [ ] AC-5: full backend + web suites green; migration single head 0037

## DRY / SOLID check
- Reuse: mint_mfa_challenge_token pattern (new mint_enrollment_token mirrors
  it), users_repo.update_user changes-dict, the migration-0036 nullable-add
  precedent, UpdateUserRequest/UserResponse.
- New: LoginEnrollmentRequiredResponse + mint/verify enrollment token —
  a distinct login outcome, not a third copy.
- iOS: n/a tonight (the iOS enrollment-required UI is day-work — needs a
  TestFlight build; the backend response is forward-compatible).

## Out of scope
- Global "require MFA for all CLINICIANs" policy (the CTO's call; this is
  per-user mechanism).
- iOS enrollment-required screen (TestFlight build → day work).

## Test plan (executable)
1. cd backend && python3 -m pytest tests/unit/test_auth*.py -q
2. cd backend && python3 -m pytest tests/unit -q && python3 -m alembic heads
3. cd web && npx vitest run tests/UsersPage*.spec.tsx && npx vitest run

## Security implications
Strengthens auth (adds an enforcement path); no PHI; audit USER_UPDATED
already records the toggle with actor. Default-off means zero behavior
change until the CTO opts a user in — safe to ship without the policy
decision.
