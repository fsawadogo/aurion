"use client";

/**
 * /portal/admin/shared-templates — admin org/shared templates (tpl-04, tpl-07).
 * Thin wrapper: the author / edit / list UI lives in
 * AdminSharedTemplatesSection, which is also composed into the unified admin
 * Library (/portal/admin/library, #579). Kept as a standalone route for
 * back-compat.
 */

import { useTranslations } from "next-intl";
import PageHeader from "@/components/portal/PageHeader";
import AdminSharedTemplatesSection from "@/components/portal/AdminSharedTemplatesSection";

export default function SharedTemplatesPage() {
  const t = useTranslations("AdminSharedTemplates");
  return (
    <div className="aurion-page-padded" data-testid="shared-templates-page">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
      />
      <AdminSharedTemplatesSection />
    </div>
  );
}
