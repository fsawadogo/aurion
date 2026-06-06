"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import MfaEnrollModal from "@/components/portal/MfaEnrollModal";
import MfaDisableModal from "@/components/portal/MfaDisableModal";
import { disableMfa, getMfaStatus, type MfaStatus } from "@/lib/portal-api";

/**
 * MFA card on /portal/profile/account (#163).
 *
 * Three states:
 *   * loading           — skeleton while the status probe runs.
 *   * not enrolled      — "Enable MFA" CTA, opens the 2-step enroll
 *                         modal (QR + recovery codes → TOTP verify).
 *   * enrolled          — pill badge + "Last verified" line + a
 *                         "Disable MFA" button that requires a fresh
 *                         code.
 *
 * The card owns its own status fetch and re-fetches after either
 * modal closes successfully — the parent doesn't need to wire the
 * round-trip.
 */
export default function MfaCard() {
  const t = useTranslations("Account.mfa");
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [enrollOpen, setEnrollOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await getMfaStatus();
      setStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleEnrolled = useCallback(() => {
    setEnrollOpen(false);
    void refresh();
  }, [refresh]);

  const handleDisabled = useCallback(() => {
    setDisableOpen(false);
    void refresh();
  }, [refresh]);

  return (
    <>
      <Card title={t("title")}>
        <p className="text-sm text-gray-600 mb-3">{t("description")}</p>

        {loading ? (
          <LoadingSkeleton lines={2} />
        ) : error ? (
          <div className="space-y-2">
            <p className="text-sm text-red-600">{error}</p>
            <Button variant="secondary" onClick={() => void refresh()}>
              {t("retry")}
            </Button>
          </div>
        ) : status?.enrolled ? (
          <EnrolledRow
            lastVerifiedAt={status.last_verified_at}
            onDisableClick={() => setDisableOpen(true)}
          />
        ) : (
          <NotEnrolledRow onEnrollClick={() => setEnrollOpen(true)} />
        )}
      </Card>

      <MfaEnrollModal
        isOpen={enrollOpen}
        onClose={() => setEnrollOpen(false)}
        onSuccess={handleEnrolled}
      />

      <MfaDisableModal
        isOpen={disableOpen}
        onClose={() => setDisableOpen(false)}
        onSuccess={handleDisabled}
        disable={disableMfa}
      />
    </>
  );
}

function NotEnrolledRow({ onEnrollClick }: { onEnrollClick: () => void }) {
  const t = useTranslations("Account.mfa");
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span
          className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-2.5 py-0.5 text-xs font-medium text-gray-700"
          aria-label={t("statusNotEnrolledAria")}
        >
          {t("statusNotEnrolled")}
        </span>
      </div>
      <Button onClick={onEnrollClick}>{t("enableCta")}</Button>
    </div>
  );
}

function EnrolledRow({
  lastVerifiedAt,
  onDisableClick,
}: {
  lastVerifiedAt: string | null;
  onDisableClick: () => void;
}) {
  const t = useTranslations("Account.mfa");
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span
          className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700"
          aria-label={t("statusEnrolledAria")}
        >
          {t("statusEnrolled")}
        </span>
        {lastVerifiedAt && (
          <span className="text-xs text-gray-500">
            {t("lastVerified", { at: formatRelative(lastVerifiedAt) })}
          </span>
        )}
      </div>
      <Button variant="secondary" onClick={onDisableClick}>
        {t("disableCta")}
      </Button>
    </div>
  );
}

/** ISO timestamp → "2 hours ago" / "Apr 12, 2026" hybrid.
 *
 * We render relative for the past 24h (the common case — clinician
 * just logged in this morning) and absolute for everything older so
 * the date stays unambiguous in audit screenshots. Falls back to the
 * raw string on parse failure so we never throw on a malformed
 * timestamp.
 */
function formatRelative(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const deltaMs = Date.now() - date.getTime();
  const hours = deltaMs / (1000 * 60 * 60);
  if (hours < 24) {
    const rounded = Math.max(1, Math.round(hours));
    return rounded === 1 ? "1 hour ago" : `${rounded} hours ago`;
  }
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
