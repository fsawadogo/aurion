"use client"

import { useLocale } from "next-intl"

import { Link, usePathname } from "@/i18n/navigation"
import { routing } from "@/i18n/routing"
import { cn } from "@/lib/utils"

const labels: Record<string, string> = { en: "EN", fr: "FR" }

/**
 * Switches locale while preserving the current path (Heidi-style toggles).
 * Add new locales in `i18n/routing.ts` and `messages/<locale>.json`.
 */
export function LanguageSwitcher() {
  const pathname = usePathname()
  const active = useLocale()

  return (
    <div
      className="flex items-center gap-1 rounded-lg border border-outline-variant/50 bg-surface-container-lowest/80 p-1"
      role="navigation"
      aria-label="Language"
    >
      {routing.locales.map((locale) => (
        <Link
          key={locale}
          href={pathname}
          locale={locale}
          // min-h/w 44px keeps the tap target at the WCAG target size on touch;
          // lg uses the desktop 36px look. (The sub-360 compaction from #729 is
          // gone — on its own header row the full pills fit any width.)
          className={cn(
            "flex min-h-11 min-w-11 items-center justify-center rounded-md px-unit-2 font-mono text-[13px] font-medium transition-colors lg:min-h-9 lg:min-w-9",
            active === locale
              ? "bg-primary text-on-primary"
              : "text-on-surface-variant hover:text-primary",
          )}
        >
          {labels[locale] ?? locale.toUpperCase()}
        </Link>
      ))}
    </div>
  )
}
