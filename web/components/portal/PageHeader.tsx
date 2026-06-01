import { ReactNode } from "react";
import Link from "next/link";
import { ChevronRightIcon } from "@heroicons/react/24/outline";

/**
 * Aurion page header — the chrome every portal page sits under.
 *
 * Optional breadcrumb above the title, optional eyebrow micro-label
 * (the iOS "aurionMicro" idiom — uppercase semibold gold tag that
 * announces context). Right slot for primary actions. Hairline below
 * separates header chrome from content without an actual visible
 * border on the canvas.
 *
 * Usage:
 *
 *   <PageHeader
 *     eyebrow="Clinician portal"
 *     title="My Notes"
 *     description="Sessions you've recorded, with their generated notes."
 *     actions={<Button>Refresh</Button>}
 *   />
 */

interface BreadcrumbCrumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  breadcrumb?: BreadcrumbCrumb[];
  actions?: ReactNode;
  className?: string;
}

export default function PageHeader({
  eyebrow,
  title,
  description,
  breadcrumb,
  actions,
  className = "",
}: PageHeaderProps) {
  return (
    <header className={"mb-7 " + className}>
      {breadcrumb && breadcrumb.length > 0 && (
        <nav
          aria-label="Breadcrumb"
          className="mb-3 flex items-center gap-1 text-aurion-caption text-navy-400"
        >
          {breadcrumb.map((c, i) => {
            const isLast = i === breadcrumb.length - 1;
            return (
              <span key={i} className="flex items-center gap-1">
                {c.href && !isLast ? (
                  <Link
                    href={c.href}
                    className="hover:text-navy-700 transition-colors duration-short"
                  >
                    {c.label}
                  </Link>
                ) : (
                  <span
                    className={isLast ? "text-navy-700 font-medium" : ""}
                  >
                    {c.label}
                  </span>
                )}
                {!isLast && (
                  <ChevronRightIcon className="h-3 w-3 text-navy-200" />
                )}
              </span>
            );
          })}
        </nav>
      )}

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && (
            <p className="aurion-micro mb-1 text-gold-600">{eyebrow}</p>
          )}
          <h1 className="aurion-display">{title}</h1>
          {description && (
            <p className="mt-1.5 text-aurion-callout text-navy-500 max-w-2xl">
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex items-center gap-2 shrink-0">{actions}</div>
        )}
      </div>
    </header>
  );
}
