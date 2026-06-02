"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
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
 * Two variants:
 *   * `compact` — three icon buttons in a segmented control. Used in
 *     the sidebar's user-chip footer where horizontal space is
 *     tight (and especially tight when the sidebar is collapsed)
 *   * `inline` — same control with text labels alongside, suitable
 *     for the profile/settings page
 *
 * Hydration: next-themes sets the actual theme client-side on
 * mount, so the first render returns a placeholder (an empty
 * 3-slot rail) to avoid the "wrong theme flashes for 1 frame"
 * problem.
 */
interface ThemeToggleProps {
  variant?: "compact" | "inline";
  /** Sync the choice to the backend via PUT /profile.
   *  Default true; admin pages set false since there's no profile row. */
  persistToBackend?: boolean;
}

const OPTIONS: { value: "system" | "light" | "dark"; label: string; Icon: typeof Sun }[] = [
  { value: "system", label: "System", Icon: Monitor },
  { value: "light",  label: "Light",  Icon: Sun },
  { value: "dark",   label: "Dark",   Icon: Moon },
];

export default function ThemeToggle({
  variant = "compact",
  persistToBackend = true,
}: ThemeToggleProps) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  // Pre-hydration placeholder: identical layout, no active state.
  // Keeps the sidebar layout from jumping when next-themes mounts.
  if (!mounted) {
    return (
      <div
        className={
          "inline-flex items-center gap-0.5 rounded-aurion-md bg-white/[0.04] p-0.5 " +
          (variant === "inline" ? "" : "")
        }
        aria-hidden
      >
        {OPTIONS.map(({ value, Icon }) => (
          <div
            key={value}
            className="flex items-center justify-center rounded-aurion-sm px-2 py-1.5 text-white/40"
          >
            <Icon className="h-3.5 w-3.5" />
          </div>
        ))}
      </div>
    );
  }

  const handleChange = async (next: "system" | "light" | "dark") => {
    // 1. Flip local UI immediately
    setTheme(next);
    // 2. Best-effort backend persist (silent on failure — the local
    //    flip already happened; next-themes also writes localStorage
    //    so the choice survives a reload even if the backend POST
    //    fails)
    if (persistToBackend) {
      try {
        await updateMyProfile({ ui_theme: next });
      } catch {
        // No surfaced error — the local theme already flipped.
        // A future "settings out of sync" indicator could surface
        // failures explicitly, but it's overkill at this layer.
      }
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="inline-flex items-center gap-0.5 rounded-aurion-md bg-white/[0.04] p-0.5"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const isActive = theme === value;
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
              (isActive
                ? "bg-white/[0.10] text-white"
                : "text-white/55 hover:bg-white/[0.06] hover:text-white/85")
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
