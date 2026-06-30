"use client";

/**
 * /portal/admin/templates — built-in specialty template management (#72).
 * Thin wrapper: the list + in-place editor live in AdminSystemTemplatesSection,
 * which is also composed into the unified admin Library
 * (/portal/admin/library, #579). Kept as a standalone route for back-compat.
 */

import { useTranslations } from "next-intl";
import PageHeader from "@/components/portal/PageHeader";
import AdminSystemTemplatesSection from "@/components/portal/AdminSystemTemplatesSection";

export default function AdminTemplatesPage() {
  const t = useTranslations("AdminTemplates");
  return (
    <div
      className="aurion-page-padded aurion-container-narrow"
      data-testid="admin-templates-page"
    >
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
      />
      <AdminSystemTemplatesSection />
    </div>
  );
}
