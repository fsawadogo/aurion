import type { Config } from "tailwindcss";

/**
 * Aurion web design tokens.
 *
 * Mirrors the iOS Theme.swift palette + scale 1:1 so the web portal
 * and the iOS app read as the same product. The values below match
 * the canonical Swift definitions in `ios/Aurion/Aurion/App/Theme.swift`:
 *
 *   navy.700  / aurionNavy        (#0C1B37)   — primary surface
 *   navy.600  / aurionNavyLight   (#16284E)   — gradient stop
 *   navy.800  / aurionNavyDark    (#081226)   — gradient end
 *   gold.500  / aurionGold        (#C9A84C)   — accent
 *   gold.300  / aurionGoldLight   (#E5D082)   — gradient top
 *   gold.600  / aurionGoldDark    (#B5953D)   — gradient bottom
 *
 * Semantic colors (amber/green/red/blue) come from iOS verbatim. Status
 * colors get light/dark pairs because the iOS palette adapts to user
 * appearance — the web ships light-mode-only today but the tokens are
 * ready for a future dark-mode pass.
 */
const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  // Class-based dark mode — `<html class="dark">` toggles all
  // `dark:` variants. Driven by next-themes (see app/providers.tsx).
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // ── Brand ────────────────────────────────────────────────
        navy: {
          DEFAULT: "#0C1B37",
          50: "#E8EBF2",
          100: "#C5CCE0",
          200: "#9EAACB",
          300: "#7788B6",
          400: "#5066A1",
          500: "#2A448C",
          600: "#16284E", // aurionNavyLight
          700: "#0C1B37", // aurionNavy (canonical)
          800: "#081226", // aurionNavyDark
          900: "#050A15",
        },
        // #418 accent theming: the gold scale reads CSS variables
        // (RGB triplets so /NN opacity modifiers compose). :root holds
        // today's gold values → byte-identical default; html[data-accent=X]
        // in globals.css swaps the whole scale per the physician preference.
        // Compliance tokens (accent.red/amber, navy) are separate — not themeable.
        gold: {
          DEFAULT: "rgb(var(--accent-500) / <alpha-value>)",
          50: "rgb(var(--accent-50) / <alpha-value>)",
          100: "rgb(var(--accent-100) / <alpha-value>)",
          200: "rgb(var(--accent-200) / <alpha-value>)",
          300: "rgb(var(--accent-300) / <alpha-value>)",
          400: "rgb(var(--accent-400) / <alpha-value>)",
          500: "rgb(var(--accent-500) / <alpha-value>)",
          600: "rgb(var(--accent-600) / <alpha-value>)",
          700: "rgb(var(--accent-700) / <alpha-value>)",
          800: "rgb(var(--accent-800) / <alpha-value>)",
          900: "rgb(var(--accent-900) / <alpha-value>)",
        },
        // ── Semantic (iOS aurionAmber/Green/Red/Blue) ────────────
        accent: {
          amber: "#D9941F",
          green: "#2E9E6A",
          red:   "#D9352B",
          blue:  "#2D6CDF",
        },
        // ── Adaptive surfaces (light-mode values for now) ────────
        canvas: "#F5F6FA",    // page background
        surface: "#FFFFFF",   // card / panel
        muted: "#EEF0F3",     // input fill / alt row
        // Hairline = visible-but-quiet divider. Pre-composited result
        // of rgba(12, 27, 55, 0.08) over #FFFFFF. Concrete hex (not
        // rgba) so existing Tailwind utilities like `border-hairline`
        // work without alpha-channel modifier acrobatics. The slightly-
        // darker hover variant (#D1D6E0) is inlined as an arbitrary
        // value at the only callsite — wasn't worth nesting the colour
        // for one place.
        hairline: "#E6E9EE",
        // ── Adaptive surfaces (Phase A4 dark mode) ─────────────
        // These read the CSS custom properties defined in
        // app/globals.css :root + html.dark, so `bg-aurion-card`,
        // `text-aurion-primary`, etc. flip automatically when
        // next-themes sets html.dark. Use these instead of the
        // raw `surface` / `text-navy-700` utilities anywhere the
        // surface should adapt to mode.
        "aurion-canvas":    "var(--surface-canvas)",
        "aurion-card":      "var(--surface-card)",
        "aurion-muted":     "var(--surface-muted)",
        "aurion-hairline":  "var(--surface-hairline)",
        "aurion-primary":   "var(--text-primary)",
        "aurion-secondary": "var(--text-secondary)",
        "aurion-tertiary":  "var(--text-tertiary)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        // iOS uses SF Pro Display for headlines on big sizes; web
        // matches with the same tight-tracking Inter weight.
        display: ["Inter", "system-ui", "sans-serif"],
      },
      fontSize: {
        // Aurion type scale — matches `.aurionFont(...)` on iOS.
        // Numbers are in rem (16px base) so they scale with the user's
        // browser font-size preference. Tracking is configured per
        // utility class in globals.css to mirror the iOS letterSpacing
        // values (-0.68 / -0.5 / -0.3 / -0.2).
        "aurion-micro":     ["0.6875rem", { lineHeight: "0.875rem", letterSpacing: "0.04em", fontWeight: "600" }],
        "aurion-caption":   ["0.8125rem", { lineHeight: "1.125rem" }],
        "aurion-callout":   ["0.9375rem", { lineHeight: "1.25rem", fontWeight: "500" }],
        "aurion-body":      ["1.0625rem", { lineHeight: "1.5rem" }],
        "aurion-headline":  ["1.0625rem", { lineHeight: "1.375rem", fontWeight: "600" }],
        "aurion-title-3":   ["1.25rem", { lineHeight: "1.625rem", letterSpacing: "-0.011em", fontWeight: "600" }],
        "aurion-title":     ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.014em", fontWeight: "600" }],
        "aurion-display":   ["1.75rem", { lineHeight: "2.125rem", letterSpacing: "-0.018em", fontWeight: "700" }],
        "aurion-large-title": ["2.125rem", { lineHeight: "2.5rem", letterSpacing: "-0.02em", fontWeight: "700" }],
      },
      borderRadius: {
        "aurion-xs": "0.375rem", // 6px
        "aurion-sm": "0.625rem", // 10px
        "aurion-md": "0.75rem",  // 12px — buttons
        "aurion-lg": "1rem",     // 16px — cards
        "aurion-xl": "1.25rem",  // 20px — sheets
        "aurion-2xl": "1.75rem", // 28px
      },
      boxShadow: {
        // Card — same 2-layer recipe as iOS cards (1px subtle + 8px diffuse).
        "card":
          "0 1px 2px 0 rgba(12, 27, 55, 0.04), 0 6px 18px -6px rgba(12, 27, 55, 0.08)",
        "card-hover":
          "0 2px 4px 0 rgba(12, 27, 55, 0.05), 0 12px 28px -8px rgba(12, 27, 55, 0.12)",
        // Premium gold drop on primary buttons (iOS aurionGold @ 0.24 / 8 / 4).
        "gold":
          "0 4px 12px -2px rgba(201, 168, 76, 0.30), 0 2px 4px -2px rgba(201, 168, 76, 0.20)",
        "gold-strong":
          "0 8px 24px -4px rgba(201, 168, 76, 0.45), 0 4px 8px -2px rgba(201, 168, 76, 0.25)",
        // Soft inner ring for elevated chrome (e.g. logo lockup card).
        "inset-hairline": "inset 0 0 0 1px rgba(255, 255, 255, 0.08)",
        // Sidebar — barely-there separator.
        "nav": "0 1px 2px 0 rgba(0, 0, 0, 0.06)",
      },
      backgroundImage: {
        // Linear navy (login + capture chrome) — iOS aurionNavyLight → aurionNavy.
        "aurion-navy":
          "linear-gradient(180deg, #16284E 0%, #0C1B37 100%)",
        // Radial navy (deeper hero — login glow, dashboard accent panel).
        "aurion-navy-radial":
          "radial-gradient(ellipse at 50% 0%, #16284E 0%, #0C1B37 65%, #081226 100%)",
        // Gold avatar / icon gradient.
        "aurion-gold":
          "radial-gradient(circle at 30% 30%, #E5D082 0%, #B5953D 100%)",
        // Gold accent strip (button hover sheen, progress shimmer).
        "aurion-gold-sheen":
          "linear-gradient(90deg, #C9A84C 0%, #E5D082 50%, #C9A84C 100%)",
      },
      animation: {
        "aurion-fade-in":  "aurion-fade-in 0.32s cubic-bezier(0.32, 0.72, 0, 1) both",
        "aurion-slide-up": "aurion-slide-up 0.32s cubic-bezier(0.32, 0.72, 0, 1) both",
        "aurion-scale-in": "aurion-scale-in 0.20s cubic-bezier(0.32, 0.72, 0, 1) both",
        "aurion-pulse":    "aurion-pulse 1.6s ease-in-out infinite",
        "aurion-glow":     "aurion-glow 3.2s ease-in-out infinite",
        // Legacy aliases — keep so existing usage doesn't break.
        "fade-in":         "aurion-fade-in 0.32s cubic-bezier(0.32, 0.72, 0, 1) both",
        "slide-up":        "aurion-slide-up 0.32s cubic-bezier(0.32, 0.72, 0, 1) both",
      },
      transitionTimingFunction: {
        // The iOS canonical content-swap curve (AurionAnimation.smooth).
        "aurion": "cubic-bezier(0.32, 0.72, 0, 1)",
        "spring": "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
      transitionDuration: {
        "micro": "120ms",
        "short": "200ms",
        "aurion": "320ms",
      },
      padding: {
        // Reads the CSS custom property published by `<Sidebar>` on
        // every collapse toggle (`--aurion-sidebar-width`). 256px
        // fallback matches the uncollapsed Tailwind class width so
        // SSR + first paint look right before the client hydrates
        // and reads localStorage.
        "aurion-sidebar": "var(--aurion-sidebar-width, 256px)",
      },
    },
  },
  plugins: [],
};

export default config;
