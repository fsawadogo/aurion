"use client";

import { usePathname } from "next/navigation";

const breadcrumbMap: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/audit": "Audit Log",
  "/users": "Users",
  "/masking": "PHI Masking",
  "/config": "Configuration",
  "/sessions": "Sessions",
  "/eval": "Evaluation",
};

interface HeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export default function Header({ title, subtitle, actions }: HeaderProps) {
  const pathname = usePathname();
  const breadcrumbLabel = pathname ? breadcrumbMap[pathname] : null;

  return (
    <header className="sticky top-0 z-20 border-b border-gray-200/80 bg-white/95 backdrop-blur-sm">
      <div className="flex h-16 items-center justify-between px-6 lg:px-8">
        <div className="min-w-0">
          {breadcrumbLabel && (
            <div className="mb-0.5 flex items-center gap-1.5 text-[11px] text-gray-400">
              <span>Admin</span>
              <span className="text-gray-300">/</span>
              <span className="font-medium text-gray-500">{breadcrumbLabel}</span>
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
