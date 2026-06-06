"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  /** Injected so tests can supply a deterministic mock without
   * touching the real fetch path. Defaults to the live API helper
   * via the calling component. */
  disable: (currentCode: string) => Promise<void>;
}

/**
 * Confirmation modal for self-serve MFA disable.
 *
 * The TOTP re-verify is mandatory: an attacker who's stolen the
 * laptop holds the access token but not the authenticator, so a
 * password-less Bearer alone must not be enough to take MFA off.
 * The backend enforces this — this modal is the UI shell.
 */
export default function MfaDisableModal({
  isOpen,
  onClose,
  onSuccess,
  disable,
}: Props) {
  const t = useTranslations("Account.mfa.disable");
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setCode("");
    setError(null);
    setSubmitting(false);
  }, [isOpen]);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      await disable(code);
      onSuccess();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("error"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t("title")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            {t("cancelCta")}
          </Button>
          <Button
            onClick={submit}
            disabled={submitting || code.length !== 6}
          >
            {submitting ? t("submitting") : t("confirmCta")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-gray-700">{t("description")}</p>
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
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            className="mt-1 w-full rounded-md border border-gray-200 bg-white px-3 py-2 font-mono text-lg tracking-widest focus:border-gold-500 focus:outline-none"
            aria-label={t("codeAria")}
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>
    </Modal>
  );
}
