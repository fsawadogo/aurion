"use client";

import { ThemeProvider } from "next-themes";
import type { ReactNode } from "react";

/**
 * Root client-side providers for the portal.
 *
 * Wraps the app tree with `next-themes` so the class-based dark mode
 * works across every route. The provider toggles `<html class="dark">`
 * which the adaptive Tailwind tokens in `globals.css` flip in response.
 *
 * Configuration choices:
 *   * `attribute="class"` — write to `<html class=...>`, matches
 *     Tailwind's `darkMode: 'class'` config
 *   * `defaultTheme="system"` — follow the OS preference until the
 *     user picks light/dark explicitly
 *   * `enableSystem` — the system option appears in the theme menu
 *   * `disableTransitionOnChange` — avoid the flash-of-mid-transition
 *     when flipping (browsers can't atomically swap many CSS vars)
 *
 * The user's stored preference lives in the backend on
 * `physician_profiles.ui_theme` (#189). The user-menu toggle reads/
 * writes that column AND lets next-themes manage the immediate UI
 * state, so the choice persists across devices.
 */
export function AurionProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {children}
    </ThemeProvider>
  );
}
