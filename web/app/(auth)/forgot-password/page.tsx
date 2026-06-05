"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertCircle, MailCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Button from "@/components/ui/Button";
import AuthScreenShell from "@/components/auth/AuthScreenShell";
import { requestPasswordReset } from "@/lib/api";

/**
 * Forgot-password page (AUTH-EMAIL-RESET-WIRING).
 *
 * Single email field. POSTs to `/api/v1/auth/forgot-password` and
 * shows the SAME confirmation regardless of the response — backend
 * returns 204 in both branches (account found / not found) so
 * account existence stays opaque. The web copy must not leak the
 * branch either; that's why both `then` and `catch` (transport
 * errors aside) route to the same "Check your inbox" panel.
 *
 * Transport errors (network down, CORS, 5xx) DO surface — those are
 * not enumeration signals, and the user needs to know to retry.
 *
 * The page intentionally avoids `useRouter` for navigation — a
 * `<Link>` to `/login` is enough, and keeps the redirect static-
 * export-friendly.
 */

export default function ForgotPasswordPage() {
  const t = useTranslations("Auth.forgotPassword");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [transportError, setTransportError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTransportError(null);
    setLoading(true);
    try {
      await requestPasswordReset(email.trim().toLowerCase());
      setSubmitted(true);
    } catch (err) {
      // Transport-level failures (the server didn't actually respond
      // with 204). Show the generic transport message — never the raw
      // error which could include schema-validation hints that leak
      // info about the request shape.
      const msg = err instanceof Error ? err.message : "";
      if (/Failed to fetch|NetworkError|Load failed|5\d\d/i.test(msg)) {
        setTransportError(t("transportError"));
      } else {
        // 4xx → still treat as "submitted" so the page doesn't
        // enumerate accounts on a malformed-but-otherwise-fine input.
        setSubmitted(true);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthScreenShell>
      <h2 className="aurion-title-3 mb-1.5">{t("title")}</h2>
      <p className="aurion-caption mb-6">{t("subtitle")}</p>

      {submitted ? (
        <div
          data-testid="forgot-password-confirmation"
          className="rounded-aurion-md bg-green-50 px-4 py-4 text-[14px] text-green-800 ring-1 ring-inset ring-green-600/15"
        >
          <div className="mb-1.5 flex items-center gap-2 font-semibold">
            <MailCheck className="h-4 w-4 text-green-600" />
            <span>{t("confirmationTitle")}</span>
          </div>
          <p className="leading-snug">{t("confirmationBody")}</p>
        </div>
      ) : (
        <>
          {transportError && (
            <div
              role="alert"
              data-testid="forgot-password-transport-error"
              className="mb-5 flex items-start gap-2 rounded-aurion-md bg-red-50 px-3.5 py-3 text-[13px] text-red-700 ring-1 ring-inset ring-red-600/15"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
              <span className="leading-snug">{transportError}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block">
              <span className="aurion-micro mb-1.5 block">
                {t("emailLabel")}
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoFocus
                required
                disabled={loading}
                placeholder={t("emailPlaceholder")}
                className="form-input"
                data-testid="forgot-password-email-input"
              />
            </label>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              disabled={email.trim().length === 0}
              fullWidth
              className="mt-2"
            >
              {loading ? t("submitting") : t("submit")}
            </Button>
          </form>
        </>
      )}

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
