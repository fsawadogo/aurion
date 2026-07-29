"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  clearOrgVisitTypeTemplate,
  getMe,
  humanizeError,
  listOrgVisitTypeTemplates,
  setOrgVisitTypeTemplate,
} from "@/lib/api";
import {
  getMyProfile,
  listMyCustomTemplates,
  updateMyProfile,
} from "@/lib/portal-api";
import VisitTypeContextsEditor, {
  BUILT_IN_TEMPLATE_KEYS,
} from "@/components/portal/VisitTypeContextsEditor";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import type {
  CustomTemplate,
  OrgVisitTypeTemplate,
  VisitTypeContext,
} from "@/types";

/**
 * Templates → "Visit Types" tab: the visit-type → template map, both tiers.
 *
 *   • Admin sees the flat ORG-default list per visit type (built-in or a
 *     SHARED custom template) — the fallback every clinician inherits.
 *   • A clinician sees ONE surface (TE-4h): the per-visit-type accordion
 *     (`VisitTypeContextsEditor`, shared with My Profile) holding each visit
 *     type's DEFAULT template (its ``is_default`` context, #577) and its
 *     named contexts — edited as one draft, saved together.
 *
 * Both tiers resolve server-side in ``resolve_context_template_key``; iOS just
 * sends the visit type.
 */

// Mirrors the System-Templates elevatable curation set (#578).
const ADMIN_ROLES = new Set(["ADMIN", "COMPLIANCE_OFFICER", "CLINICAL_ADMIN"]);

const DEFAULT_VISIT_TYPE_LABELS: Record<string, string> = {
  new_patient: "New patient",
  follow_up: "Follow-up",
  pre_op: "Pre-op",
  post_op: "Post-op",
};

function visitTypeLabel(key: string): string {
  return DEFAULT_VISIT_TYPE_LABELS[key] ?? key;
}

// Select value encoding: "" = specialty/org default; "builtin:<key>"; "custom:<id>".
function encodeValue(
  templateKey: string | null | undefined,
  customId: string | null | undefined,
): string {
  if (templateKey) return `builtin:${templateKey}`;
  if (customId) return `custom:${customId}`;
  return "";
}

function orgValue(row: OrgVisitTypeTemplate | undefined): string {
  return encodeValue(row?.template_key, row?.custom_template_id);
}

export default function VisitTypesTab() {
  const t = useTranslations("TemplatesList");
  const tTpl = useTranslations("Profile.contexts.templates");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [visitTypes, setVisitTypes] = useState<string[]>([]);
  const [orgByVt, setOrgByVt] = useState<Record<string, OrgVisitTypeTemplate>>(
    {},
  );
  const [contextsByVt, setContextsByVt] = useState<
    Record<string, VisitTypeContext[]>
  >({});
  // TE-4f: the clinician's whole visit-type mapping (defaults + named
  // contexts) is edited as ONE draft and saved together, so the flat default
  // dropdown and the rich accordion — both editing contexts_per_visit_type —
  // can't race each other's PUT. `contextsByVt` is the last saved snapshot.
  const [draftContexts, setDraftContexts] = useState<
    Record<string, VisitTypeContext[]>
  >({});
  const [savingContexts, setSavingContexts] = useState(false);
  const [customs, setCustoms] = useState<CustomTemplate[]>([]);
  const [savingVt, setSavingVt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const me = await getMe();
      const admin = ADMIN_ROLES.has(me.role as string);
      setIsAdmin(admin);
      const [profile, allCustoms] = await Promise.all([
        getMyProfile(),
        listMyCustomTemplates(),
      ]);
      setVisitTypes(profile.consultation_types ?? []);
      setContextsByVt(profile.contexts_per_visit_type ?? {});
      setDraftContexts(profile.contexts_per_visit_type ?? {});
      setCustoms(allCustoms);
      if (admin) {
        const rows = await listOrgVisitTypeTemplates();
        const map: Record<string, OrgVisitTypeTemplate> = {};
        for (const r of rows) map[r.visit_type] = r;
        setOrgByVt(map);
      }
    } catch (e) {
      setLoadError(humanizeError(e, t("visitsLoadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onOrgChange(vt: string, value: string) {
    setSavingVt(vt);
    setSaveError(null);
    try {
      if (value === "") {
        await clearOrgVisitTypeTemplate(vt);
        setOrgByVt((prev) => {
          const next = { ...prev };
          delete next[vt];
          return next;
        });
      } else {
        const idx = value.indexOf(":");
        const kind = value.slice(0, idx);
        const id = value.slice(idx + 1);
        const saved = await setOrgVisitTypeTemplate(
          vt,
          kind === "builtin"
            ? { template_key: id }
            : { custom_template_id: id },
        );
        setOrgByVt((prev) => ({ ...prev, [vt]: saved }));
      }
    } catch (e) {
      setSaveError(humanizeError(e, t("visitsSaveError")));
    } finally {
      setSavingVt(null);
    }
  }

  const contextsDirty =
    JSON.stringify(draftContexts) !== JSON.stringify(contextsByVt);

  async function onSaveContexts() {
    setSavingContexts(true);
    setSaveError(null);
    try {
      await updateMyProfile({
        consultation_types: visitTypes,
        contexts_per_visit_type: draftContexts,
      });
      setContextsByVt(draftContexts);
    } catch (e) {
      setSaveError(humanizeError(e, t("visitsSaveError")));
    } finally {
      setSavingContexts(false);
    }
  }

  function renderSelect(
    vt: string,
    value: string,
    options: CustomTemplate[],
    customGroupLabel: string,
    onChange: (vt: string, value: string) => void,
  ) {
    // Admin-only since TE-4h — the clinician surface is the accordion below.
    return (
      <select
        className="rounded-aurion-md border border-hairline bg-white px-3 py-2 text-aurion-callout text-navy-800 focus:outline-none focus:ring-2 focus:ring-gold-300/40 disabled:opacity-50"
        value={value}
        // Serialize org-default writes: disable while a save is in flight.
        disabled={savingVt !== null}
        onChange={(e) => onChange(vt, e.target.value)}
        data-testid={`visit-type-template-${vt}`}
        aria-label={t("visitsSelectAria", { visit: visitTypeLabel(vt) })}
      >
        <option value="">{t("visitsSpecialtyDefault")}</option>
        <optgroup label={t("visitsBuiltinGroup")}>
          {BUILT_IN_TEMPLATE_KEYS.map((k) => (
            <option key={k} value={encodeValue(k, null)}>
              {tTpl(k)}
            </option>
          ))}
        </optgroup>
        {options.length > 0 && (
          <optgroup label={customGroupLabel}>
            {options.map((c) => (
              <option key={c.id} value={`custom:${c.id}`}>
                {c.display_name}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    );
  }

  if (loading) return <LoadingSkeleton lines={5} />;

  if (loadError) {
    return (
      <div className="py-4">
        <div className="mb-3 rounded-aurion-md bg-red-50 border border-red-200 px-4 py-3 text-aurion-callout text-red-700">
          {loadError}
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="text-aurion-callout font-medium text-navy-500 hover:text-navy-800 transition-colors duration-short"
        >
          {t("visitsRetry")}
        </button>
      </div>
    );
  }

  const shared = customs.filter((c) => c.is_shared);

  return (
    <div>
      {saveError && (
        <div className="mb-4 rounded-aurion-md bg-red-50 border border-red-200 px-4 py-3 text-aurion-callout text-red-700">
          {saveError}
        </div>
      )}
      {isAdmin && (
        <p className="mb-4 text-aurion-caption text-navy-500">
          {t("visitsAdminHint")}
        </p>
      )}
      {visitTypes.length === 0 ? (
        <p className="py-4 text-aurion-caption text-navy-500">
          {t("visitsEmpty")}
        </p>
      ) : isAdmin ? (
        <ul className="divide-y divide-hairline">
          {visitTypes.map((vt) => (
            <li key={vt} className="flex items-center gap-3 py-3">
              <span className="flex-1 min-w-0 truncate text-aurion-callout font-medium text-navy-800">
                {visitTypeLabel(vt)}
              </span>
              {renderSelect(
                vt,
                orgValue(orgByVt[vt]),
                shared,
                t("visitsSharedGroup"),
                onOrgChange,
              )}
            </li>
          ))}
        </ul>
      ) : (
        /* TE-4h — the clinician's ONE surface: the same accordion as My
           Profile, now carrying each visit type's default template AND its
           contexts. One draft, one Save. */
        <div>
          <VisitTypeContextsEditor
            visitTypes={visitTypes}
            value={draftContexts}
            onChange={setDraftContexts}
            customTemplates={customs}
          />
          <div className="mt-4 flex items-center gap-3">
            <Button
              variant="primary"
              size="sm"
              onClick={() => void onSaveContexts()}
              loading={savingContexts}
              disabled={!contextsDirty || savingContexts}
              data-testid="visit-types-save"
            >
              {t("visitsSaveButton")}
            </Button>
            {contextsDirty && !savingContexts && (
              <span className="text-aurion-caption text-navy-400">
                {t("visitsUnsaved")}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
