"use client";

/**
 * /portal/admin/library — unified admin template Library (#579).
 *
 * One page, two sections: Built-in specialty templates (admin override, keyed)
 * and Org-custom shared templates (UUID). Reuses the existing section
 * components + their APIs — NO data change. The two former routes
 * (/admin/templates, /admin/shared-templates) remain as thin wrappers over the
 * same sections for back-compat; the Sidebar now points here as the single
 * "Library" entry.
 */

import { useTranslations } from "next-intl";
import PageHeader from "@/components/portal/PageHeader";
import AdminSystemTemplatesSection from "@/components/portal/AdminSystemTemplatesSection";
import AdminSharedTemplatesSection from "@/components/portal/AdminSharedTemplatesSection";

const headingClass =
  "mb-3 text-aurion-caption font-semibold uppercase tracking-wide text-navy-500";

export default function AdminLibraryPage() {
  const t = useTranslations("AdminLibrary");
  return (
    <div
      className="aurion-page-padded aurion-container-narrow"
      data-testid="admin-library-page"
    >
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
      />

      <section className="mb-8">
        <h2 className={headingClass}>{t("builtinHeading")}</h2>
        <AdminSystemTemplatesSection />
      </section>

      <section>
        <h2 className={headingClass}>{t("customHeading")}</h2>
        <AdminSharedTemplatesSection />
      </section>
    </div>
  );
}
