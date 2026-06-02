/**
 * next-intl configuration for the Aurion portal.
 *
 * Cookie-based locale (no URL prefix) — chosen over routing-based
 * locales because:
 *   * the portal is internal (no SEO), so /en/* vs /fr/* gives nothing
 *   * cookie keeps every existing link working (no .href + locale plumbing)
 *   * the switcher just sets a cookie + reloads
 *
 * Defaults to `en` when the cookie isn't set OR carries an unsupported
 * locale (forward-compat safety net for when we expand the union).
 */

export const SUPPORTED_LOCALES = ["en", "fr"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

/** Cookie name the LocaleSwitcher writes + the next-intl request
 *  config reads. Aurion-prefixed to avoid collisions with the
 *  hosting platform's own locale cookies. */
export const LOCALE_COOKIE = "aurion-locale";

export function isLocale(value: unknown): value is Locale {
  return (
    typeof value === "string"
    && (SUPPORTED_LOCALES as readonly string[]).includes(value)
  );
}
