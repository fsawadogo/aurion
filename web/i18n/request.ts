import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { DEFAULT_LOCALE, isLocale, LOCALE_COOKIE } from "./config";

/**
 * Server-side request config — next-intl reads this on every
 * request to know which locale to serve + which message catalog
 * to load.
 *
 * We read the locale from the `aurion-locale` cookie. The cookie
 * is set by `<LocaleSwitcher />` (and on first login, mirrored from
 * the user's `ui_language` profile column shipped in #189).
 */
export default getRequestConfig(async () => {
  const cookieStore = cookies();
  const raw = cookieStore.get(LOCALE_COOKIE)?.value;
  const locale = isLocale(raw) ? raw : DEFAULT_LOCALE;

  // Dynamic import keeps the unused catalog out of every bundle.
  const messages = (
    await import(`../messages/${locale}.json`)
  ).default;

  return { locale, messages };
});
