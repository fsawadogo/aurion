"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

// Map a top-level route to its Sidebar nav key, so the breadcrumb label
// reuses the already-localized Sidebar.nav.* strings (single source of
// truth — no parallel English-only label map to drift).
const breadcrumbNavKey: Record<string, string> = {
  "/dashboard": "dashboard",
  "/audit": "auditLog",
  "/users": "users",
  "/masking": "phiMasking",
  "/config": "config",
  "/sessions": "sessions",
  "/eval": "eval",
};

interface HeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export default function Header({ title, subtitle, actions }: HeaderProps) {
  const pathname = usePathname();
  const t = useTranslations("Sidebar");
  const navKey = pathname ? breadcrumbNavKey[pathname] : null;

  return (
    <header className="sticky top-0 z-20 border-b border-gray-200/80 bg-white/95 backdrop-blur-sm">
      <div className="flex h-16 items-center justify-between px-6 lg:px-8">
        <div className="min-w-0">
          {navKey && (
            <div className="mb-0.5 flex items-center gap-1.5 text-[11px] text-gray-400">
              <span>{t("admin")}</span>
              <span className="text-gray-300">/</span>
              <span className="font-medium text-gray-500">{t(`nav.${navKey}`)}</span>
            </div>
          )}
          <h1 className="truncate text-lg font-semibold text-navy-700">{title}</h1>
        </div>
        {(subtitle || actions) && (
          <div className="flex items-center gap-4">
            {subtitle && (
              <p className="hidden text-sm text-gray-400 sm:block">{subtitle}</p>
            )}
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}
