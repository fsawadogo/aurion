"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { updateMyProfile } from "@/lib/portal-api";

/**
 * Tri-state theme toggle (System / Light / Dark).
 *
 * Local UI flips via `next-themes` (instant, no roundtrip), backend
 * persistence via the `ui_theme` column added in #189. Storing
 * on the backend means the preference survives logout + syncs
 * across devices.
 *
 * Three variants:
 *   * `compact` — three icon buttons in a segmented control. Used in
 *     the expanded sidebar's user-chip footer where horizontal space
 *     is tight. Dark chrome (sits on the navy sidebar).
 *   * `icon` — a single button that cycles System → Light → Dark on
 *     each click, showing the current setting's icon. Used in the
 *     COLLAPSED sidebar rail where three buttons don't fit, so the
 *     control stays reachable regardless of sidebar state. Dark chrome.
 *   * `inline` — same segmented control with text labels alongside,
 *     for the profile/settings page. Light-surface chrome (with dark:
 *     variants) since it sits on a white card.
 *
 * Hydration: next-themes sets the actual theme client-side on
 * mount, so the first render returns a placeholder to avoid the
 * "wrong theme flashes for 1 frame" problem.
 */
interface ThemeToggleProps {
  variant?: "compact" | "inline" | "icon";
  /** Sync the choice to the backend via PUT /profile.
   *  Default true; admin/eval roles set false since there's no
   *  profile row — next-themes still persists to localStorage. */
  persistToBackend?: boolean;
}

type ThemeValue = "system" | "light" | "dark";

const OPTIONS: { value: ThemeValue; Icon: typeof Sun }[] = [
  { value: "system", Icon: Monitor },
  { value: "light", Icon: Sun },
  { value: "dark", Icon: Moon },
];

export default function ThemeToggle({
  variant = "compact",
  persistToBackend = true,
}: ThemeToggleProps) {
  const { theme, setTheme } = useTheme();
  const t = useTranslations("Theme");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Light-surface (profile card) vs dark-chrome (sidebar) styling.
  const isLight = variant === "inline";
  const railClass = isLight
    ? "inline-flex items-center gap-0.5 rounded-aurion-md border border-gray-200 bg-gray-50 p-0.5 dark:border-white/10 dark:bg-white/[0.04]"
    : "inline-flex items-center gap-0.5 rounded-aurion-md bg-white/[0.04] p-0.5";

  const handleChange = async (next: ThemeValue) => {
    // 1. Flip local UI immediately.
    setTheme(next);
    // 2. Best-effort backend persist (silent on failure — the local
    //    flip already happened; next-themes also writes localStorage
    //    so the choice survives a reload even if the backend POST
    //    fails).
    if (persistToBackend) {
      try {
        await updateMyProfile({ ui_theme: next });
      } catch {
        // No surfaced error — the local theme already flipped.
      }
    }
  };

  // ── Collapsed-rail single button: cycles on click. ──
  if (variant === "icon") {
    if (!mounted) {
      return (
        <div
          className="flex items-center justify-center rounded-aurion-sm bg-white/[0.04] p-1.5 text-white/40"
          aria-hidden
        >
          <Monitor className="h-4 w-4" />
        </div>
      );
    }
    const current =
      OPTIONS.find((o) => o.value === theme) ?? OPTIONS[0];
    const idx = OPTIONS.indexOf(current);
    const next = OPTIONS[(idx + 1) % OPTIONS.length];
    const CurrentIcon = current.Icon;
    return (
      <button
        type="button"
        onClick={() => void handleChange(next.value)}
        title={`${t("label")}: ${t(current.value)}`}
        aria-label={`${t("label")}: ${t(current.value)}`}
        className="flex items-center justify-center rounded-aurion-sm p-1.5 text-white/55 transition-colors duration-short hover:bg-white/[0.06] hover:text-white/90"
      >
        <CurrentIcon className="h-4 w-4" />
      </button>
    );
  }

  // Pre-hydration placeholder: identical layout, no active state.
  // Keeps the surrounding layout from jumping when next-themes mounts.
  if (!mounted) {
    return (
      <div className={railClass} aria-hidden>
        {OPTIONS.map(({ value, Icon }) => (
          <div
            key={value}
            className={
              "flex items-center justify-center rounded-aurion-sm px-2 py-1.5 " +
              (isLight ? "text-gray-300 dark:text-white/40" : "text-white/40")
            }
          >
            <Icon className="h-3.5 w-3.5" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div role="radiogroup" aria-label={t("label")} className={railClass}>
      {OPTIONS.map(({ value, Icon }) => {
        const isActive = theme === value;
        const label = t(value);
        const stateClass = isLight
          ? isActive
            ? "bg-white text-navy-700 shadow-sm dark:bg-white/10 dark:text-white"
            : "text-gray-500 hover:text-navy-700 dark:text-white/55 dark:hover:bg-white/[0.06] dark:hover:text-white/85"
          : isActive
            ? "bg-white/[0.10] text-white"
            : "text-white/55 hover:bg-white/[0.06] hover:text-white/85";
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={isActive}
            onClick={() => void handleChange(value)}
            title={label}
            aria-label={label}
            className={
              "flex items-center gap-1.5 rounded-aurion-sm px-2 py-1.5 text-[12px] font-medium transition-colors duration-short " +
              stateClass
            }
          >
            <Icon className="h-3.5 w-3.5" />
            {variant === "inline" && label}
          </button>
        );
      })}
    </div>
  );
}
