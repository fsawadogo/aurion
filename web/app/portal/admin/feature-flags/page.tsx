"use client";

/**
 * /portal/admin/feature-flags — ADMIN-only feature flag toggles.
 *
 * Scope (lane-full/card-visibility-flags): four post-pilot cards on
 * the iOS note-review screen (Orders, Coding & Billing, Patient
 * Summary, EMR Write-Back) each ship behind their own AppConfig flag.
 * This page is the only writer for those flags — backend pushes a new
 * AppConfig hosted-version every save and the live FeatureFlagsConfig
 * propagates to iOS within ~30 seconds via the existing polling
 * client.
 *
 * The other six feature flags (screen capture, note versioning, etc.)
 * are read-only here. They're tied to deeper pipeline behaviors and
 * aren't intended for ad-hoc admin toggling during pilot. The save
 * action only writes the four card flags; the other six pass through
 * verbatim from the loaded snapshot.
 *
 * Role gate: the link only appears in the Sidebar for ADMIN, AND the
 * backend POST /admin/feature-flags is `require_role(ADMIN)`. A
 * non-ADMIN landing here directly would see a load error from the GET
 * which is itself ADMIN-gated.
 */

import { AlertTriangle, CheckCircle2, Flag } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import { getFeatureFlags, updateFeatureFlags, humanizeError} from "@/lib/api";
import type { FeatureFlags } from "@/types";

/** The four flags this page actually mutates. Order = display order. */
const EDITABLE_FLAGS = [
  "orders_card_enabled",
  "coding_card_enabled",
  "patient_summary_card_enabled",
  "emr_writeback_card_enabled",
] as const satisfies readonly (keyof FeatureFlags)[];

type EditableFlag = (typeof EDITABLE_FLAGS)[number];

/** Mirror Theme.swift's toggle visual rhythm — gold rail when ON, neutral
 *  when OFF, gentle ease transition that matches AurionAnimation.spring. */
function ToggleSwitch({
  enabled,
  onChange,
  ariaLabel,
}: {
  enabled: boolean;
  onChange: () => void;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={ariaLabel}
      onClick={onChange}
      className={
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full " +
        "transition-colors duration-short ease-aurion " +
        "focus:outline-none focus:ring-2 focus:ring-gold-300/40 " +
        (enabled ? "bg-gold-500" : "bg-navy-200")
      }
    >
      <span
        className={
          "inline-block h-5 w-5 transform rounded-full bg-white shadow-sm " +
          "transition-transform duration-short ease-aurion " +
          (enabled ? "translate-x-[22px]" : "translate-x-[2px]")
        }
      />
    </button>
  );
}

export default function FeatureFlagsPage() {
  const t = useTranslations("FeatureFlags");

  const [loaded, setLoaded] = useState<FeatureFlags | null>(null);
  const [draft, setDraft] = useState<FeatureFlags | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await getFeatureFlags();
        if (cancelled) return;
        setLoaded(data);
        setDraft(data);
      } catch (e) {
        if (!cancelled) {
          setError(humanizeError(e, t("loadError")));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const dirty = useMemo(() => {
    if (!loaded || !draft) return false;
    return EDITABLE_FLAGS.some((k) => loaded[k] !== draft[k]);
  }, [loaded, draft]);

  function toggle(key: EditableFlag) {
    if (!draft) return;
    setDraft({ ...draft, [key]: !draft[key] });
    setSavedVersion(null);
  }

  function reset() {
    if (!loaded) return;
    setDraft(loaded);
    setSavedVersion(null);
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    setSavedVersion(null);

    // Optimistic UI: commit the draft into `loaded` so the toggles
    // settle on the new state immediately. Roll back on error.
    const prior = loaded;
    setLoaded(draft);

    try {
      const resp = await updateFeatureFlags(draft);
      setLoaded(resp.feature_flags);
      setDraft(resp.feature_flags);
      setSavedVersion(resp.appconfig_version);
    } catch (e) {
      setLoaded(prior);
      setError(humanizeError(e, t("saveError")));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="aurion-page-padded aurion-container-narrow"
      data-testid="feature-flags-page"
    >
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("subtitle")}
      />

      {error && (
        <div
          className="mb-4 flex items-start gap-2 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {savedVersion !== null && savedVersion > 0 && (
        <div
          className="mb-4 flex items-start gap-2 rounded-aurion-md border border-green-200 bg-green-50 px-4 py-3 text-aurion-callout text-green-800"
          role="status"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{t("saveSuccess", { version: savedVersion })}</span>
        </div>
      )}

      {loading || !draft ? (
        <Card>
          <LoadingSkeleton lines={6} />
        </Card>
      ) : (
        <>
          <Card>
            <div className="mb-4 flex items-center gap-2">
              <Flag className="h-4 w-4 text-gold-600" />
              <h2 className="aurion-micro text-gold-600">
                {t("sectionCards")}
              </h2>
            </div>
            <p className="mb-5 text-aurion-callout text-navy-500">
              {t("sectionCardsHint")}
            </p>

            <ul className="divide-y divide-hairline">
              {EDITABLE_FLAGS.map((key) => {
                const name = t(`flags.${key}.name`);
                const description = t(`flags.${key}.description`);
                const enabled = draft[key];
                const changed = loaded ? loaded[key] !== draft[key] : false;
                return (
                  <li
                    key={key}
                    className="flex items-start justify-between gap-6 py-4"
                    data-testid={`flag-row-${key}`}
                  >
                    <div className="min-w-0">
                      <p className="text-aurion-body font-semibold text-navy-800">
                        {name}
                      </p>
                      <p className="mt-1 text-aurion-caption text-navy-500">
                        {description}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2.5 pt-0.5">
                      <span
                        aria-hidden="true"
                        className={
                          "h-2 w-2 rounded-full bg-gold-500 transition-opacity duration-short ease-aurion " +
                          (changed ? "opacity-100" : "opacity-0")
                        }
                      />
                      <ToggleSwitch
                        enabled={enabled}
                        onChange={() => toggle(key)}
                        ariaLabel={name}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>

          <div className="mt-6 flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              onClick={reset}
              disabled={!dirty || saving}
            >
              {t("reset")}
            </Button>
            <Button
              variant="primary"
              onClick={save}
              loading={saving}
              disabled={!dirty || saving}
            >
              {t("save")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
