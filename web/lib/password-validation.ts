/**
 * Single source of truth for client-side password rules in the web
 * portal (AUTH-EMAIL-RESET-WIRING).
 *
 * Mirrors the server-side Pydantic constraint
 * (`backend/app/api/v1/auth.py` → ResetPasswordRequest:
 * `Field(min_length=8, max_length=128)`). When the server rule
 * changes, change `PASSWORD_MIN_LENGTH` here in lockstep — the
 * server is always the authority but a UI that lets you submit an
 * obviously-too-short password and then surfaces the 422 is a worse
 * experience than catching it locally.
 *
 * The rules intentionally stay narrow — `min_length` + `matches
 * confirm`. Complexity rules (mixed case / digits / symbols) are
 * out of scope here; the backend doesn't enforce them and shoving
 * them into the UI would only diverge from the real policy.
 */

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 128;

export type PasswordValidationError =
  | "too_short"
  | "too_long"
  | "mismatch";

export interface PasswordCheck {
  ok: boolean;
  error?: PasswordValidationError;
}

/** Pure function — no side effects, easy to unit-test. */
export function validatePassword(
  newPassword: string,
  confirmPassword: string,
): PasswordCheck {
  if (newPassword.length < PASSWORD_MIN_LENGTH) {
    return { ok: false, error: "too_short" };
  }
  if (newPassword.length > PASSWORD_MAX_LENGTH) {
    return { ok: false, error: "too_long" };
  }
  if (newPassword !== confirmPassword) {
    return { ok: false, error: "mismatch" };
  }
  return { ok: true };
}
