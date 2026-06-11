/**
 * #418 accent theming — the curated palette + the DOM-apply helper.
 *
 * The five keys mirror the backend's `_ACCENT_PALETTE` in
 * `backend/app/api/v1/profile.py` exactly; that field validator is the
 * source of truth, so widening the palette means updating both sides.
 *
 * "gold" is the product default. Applying it CLEARS the `data-accent`
 * attribute so the `:root` gold triplets in `app/globals.css` drive the
 * render — existing (default) users keep a byte-identical DOM with no
 * override attribute at all. Any other key sets `html[data-accent=…]`,
 * which swaps the whole `--accent-*` scale the Tailwind `gold` tokens
 * read from.
 *
 * Compliance surfaces (CONFLICTS amber, masking, audit navy) use
 * separate tokens and are deliberately NOT routed through these vars.
 */
export const ACCENT_KEYS = ["gold", "teal", "indigo", "rose", "slate"] as const;
export type AccentKey = (typeof ACCENT_KEYS)[number];

/** Representative swatch fill — the 500 step of each scale, matching the
 *  `globals.css` triplets 1:1. Used only to paint the picker chips. */
export const ACCENT_SWATCH: Record<AccentKey, string> = {
  gold: "#C9A84C",
  teal: "#14B8A6",
  indigo: "#6366F1",
  rose: "#F43F5E",
  slate: "#64748B",
};

export function isAccentKey(v: unknown): v is AccentKey {
  return typeof v === "string" && (ACCENT_KEYS as readonly string[]).includes(v);
}

/**
 * Apply an accent to the document root.
 *
 * The default ("gold", or anything unrecognized) clears `data-accent` so
 * the `:root` defaults render unchanged; any other valid key sets the
 * attribute. Unknown values fall through to the default rather than
 * painting a broken theme — the backend validates on write, but a stale
 * cached profile shouldn't be trusted to. SSR no-op when `document` is
 * absent.
 */
export function applyAccent(accent: string | null | undefined): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (!accent || accent === "gold" || !isAccentKey(accent)) {
    delete root.dataset.accent;
    return;
  }
  root.dataset.accent = accent;
}
