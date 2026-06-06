"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import QRCode from "qrcode";

import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import { enrollMfa, verifyMfaEnroll } from "@/lib/portal-api";
import type { MfaEnrollResponse } from "@/lib/portal-api";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * Two-step MFA enrollment modal.
 *
 * Step 1 (scan):
 *   * POST /api/v1/me/mfa/enroll on open → gets QR URI + 8 recovery codes.
 *   * Renders the QR on a canvas locally — the URI never leaves the
 *     modal, the recovery codes are rendered as plaintext exactly once.
 *   * "Next" advances to step 2.
 *
 * Step 2 (verify):
 *   * 6-digit TOTP entry → POST /api/v1/me/mfa/verify-enroll.
 *   * Success → `onSuccess()` fires; the parent re-fetches status.
 *
 * The `setup_token` returned in step 1 carries the candidate secret +
 * hashed recovery codes server-side until verify succeeds; nothing
 * persists if the clinician abandons the modal.
 */
export default function MfaEnrollModal({ isOpen, onClose, onSuccess }: Props) {
  const t = useTranslations("Account.mfa.enroll");
  const [step, setStep] = useState<"scan" | "verify">("scan");
  const [enrollment, setEnrollment] = useState<MfaEnrollResponse | null>(null);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset when reopened.
  useEffect(() => {
    if (!isOpen) return;
    setStep("scan");
    setEnrollment(null);
    setCode("");
    setError(null);
    setSubmitting(false);
    let cancelled = false;
    void (async () => {
      try {
        const data = await enrollMfa();
        if (cancelled) return;
        setEnrollment(data);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : t("startError"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isOpen, t]);

  async function submitVerify() {
    if (!enrollment) return;
    setSubmitting(true);
    setError(null);
    try {
      await verifyMfaEnroll(enrollment.setup_token, code);
      onSuccess();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("verifyError"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t("title")} size="lg">
      {!enrollment ? (
        <div className="py-6 text-center text-sm text-gray-500">
          {error ?? t("starting")}
        </div>
      ) : step === "scan" ? (
        <ScanStep
          enrollment={enrollment}
          onNext={() => setStep("verify")}
        />
      ) : (
        <VerifyStep
          code={code}
          submitting={submitting}
          error={error}
          onCodeChange={setCode}
          onSubmit={submitVerify}
          onBack={() => setStep("scan")}
        />
      )}
    </Modal>
  );
}

function ScanStep({
  enrollment,
  onNext,
}: {
  enrollment: MfaEnrollResponse;
  onNext: () => void;
}) {
  const t = useTranslations("Account.mfa.enroll");
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Render the QR code into the canvas whenever the QR URI changes.
  // We render with QRCode.toCanvas so the bitmap stays inline — never
  // posted to a 3rd-party QR endpoint.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    void QRCode.toCanvas(canvas, enrollment.qr_uri, {
      width: 192,
      margin: 1,
      color: { dark: "#0f172a", light: "#ffffff" },
    });
  }, [enrollment.qr_uri]);

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-700">{t("scanDescription")}</p>

      <div className="flex flex-col items-center gap-3">
        <canvas
          ref={canvasRef}
          aria-label={t("qrAria")}
          className="rounded-md bg-white p-2 ring-1 ring-gray-200"
        />
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer">{t("manualEntry")}</summary>
          <code className="mt-1 inline-block break-all rounded bg-gray-50 px-2 py-1 font-mono text-[11px]">
            {enrollment.secret}
          </code>
        </details>
      </div>

      <div>
        <h4 className="text-sm font-semibold text-navy-700">
          {t("recoveryCodesTitle")}
        </h4>
        <p className="mt-1 text-xs text-gray-600">
          {t("recoveryCodesDescription")}
        </p>
        <ul
          aria-label={t("recoveryCodesAria")}
          className="mt-2 grid grid-cols-2 gap-1.5 rounded-md bg-gray-50 p-3 font-mono text-sm text-navy-800"
        >
          {enrollment.recovery_codes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </div>

      <div className="flex justify-end">
        <Button onClick={onNext}>{t("nextCta")}</Button>
      </div>
    </div>
  );
}

function VerifyStep({
  code,
  submitting,
  error,
  onCodeChange,
  onSubmit,
  onBack,
}: {
  code: string;
  submitting: boolean;
  error: string | null;
  onCodeChange: (v: string) => void;
  onSubmit: () => void;
  onBack: () => void;
}) {
  const t = useTranslations("Account.mfa.enroll");
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-700">{t("verifyDescription")}</p>
      <label className="block">
        <span className="text-xs uppercase tracking-wider text-gray-500">
          {t("codeLabel")}
        </span>
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          pattern="[0-9]{6}"
          value={code}
          onChange={(e) => onCodeChange(e.target.value.replace(/\D/g, ""))}
          className="mt-1 w-full rounded-md border border-gray-200 bg-white px-3 py-2 font-mono text-lg tracking-widest focus:border-gold-500 focus:outline-none"
          aria-label={t("codeAria")}
        />
      </label>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-between">
        <Button variant="secondary" onClick={onBack} disabled={submitting}>
          {t("backCta")}
        </Button>
        <Button
          onClick={onSubmit}
          disabled={submitting || code.length !== 6}
        >
          {submitting ? t("verifying") : t("verifyCta")}
        </Button>
      </div>
    </div>
  );
}
