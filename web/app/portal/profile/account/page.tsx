"use client";

import { useCallback, useEffect, useState } from "react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import { getMe, logout } from "@/lib/api";
import { getMyProfile, updateMyProfile } from "@/lib/portal-api";
import type { CurrentUser, PhysicianProfile } from "@/types";

/**
 * Account settings for the clinician portal.
 *
 * Today this is intentionally narrow: identity (read-only), output
 * language, sign-out. MFA setup + active-session listing land in a
 * follow-up dedicated PR — both depend on backend endpoints that
 * don't ship in PR-A/B.
 *
 * The output_language toggle lives here (not on the main profile
 * page) because it's a personal-account preference, not a practice-
 * configuration one. The web portal locale itself is not yet i18n'd
 * — that's the next-intl PR — so the toggle today only changes the
 * language of generated notes, not the UI chrome.
 */
export default function PortalAccountPage() {
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
      setError(e instanceof Error ? e.message : "Failed to load account.");
    } finally {
      setLoading(false);
    }
  }, []);

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
      setError(e instanceof Error ? e.message : "Failed to update language.");
    } finally {
      setSavingLanguage(false);
    }
  }

  return (
    <div className="aurion-page-padded aurion-container-form">
      <PageHeader
        breadcrumb={[
          { label: "My Profile", href: "/portal/profile" },
          { label: "Account" },
        ]}
        eyebrow="Clinician portal"
        title="Account settings"
        description="Identity, language preferences, and sign-out."
      />

      {loading ? (
        <Card>
          <LoadingSkeleton lines={6} />
        </Card>
      ) : error && !profile ? (
        <Card>
          <p className="text-sm text-red-600">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void load()}>
            Retry
          </Button>
        </Card>
      ) : me && profile ? (
        <div className="space-y-6">
          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <Card title="Identity">
            <dl className="space-y-3 text-sm">
              <Row label="Name">{me.full_name || "—"}</Row>
              <Row label="Email">{me.email}</Row>
              <Row label="Role">{me.role}</Row>
            </dl>
          </Card>

          <Card title="Generated note language">
            <p className="text-sm text-gray-600 mb-3">
              The language Aurion uses when generating notes from your
              transcripts. Independent of the portal interface language.
            </p>
            <div className="flex gap-2">
              <LanguageButton
                code="en"
                label="English"
                active={profile.output_language === "en"}
                disabled={savingLanguage}
                onClick={() => void setLanguage("en")}
              />
              <LanguageButton
                code="fr"
                label="Français"
                active={profile.output_language === "fr"}
                disabled={savingLanguage}
                onClick={() => void setLanguage("fr")}
              />
            </div>
          </Card>

          <Card title="Security">
            <p className="text-sm text-gray-600 mb-3">
              Multi-factor authentication and active-session management
              are coming in a follow-up. For now you can sign out below
              — your session ends immediately on this device.
            </p>
            <Button
              variant="secondary"
              onClick={() => {
                void logout();
              }}
            >
              Sign out
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
  active,
  disabled,
  onClick,
}: {
  code: string;
  label: string;
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
      aria-label={`Set generated note language to ${label}`}
    >
      <span className="font-mono text-[10px] uppercase mr-1.5 text-gray-500">
        {code}
      </span>
      {label}
    </button>
  );
}
