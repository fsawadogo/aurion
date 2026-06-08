"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import LocaleSwitcher from "@/components/portal/LocaleSwitcher";
import MfaCard from "@/components/portal/MfaCard";
import PageHeader from "@/components/portal/PageHeader";
import SessionsCard from "@/components/portal/SessionsCard";
import { getMe, logout, humanizeError} from "@/lib/api";
import { getMyProfile, updateMyProfile } from "@/lib/portal-api";
import type { CurrentUser, PhysicianProfile } from "@/types";

/**
 * Account settings for the clinician portal.
 *
 * Today this is intentionally narrow: identity (read-only), generated
 * note language, portal UI language, sign-out. MFA setup + active-
 * session listing land in a follow-up dedicated PR — both depend on
 * backend endpoints that don't ship in PR-A/B.
 *
 * Two language toggles live here side-by-side:
 *   * Generated note language (`output_language`) — the language the
 *     LLM writes the SOAP note in.
 *   * Portal interface language (`ui_language` / cookie) — the locale
 *     used for menus, buttons, and labels in this portal. Handled by
 *     <LocaleSwitcher /> which writes the cookie + syncs to backend.
 *
 * They're deliberately separate fields per CLAUDE.md memory — a
 * physician might prefer FR chrome but EN-generated notes (or vice
 * versa) so we don't conflate them.
 */
export default function PortalAccountPage() {
  const t = useTranslations("Account");
  const tIdentity = useTranslations("Account.identity");
  const tNote = useTranslations("Account.noteLanguage");
  const tUi = useTranslations("Account.uiLanguage");
  const tSecurity = useTranslations("Account.security");
  const tRoles = useTranslations("Roles");
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PhysicianProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingLanguage, setSavingLanguage] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [u, p] = await Promise.all([getMe(), getMyProfile()]);
      setMe(u);
      setProfile(p);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function setLanguage(lang: "en" | "fr") {
    if (!profile || profile.output_language === lang) return;
    setSavingLanguage(true);
    setError(null);
    try {
      const updated = await updateMyProfile({ output_language: lang });
      setProfile(updated);
    } catch (e) {
      setError(humanizeError(e, t("saveLanguageError")));
    } finally {
      setSavingLanguage(false);
    }
  }

  return (
    <div className="aurion-page-padded aurion-container-form">
      <PageHeader
        breadcrumb={[
          { label: t("breadcrumbProfile"), href: "/portal/profile" },
          { label: t("breadcrumbAccount") },
        ]}
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
      />

      {loading ? (
        <Card>
          <LoadingSkeleton lines={6} />
        </Card>
      ) : error && !profile ? (
        <Card>
          <p className="text-sm text-red-600">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void load()}>
            {t("retry")}
          </Button>
        </Card>
      ) : me && profile ? (
        <div className="space-y-6">
          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <Card title={tIdentity("title")}>
            <dl className="space-y-3 text-sm">
              <Row label={tIdentity("name")}>{me.full_name || tIdentity("missing")}</Row>
              <Row label={tIdentity("email")}>{me.email}</Row>
              <Row label={tIdentity("role")}>{tRoles(me.role)}</Row>
            </dl>
          </Card>

          <Card title={tUi("title")}>
            <p className="text-sm text-gray-600 mb-3">{tUi("description")}</p>
            {/* LocaleSwitcher writes the aurion-locale cookie + syncs
                to backend `ui_language`; router.refresh() re-renders
                the chrome with the new catalog. */}
            <LocaleSwitcher variant="inline" />
          </Card>

          <Card title={tNote("title")}>
            <p className="text-sm text-gray-600 mb-3">{tNote("description")}</p>
            <div className="flex gap-2">
              <LanguageButton
                code="en"
                label={tNote("english")}
                ariaLabel={tNote("setAria", { label: tNote("english") })}
                active={profile.output_language === "en"}
                disabled={savingLanguage}
                onClick={() => void setLanguage("en")}
              />
              <LanguageButton
                code="fr"
                label={tNote("french")}
                ariaLabel={tNote("setAria", { label: tNote("french") })}
                active={profile.output_language === "fr"}
                disabled={savingLanguage}
                onClick={() => void setLanguage("fr")}
              />
            </div>
          </Card>

          <MfaCard />

          <SessionsCard />

          <Card title={tSecurity("title")}>
            <p className="text-sm text-gray-600 mb-3">{tSecurity("description")}</p>
            <Button
              variant="secondary"
              onClick={() => {
                void logout();
              }}
            >
              {tSecurity("signOut")}
            </Button>
          </Card>
        </div>
      ) : null}
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="w-24 shrink-0 text-xs uppercase tracking-wider text-gray-500">
        {label}
      </dt>
      <dd className="flex-1 text-right text-navy-800 font-medium">{children}</dd>
    </div>
  );
}

function LanguageButton({
  code,
  label,
  ariaLabel,
  active,
  disabled,
  onClick,
}: {
  code: string;
  label: string;
  ariaLabel: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || active}
      className={
        "rounded-lg border px-4 py-2 text-sm transition-colors " +
        (active
          ? "border-gold-500 bg-gold-50 text-navy-900 font-medium cursor-default"
          : "border-gray-200 text-gray-700 hover:border-gray-300 disabled:opacity-50")
      }
      aria-pressed={active}
      aria-label={ariaLabel}
    >
      <span className="font-mono text-[10px] uppercase mr-1.5 text-gray-500">
        {code}
      </span>
      {label}
    </button>
  );
}
