"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import {
  clearOrgVisitTypeTemplate,
  getMe,
  humanizeError,
  listOrgVisitTypeTemplates,
  setOrgVisitTypeTemplate,
} from "@/lib/api";
import { getMyProfile, listMyCustomTemplates } from "@/lib/portal-api";
import { BUILT_IN_TEMPLATE_KEYS } from "@/components/portal/VisitTypeContextsEditor";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import type { CustomTemplate, OrgVisitTypeTemplate } from "@/types";

/**
 * Templates → "Visit Types" tab: the admin org-default layer of the visit-type →
 * template map (PR2 of the two-tier mapping; the backend + resolution shipped in
 * PR1). Per visit type, an admin sets the ORG default template; clinicians
 * inherit it unless they pin their own under My Profile → Visit-type contexts
 * (the clinician layer, which outranks the org default at resolve time).
 *
 * The org-default GET/PUT/DELETE are admin-gated server-side, so a non-admin
 * sees a read-only note pointing at their profile rather than the editor.
 */

// Mirrors the System-Templates elevatable curation set (#578).
const ADMIN_ROLES = new Set(["ADMIN", "COMPLIANCE_OFFICER", "CLINICAL_ADMIN"]);

// The four built-in visit-type keys have friendly labels; a clinician-authored
// custom visit type renders verbatim.
const DEFAULT_VISIT_TYPE_LABELS: Record<string, string> = {
  new_patient: "New patient",
  follow_up: "Follow-up",
  pre_op: "Pre-op",
  post_op: "Post-op",
};

function visitTypeLabel(key: string): string {
  return DEFAULT_VISIT_TYPE_LABELS[key] ?? key;
}

// Select value encoding: "" = specialty default; "builtin:<key>"; "custom:<id>".
function currentValue(row: OrgVisitTypeTemplate | undefined): string {
  if (!row) return "";
  if (row.template_key) return `builtin:${row.template_key}`;
  if (row.custom_template_id) return `custom:${row.custom_template_id}`;
  return "";
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
  const [shared, setShared] = useState<CustomTemplate[]>([]);
  const [savingVt, setSavingVt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      // Resolve the role first: a non-admin only sees the read-only note, so we
      // skip the rest (and never call the admin-gated org endpoint for them).
      const me = await getMe();
      const admin = ADMIN_ROLES.has(me.role as string);
      setIsAdmin(admin);
      if (!admin) return;
      const [profile, customs, rows] = await Promise.all([
        getMyProfile(),
        listMyCustomTemplates(),
        listOrgVisitTypeTemplates(),
      ]);
      setVisitTypes(profile.consultation_types ?? []);
      // An org default may only pin a SHARED template (the backend rejects a
      // private one) — so the picker offers built-ins + shared templates only.
      setShared(customs.filter((c) => c.is_shared));
      const map: Record<string, OrgVisitTypeTemplate> = {};
      for (const r of rows) map[r.visit_type] = r;
      setOrgByVt(map);
    } catch (e) {
      setLoadError(humanizeError(e, t("visitsLoadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onChange(vt: string, value: string) {
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

  if (!isAdmin) {
    return (
      <div className="py-8 text-center">
        <p className="text-aurion-callout text-navy-700">
          {t("visitsClinicianNote")}
        </p>
        <Link
          href="/portal/profile"
          className="mt-2 inline-block text-aurion-callout font-medium text-navy-500 hover:text-navy-800 transition-colors duration-short"
        >
          {t("visitsGoToProfile")}
        </Link>
      </div>
    );
  }

  return (
    <div>
      {saveError && (
        <div className="mb-4 rounded-aurion-md bg-red-50 border border-red-200 px-4 py-3 text-aurion-callout text-red-700">
          {saveError}
        </div>
      )}
      <p className="mb-4 text-aurion-caption text-navy-500">
        {t("visitsAdminHint")}
      </p>
      {visitTypes.length === 0 ? (
        <p className="py-4 text-aurion-caption text-navy-500">
          {t("visitsEmpty")}
        </p>
      ) : (
        <ul className="divide-y divide-hairline">
          {visitTypes.map((vt) => (
            <li key={vt} className="flex items-center gap-3 py-3">
              <span className="flex-1 min-w-0 truncate text-aurion-callout font-medium text-navy-800">
                {visitTypeLabel(vt)}
              </span>
              <select
                className="rounded-aurion-md border border-hairline bg-white px-3 py-2 text-aurion-callout text-navy-800 focus:outline-none focus:ring-2 focus:ring-gold-300/40 disabled:opacity-50"
                value={currentValue(orgByVt[vt])}
                disabled={savingVt === vt}
                onChange={(e) => void onChange(vt, e.target.value)}
                data-testid={`visit-type-template-${vt}`}
                aria-label={t("visitsSelectAria", { visit: visitTypeLabel(vt) })}
              >
                <option value="">{t("visitsSpecialtyDefault")}</option>
                <optgroup label={t("visitsBuiltinGroup")}>
                  {BUILT_IN_TEMPLATE_KEYS.map((k) => (
                    <option key={k} value={`builtin:${k}`}>
                      {tTpl(k)}
                    </option>
                  ))}
                </optgroup>
                {shared.length > 0 && (
                  <optgroup label={t("visitsSharedGroup")}>
                    {shared.map((c) => (
                      <option key={c.id} value={`custom:${c.id}`}>
                        {c.display_name}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
