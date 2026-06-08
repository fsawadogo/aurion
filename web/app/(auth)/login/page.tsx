"use client";

import { AlertCircle, CheckCircle2, Eye, EyeOff } from "lucide-react";
// Single-path login against the backend bcrypt-JWT API (`/api/v1/auth/login`)
// — the same auth system the iOS app and backend use. Cognito was removed
// from the portal (re-added post-MVP); see docs/plans/auth-pivot-web.md.
//   * Success      → tokens stored, route by `user.role`.
//   * mfa_required → prompt for the 6-digit TOTP code, then
//                    `/api/v1/auth/mfa/verify-login`.
//   * `?reset=success` query param → green confirmation toast.
//
// IS_LOCAL only gates the optional "local dev credentials" hint panel
// (the APP_ENV=local seed accounts); it no longer changes the auth path.

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import Button from "@/components/ui/Button";
import AuthScreenShell from "@/components/auth/AuthScreenShell";
import { login, verifyMfaLogin } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const IS_LOCAL =
  API_BASE.includes("localhost") || API_BASE.includes("127.0.0.1");

const RESET_TOAST_AUTO_DISMISS_MS = 5_000;

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginContent />
    </Suspense>
  );
}

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tToast = useTranslations("Auth.loginToast");
  const tAuth = useTranslations("Auth.forgotPassword");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [resetToastVisible, setResetToastVisible] = useState(false);
  // Set once the backend returns mfa_required — switches the form to the
  // TOTP-code step. Holds the short-lived challenge token.
  const [mfaChallenge, setMfaChallenge] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");

  // Show the "Password reset" toast iff arriving with ?reset=success.
  // Auto-dismiss after 5s — the user is already on the login form, so
  // the toast is a confirmation, not a CTA.
  useEffect(() => {
    if (searchParams?.get("reset") === "success") {
      setResetToastVisible(true);
      const id = setTimeout(
        () => setResetToastVisible(false),
        RESET_TOAST_AUTO_DISMISS_MS,
      );
      return () => clearTimeout(id);
    }
  }, [searchParams]);

  // CLINICIAN lands on the portal; everyone else gets the admin
  // /dashboard, which the admin/eval/compliance pages route off.
  function routeAfterAuth(role: string) {
    router.push(role === "CLINICIAN" ? "/portal/dashboard" : "/dashboard");
    router.refresh();
  }

  function describeError(err: unknown, opts?: { mfa?: boolean }): string {
    const msg = err instanceof Error ? err.message : "Sign-in failed";
    if (/Failed to fetch|NetworkError|Load failed/i.test(msg)) {
      return IS_LOCAL
        ? `Cannot reach the backend at ${API_BASE}. Is \`docker-compose up\` running?`
        : "Couldn't reach Aurion. Check your network and try again.";
    }
    // Backend 429 lockout — keep its distinct "~N minutes" hint rather
    // than collapsing into the generic invalid-credentials line.
    if (/Too many failed sign-in attempts/i.test(msg)) {
      return msg.replace(/^Login failed:\s*/, "");
    }
    if (/401|Invalid email or password/i.test(msg)) {
      // On the 2FA step the backend reuses the generic credentials detail
      // for a bad/expired code — reword it for the code context.
      return opts?.mfa
        ? "Incorrect or expired code. Try again, or go back to sign in."
        : "Invalid email or password.";
    }
    return msg.replace(/^Login failed:\s*/, "");
  }

  // Abandon the MFA step and return to the email/password form (e.g. the
  // 5-minute challenge token expired, or the user picked the wrong account).
  function backToSignIn() {
    setMfaChallenge(null);
    setMfaCode("");
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await login(email.trim().toLowerCase(), password);
      if ("mfa_required" in result) {
        // Switch to the TOTP step — no tokens issued yet.
        setMfaChallenge(result.mfa_challenge_token);
        setLoading(false);
        return;
      }
      routeAfterAuth(result.user.role);
    } catch (err) {
      setError(describeError(err));
      setLoading(false);
    }
  }

  async function handleMfaSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!mfaChallenge) return;
    setError(null);
    setLoading(true);
    try {
      const auth = await verifyMfaLogin(mfaChallenge, mfaCode.trim());
      routeAfterAuth(auth.user.role);
    } catch (err) {
      setError(describeError(err, { mfa: true }));
      setLoading(false);
    }
  }

  const resetToast = resetToastVisible ? (
    <div
      role="status"
      data-testid="login-reset-success-toast"
      className="mb-4 flex items-start gap-2 rounded-aurion-md bg-green-50 px-3.5 py-3 text-[13px] text-green-800 ring-1 ring-inset ring-green-600/15 animate-aurion-slide-up"
    >
      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
      <span className="leading-snug">{tToast("resetSuccess")}</span>
    </div>
  ) : null;

  return (
    <AuthScreenShell slot={resetToast}>
      <h2 className="aurion-title-3 mb-1.5">
        {mfaChallenge ? "Two-factor authentication" : "Sign in"}
      </h2>
      <p className="aurion-caption mb-6">
        {mfaChallenge
          ? "Enter the 6-digit code from your authenticator app."
          : "Use your Aurion email and password."}
      </p>

      {error && (
        <div
          role="alert"
          className="mb-5 flex items-start gap-2 rounded-aurion-md bg-red-50 px-3.5 py-3 text-[13px] text-red-700 ring-1 ring-inset ring-red-600/15"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
          <span className="leading-snug">{error}</span>
        </div>
      )}

      {mfaChallenge ? (
        <form
          onSubmit={handleMfaSubmit}
          className="space-y-4"
          data-testid="login-mfa-form"
        >
          <label className="block">
            <span className="aurion-micro mb-1.5 block">
              Authentication code
            </span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]*"
              maxLength={6}
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ""))}
              autoFocus
              required
              disabled={loading}
              placeholder="123456"
              className="form-input text-center tracking-[0.4em]"
            />
          </label>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={loading}
            fullWidth
            className="mt-2"
          >
            Verify
          </Button>
          <button
            type="button"
            onClick={backToSignIn}
            disabled={loading}
            className="mx-auto block text-[12.5px] font-medium text-navy-500 hover:text-navy-800 transition-colors duration-short disabled:opacity-50"
          >
            Back to sign in
          </button>
        </form>
      ) : (
      <form onSubmit={handleSubmit} className="space-y-4">
        <label className="block">
          <span className="aurion-micro mb-1.5 block">Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            autoFocus
            required
            disabled={loading}
            placeholder="you@aurionclinical.com"
            className="form-input"
          />
        </label>

        <label className="block">
          <span className="aurion-micro mb-1.5 block">Password</span>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              disabled={loading}
              className="form-input pr-11"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-navy-400 hover:text-navy-700 transition-colors duration-short"
              tabIndex={-1}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </label>

        <div className="flex justify-end">
          <Link
            href="/forgot-password"
            data-testid="login-forgot-password-link"
            className="text-[12.5px] font-medium text-navy-500 hover:text-navy-800 transition-colors duration-short"
          >
            {tAuth("title").replace("?", "")}?
          </Link>
        </div>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          loading={loading}
          fullWidth
          className="mt-2"
        >
          Sign in
        </Button>
      </form>
      )}

      {!mfaChallenge && IS_LOCAL && (
        <details className="group mt-6 rounded-aurion-md bg-canvas px-3.5 py-3 ring-1 ring-inset ring-hairline">
          <summary className="cursor-pointer text-[12.5px] font-semibold text-navy-700 marker:hidden flex items-center justify-between">
            <span>Local dev credentials</span>
            <span className="text-navy-300 group-open:rotate-180 transition-transform duration-short">
              ▾
            </span>
          </summary>
          <ul className="mt-3 space-y-1.5 text-[12px] font-mono text-navy-700">
            <DevCredRow role="ADMIN" email="admin@aurionclinical.com" pw="admin" />
            <DevCredRow role="CLINICIAN" email="perry@creoq.ca" pw="perry" />
            <DevCredRow role="CLINICIAN" email="marie@creoq.ca" pw="marie" />
            <DevCredRow role="COMPLIANCE" email="compliance@aurionclinical.com" pw="compliance" />
            <DevCredRow role="EVAL" email="eval@aurionclinical.com" pw="eval" />
          </ul>
          <p className="mt-2.5 text-[11px] text-navy-400">
            Seeded by the backend when <code>APP_ENV=local</code>.
          </p>
        </details>
      )}
    </AuthScreenShell>
  );
}

function DevCredRow({
  role,
  email,
  pw,
}: {
  role: string;
  email: string;
  pw: string;
}) {
  return (
    <li className="flex items-baseline gap-2">
      <span className="inline-flex shrink-0 items-center rounded-aurion-xs bg-navy-50 px-1.5 py-0.5 text-[9.5px] font-bold tracking-wider text-navy-600 uppercase">
        {role}
      </span>
      <span>{email}</span>
      <span className="text-navy-300">/</span>
      <span className="text-navy-500">{pw}</span>
    </li>
  );
}
