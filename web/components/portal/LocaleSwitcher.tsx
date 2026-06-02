"use client";

import { Languages } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { LOCALE_COOKIE, SUPPORTED_LOCALES } from "@/i18n/config";
import { updateMyProfile } from "@/lib/portal-api";

/**
 * Bilingual locale switcher (EN / FR).
 *
 * Compact segmented control sitting next to the theme toggle. On
 * change:
 *   1. Write the `aurion-locale` cookie so the next request's
 *      server-rendered HTML loads the new catalog.
 *   2. PUT /profile { ui_language } to sync the choice to the backend
 *      so it survives logout + crosses devices (column shipped in #189).
 *   3. router.refresh() — re-runs the layout's `getLocale()` +
 *      `getMessages()` server-side and re-renders without a full
 *      page reload. The chrome flips locale in place.
 *
 * Two variants (mirroring ThemeToggle):
 *   * `compact` — sidebar footer; two-letter labels (EN / FR)
 *   * `inline`  — settings page; full language names alongside
 */
interface LocaleSwitcherProps {
  variant?: "compact" | "inline";
  /** Sync the choice to the backend via PUT /profile. Default true;
   *  set false on admin pages (no profile row). */
  persistToBackend?: boolean;
}

export default function LocaleSwitcher({
  variant = "compact",
  persistToBackend = true,
}: LocaleSwitcherProps) {
  const locale = useLocale();
  const t = useTranslations("Locale");
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const handleChange = async (next: (typeof SUPPORTED_LOCALES)[number]) => {
    if (next === locale || busy) return;
    setBusy(true);
    // 1. Write cookie. Path=/ so server-side `cookies()` in any
    //    route picks it up; SameSite=Lax + 1-year expiry to
    //    survive normal browsing.
    const oneYear = 60 * 60 * 24 * 365;
    document.cookie =
      `${LOCALE_COOKIE}=${next}; path=/; max-age=${oneYear}; SameSite=Lax`;
    // 2. Best-effort backend sync (silent on failure — cookie
    //    already flipped + router.refresh() will load the new
    //    catalog regardless)
    if (persistToBackend) {
      try {
        await updateMyProfile({ ui_language: next });
      } catch {
        // Same logic as ThemeToggle — the local change already
        // succeeded; a future settings-out-of-sync indicator
        // could surface failures explicitly
      }
    }
    // 3. Re-render with the new catalog. Next.js re-runs the
    //    layout's getLocale() + getMessages() on the server.
    router.refresh();
    setBusy(false);
  };

  return (
    <div
      role="radiogroup"
      aria-label={t("label")}
      className="inline-flex items-center gap-0.5 rounded-aurion-md bg-white/[0.04] p-0.5"
    >
      {variant === "inline" && (
        <span
          aria-hidden
          className="flex items-center px-2 text-[12px] text-white/55"
        >
          <Languages className="h-3.5 w-3.5" />
        </span>
      )}
      {SUPPORTED_LOCALES.map((code) => {
        const isActive = locale === code;
        return (
          <button
            key={code}
            type="button"
            role="radio"
            aria-checked={isActive}
            onClick={() => void handleChange(code)}
            disabled={busy}
            title={t(code)}
            aria-label={t(code)}
            className={
              "flex items-center rounded-aurion-sm px-2 py-1.5 text-[12px] font-semibold transition-colors duration-short uppercase tracking-wide " +
              (isActive
                ? "bg-white/[0.10] text-white"
                : "text-white/55 hover:bg-white/[0.06] hover:text-white/85") +
              (busy ? " opacity-60" : "")
            }
          >
            {variant === "inline" ? t(code) : code}
          </button>
        );
      })}
    </div>
  );
}
