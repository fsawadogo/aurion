"use client";

import { Settings } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import { getMyProfile, updateMyProfile } from "@/lib/portal-api";
import type { PhysicianProfile } from "@/types";

/**
 * Clinician profile — view + edit.
 *
 * Mirrors the iOS `PhysicianProfileSetupView` field set so a clinician
 * can manage their preferences from either device. Practice type is a
 * Set<string> in the UI (multiple-select) that serialises to a
 * comma-joined string on the wire, matching the iOS convention and
 * the backend's `practice_type` column shape.
 *
 * Output language picker lives on the companion `/portal/profile/account`
 * page (it's a personal-account concern, not a practice-config one).
 */

/* ── Option keys — labels resolve via the i18n catalogs so they stay
 *  in lockstep with iOS `PhysicianProfileSetupView`. ──────────────── */

const PRACTICE_TYPE_KEYS = ["clinic", "surgical_center", "hospital"] as const;

const SPECIALTY_KEYS = [
  "orthopedic_surgery",
  "plastic_surgery",
  "musculoskeletal",
  "emergency_medicine",
  "general",
] as const;

const CONSULTATION_TYPE_KEYS = [
  "new_patient",
  "follow_up",
  "pre_op",
  "post_op",
] as const;

const CONSENT_REPROMPT_KEYS: PhysicianProfile["consent_reprompt"][] = [
  "every_session",
  "daily",
  "weekly",
];

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function PortalProfilePage() {
  const t = useTranslations("Profile");
  const tIdentity = useTranslations("Profile.identity");
  const tPractice = useTranslations("Profile.practice");
  const tRecording = useTranslations("Profile.recording");
  const tPracticeTypes = useTranslations("Profile.practiceTypes");
  const tConsultation = useTranslations("Profile.consultationTypes");
  const tSpecialties = useTranslations("Specialties");
  const [profile, setProfile] = useState<PhysicianProfile | null>(null);
  const [draft, setDraft] = useState<PhysicianProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedNotice, setSavedNotice] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await getMyProfile();
      setProfile(p);
      setDraft(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = profile != null && draft != null && !isEqual(profile, draft);

  async function onSave() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateMyProfile({
        display_name: draft.display_name,
        practice_type: draft.practice_type,
        primary_specialty: draft.primary_specialty,
        preferred_templates: draft.preferred_templates,
        consultation_types: draft.consultation_types,
        retention_days: draft.retention_days,
        auto_upload: draft.auto_upload,
        consent_reprompt: draft.consent_reprompt,
      });
      setProfile(updated);
      setDraft(updated);
      setSavedNotice(true);
      // Auto-dismiss the "Saved" banner after a couple seconds — the
      // user already sees the buttons go back to disabled, this is
      // belt + suspenders.
      window.setTimeout(() => setSavedNotice(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  function onCancel() {
    if (profile) setDraft(profile);
    setSavedNotice(false);
  }

  const practiceTypeOptions = PRACTICE_TYPE_KEYS.map((key) => ({
    key,
    label: tPracticeTypes(key),
  }));
  const specialtyOptions = SPECIALTY_KEYS.map((key) => ({
    key,
    label: tSpecialties(key),
  }));
  const consultationOptions = CONSULTATION_TYPE_KEYS.map((key) => ({
    key,
    label: tConsultation(key),
  }));
  const consentRepromptOptions = CONSENT_REPROMPT_KEYS.map((key) => ({
    key,
    label:
      key === "every_session"
        ? tRecording("consentEverySession")
        : key === "daily"
          ? tRecording("consentDaily")
          : tRecording("consentWeekly"),
  }));

  return (
    <div className="aurion-page-padded aurion-container-narrow">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={
          <Link
            href="/portal/profile/account"
            className="inline-flex items-center gap-1.5 rounded-aurion-md px-3 py-2 text-aurion-callout text-navy-600 hover:bg-canvas hover:text-navy-800 transition-colors duration-short"
          >
            <Settings className="h-4 w-4" />
            {t("accountSettings")}
          </Link>
        }
      />

      {loading ? (
        <Card>
          <LoadingSkeleton lines={8} />
        </Card>
      ) : error && !profile ? (
        <Card>
          <p className="text-sm text-red-600">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void load()}>
            {t("retry")}
          </Button>
        </Card>
      ) : profile && draft ? (
        <div className="space-y-6">
          {savedNotice && (
            <div className="rounded-md bg-emerald-50 border border-emerald-200 px-4 py-2 text-sm text-emerald-700">
              {t("savedNotice")}
            </div>
          )}
          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <Card title={tIdentity("title")}>
            <div className="space-y-4">
              <Field label={tIdentity("displayName")}>
                <input
                  className="form-input"
                  type="text"
                  value={draft.display_name}
                  onChange={(e) =>
                    setDraft({ ...draft, display_name: e.target.value })
                  }
                />
              </Field>
              {/* Email + role are immutable here — they live in /portal/profile/account. */}
            </div>
          </Card>

          <Card title={tPractice("title")}>
            <div className="space-y-5">
              <MultiSelect
                label={tPractice("practiceSettings")}
                options={practiceTypeOptions}
                selected={parsePracticeType(draft.practice_type)}
                onChange={(set) =>
                  setDraft({
                    ...draft,
                    practice_type: serialisePracticeType(set),
                  })
                }
              />
              <SingleSelect
                label={tPractice("primarySpecialty")}
                options={specialtyOptions}
                value={draft.primary_specialty}
                onChange={(v) => setDraft({ ...draft, primary_specialty: v })}
              />
              <MultiSelect
                label={tPractice("consultationTypes")}
                options={consultationOptions}
                selected={new Set(draft.consultation_types)}
                onChange={(set) =>
                  setDraft({ ...draft, consultation_types: Array.from(set) })
                }
              />
            </div>
          </Card>

          <Card title={tRecording("title")}>
            <div className="space-y-5">
              <Field label={tRecording("retentionLabel")}>
                <input
                  className="form-input w-32"
                  type="number"
                  min={1}
                  max={30}
                  value={draft.retention_days}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    if (Number.isFinite(n) && n >= 1 && n <= 30) {
                      setDraft({ ...draft, retention_days: n });
                    }
                  }}
                />
                <p className="text-xs text-gray-500 mt-1">
                  {tRecording("retentionHint")}
                </p>
              </Field>
              <Toggle
                label={tRecording("autoUploadLabel")}
                description={tRecording("autoUploadHint")}
                value={draft.auto_upload}
                onChange={(v) => setDraft({ ...draft, auto_upload: v })}
              />
              <SingleSelect
                label={tRecording("consentRepromptLabel")}
                options={consentRepromptOptions}
                value={draft.consent_reprompt}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    consent_reprompt: v as PhysicianProfile["consent_reprompt"],
                  })
                }
              />
            </div>
          </Card>

          <div className="flex items-center gap-3 sticky bottom-4 bg-white/85 backdrop-blur rounded-lg border border-gray-200 px-4 py-3 shadow-sm">
            <Button
              variant="primary"
              onClick={() => void onSave()}
              disabled={!dirty || saving}
              loading={saving}
            >
              {t("saveChanges")}
            </Button>
            <Button variant="secondary" onClick={onCancel} disabled={!dirty || saving}>
              {t("discard")}
            </Button>
            <span className="text-xs text-gray-500 ml-auto">
              {dirty ? t("unsaved") : t("allSaved")}
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ── Field sub-components ────────────────────────────────────────────────── */

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-navy-800 mb-1.5">
        {label}
      </span>
      {children}
    </label>
  );
}

function SingleSelect({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <Field label={label}>
      <select
        className="form-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

function MultiSelect({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: { key: string; label: string }[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
}) {
  function toggle(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }
  return (
    <Field label={label}>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => {
          const active = selected.has(o.key);
          return (
            <button
              key={o.key}
              type="button"
              onClick={() => toggle(o.key)}
              className={
                "rounded-full border px-3 py-1.5 text-sm transition-colors " +
                (active
                  ? "border-gold-500 bg-gold-50 text-navy-900 font-medium"
                  : "border-gray-200 text-gray-700 hover:border-gray-300")
              }
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </Field>
  );
}

function Toggle({
  label,
  description,
  value,
  onChange,
}: {
  label: string;
  description?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-navy-800">{label}</p>
        {description && (
          <p className="text-xs text-gray-500 mt-0.5">{description}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={
          "relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-gold-500/50 " +
          (value ? "bg-gold-500" : "bg-gray-300")
        }
        aria-pressed={value}
        aria-label={label}
      >
        <span
          className={
            "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform duration-150 " +
            (value ? "translate-x-5" : "translate-x-0")
          }
        />
      </button>
    </div>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────────── */

function parsePracticeType(value: string | null): Set<string> {
  if (!value) return new Set();
  return new Set(value.split(",").map((s) => s.trim()).filter(Boolean));
}

function serialisePracticeType(set: Set<string>): string | null {
  if (set.size === 0) return null;
  return Array.from(set).join(",");
}

function isEqual(a: PhysicianProfile, b: PhysicianProfile): boolean {
  return (
    a.display_name === b.display_name &&
    a.practice_type === b.practice_type &&
    a.primary_specialty === b.primary_specialty &&
    a.consent_reprompt === b.consent_reprompt &&
    a.output_language === b.output_language &&
    a.auto_upload === b.auto_upload &&
    a.retention_days === b.retention_days &&
    sameStringArray(a.preferred_templates, b.preferred_templates) &&
    sameStringArray(a.consultation_types, b.consultation_types)
  );
}

function sameStringArray(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const bs = [...b].sort();
  const as = [...a].sort();
  for (let i = 0; i < as.length; i++) if (as[i] !== bs[i]) return false;
  return true;
}
