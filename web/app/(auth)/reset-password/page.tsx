"use client";

import { Suspense, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertCircle, Eye, EyeOff } from "lucide-react";
import { useTranslations } from "next-intl";
import Button from "@/components/ui/Button";
import AuthScreenShell from "@/components/auth/AuthScreenShell";
import { resetPassword } from "@/lib/api";
import {
  PASSWORD_MIN_LENGTH,
  validatePassword,
} from "@/lib/password-validation";

/**
 * Reset-password page (AUTH-EMAIL-RESET-WIRING).
 *
 * Step 1 (mount): pull `?token=<token>` off the URL.
 *   - missing → error banner, no form.
 *   - present → show the new-password form.
 *
 * Step 2 (submit): validate locally (8+ chars, matches confirm),
 *   POST to `/api/v1/auth/reset-password`, on 204 redirect to
 *   `/login?reset=success` so the next screen shows the success
 *   toast.
 *
 * Security:
 *  - The raw token is read once into component state from
 *    useSearchParams, sent verbatim in the POST body, then dropped.
 *  - The token is NEVER rendered into the DOM (not even hidden) and
 *    NEVER logged.
 *  - The user's email is NOT echoed — the user-to-token binding lives
 *    server-side; the form just asks for the new password.
 *  - 4xx errors map to friendly hints that suggest requesting a new
 *    link; the backend's `detail` field is shown verbatim above the
 *    hint so the user knows what happened.
 *
 * `useSearchParams` requires a Suspense boundary in static-export
 * builds; the page-level `<Suspense>` here keeps `next build`
 * happy without forcing the surrounding shell to be a client tree
 * with no SSR fallback.
 */

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordContent />
    </Suspense>
  );
}

function ResetPasswordContent() {
  const t = useTranslations("Auth.resetPassword");
  const searchParams = useSearchParams();
  // useSearchParams returns null in static-export builds before
  // hydration; default to empty string so the missing-token branch
  // fires consistently in both SSR and CSR.
  const token = useMemo(
    () => searchParams?.get("token") ?? "",
    [searchParams],
  );

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  // Inline validation errors (local, before any API call) use a
  // discriminated `localError` key; API errors flow through
  // `apiError` and `apiErrorHint` so the error UI can show the
  // backend's detail + a context hint without conflating the two.
  const [localError, setLocalError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [apiErrorHint, setApiErrorHint] = useState<string | null>(null);

  // No token in URL → render the error banner; never the form.
  if (!token) {
    return (
      <AuthScreenShell>
        <h2 className="aurion-title-3 mb-1.5">{t("missingTokenTitle")}</h2>
        <p className="aurion-caption mb-6">{t("missingTokenBody")}</p>
        <div className="mt-2 text-center">
          <Link
            href="/login"
            className="text-[13px] font-medium text-navy-600 hover:text-navy-800 transition-colors duration-short"
          >
            ← {t("backToSignIn")}
          </Link>
        </div>
      </AuthScreenShell>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    setApiError(null);
    setApiErrorHint(null);

    const check = validatePassword(newPassword, confirmPassword);
    if (!check.ok) {
      // Map the validation error key to a localized string. The
      // mapping lives here (not in the validator) so the validator
      // stays pure / testable.
      const key =
        check.error === "too_short"
          ? "errors.tooShort"
          : check.error === "too_long"
            ? "errors.tooLong"
            : "errors.mismatch";
      setLocalError(t(key));
      return;
    }

    setLoading(true);
    try {
      await resetPassword(token, newPassword);
      // Success → bounce to login with the success flag. We use
      // window.location (not the Next router) here because the login
      // page lives in a different route group; static-export routing
      // has been finicky with cross-group navigation in this codebase
      // (see commit b20910a — "bypass Next router for dynamic-route
      // navigation under static export"), and a `router.push` can
      // stall the post-success bounce under the Amplify static export.
      // The static /login HTML still ships from the same domain so
      // this is a single-page-app boundary, not a network hop.
      window.location.assign("/login?reset=success");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      setApiError(msg || t("errors.transport"));
      // Tail-classify the backend message → friendlier hint. The
      // detail string itself ("Invalid or expired reset token.") is
      // accurate but generic; the hint tells the user what to do
      // next.
      if (/expired/i.test(msg)) {
        setApiErrorHint(t("errors.expiredHint"));
      } else if (/used|consumed/i.test(msg)) {
        setApiErrorHint(t("errors.usedHint"));
      } else if (/invalid/i.test(msg)) {
        setApiErrorHint(t("errors.invalidHint"));
      }
      setLoading(false);
    }
  }

  return (
    <AuthScreenShell>
      <h2 className="aurion-title-3 mb-1.5">{t("title")}</h2>
      <p className="aurion-caption mb-6">{t("subtitle")}</p>

      {(localError || apiError) && (
        <div
          role="alert"
          data-testid="reset-password-error"
          className="mb-5 flex items-start gap-2 rounded-aurion-md bg-red-50 px-3.5 py-3 text-[13px] text-red-700 ring-1 ring-inset ring-red-600/15"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
          <span className="leading-snug">
            {localError || apiError}
            {apiErrorHint && (
              <span className="mt-1 block text-red-600">{apiErrorHint}</span>
            )}
          </span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <label className="block">
          <span className="aurion-micro mb-1.5 block">
            {t("newPasswordLabel")}
          </span>
          <div className="relative">
            <input
              type={showNew ? "text" : "password"}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              autoFocus
              required
              disabled={loading}
              minLength={PASSWORD_MIN_LENGTH}
              className="form-input pr-11"
              data-testid="reset-password-new-input"
            />
            <button
              type="button"
              onClick={() => setShowNew((v) => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-navy-400 hover:text-navy-700 transition-colors duration-short"
              tabIndex={-1}
              aria-label={showNew ? "Hide password" : "Show password"}
            >
              {showNew ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </label>

        <label className="block">
          <span className="aurion-micro mb-1.5 block">
            {t("confirmPasswordLabel")}
          </span>
          <div className="relative">
            <input
              type={showConfirm ? "text" : "password"}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
              disabled={loading}
              minLength={PASSWORD_MIN_LENGTH}
              className="form-input pr-11"
              data-testid="reset-password-confirm-input"
            />
            <button
              type="button"
              onClick={() => setShowConfirm((v) => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-navy-400 hover:text-navy-700 transition-colors duration-short"
              tabIndex={-1}
              aria-label={showConfirm ? "Hide password" : "Show password"}
            >
              {showConfirm ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </label>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          loading={loading}
          fullWidth
          className="mt-2"
        >
          {loading ? t("submitting") : t("submit")}
        </Button>
      </form>

      <div className="mt-6 text-center">
        <Link
          href="/login"
          className="text-[13px] font-medium text-navy-600 hover:text-navy-800 transition-colors duration-short"
        >
          ← {t("backToSignIn")}
        </Link>
      </div>
    </AuthScreenShell>
  );
}
