"use client";

import { NextIntlClientProvider } from "next-intl";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { DEFAULT_LOCALE, isLocale, LOCALE_COOKIE, type Locale } from "./config";

/**
 * Client-side locale provider for the Aurion portal.
 *
 * Replaces the server-side next-intl request config
 * (`i18n/request.ts`) which can't run under `output: "export"` —
 * there's no request to serve.
 *
 * Catalog loading: both EN + FR JSON catalogs are statically
 * imported at module load so they ship in the same client bundle.
 * Combined gzipped weight is small (≈25 KB pre-gzip today), well
 * inside the budget for an internal admin tool. A future scale-up
 * (dozens of locales, MB-class catalogs) would justify a
 * dynamic-import-per-locale split — not worth the complexity today.
 *
 * Locale resolution:
 *   1. Initial render uses DEFAULT_LOCALE so the static HTML emitted
 *      by `next build` is deterministic — every visitor gets the
 *      same pre-rendered shell regardless of cookie state.
 *   2. On mount, parse `document.cookie` for `aurion-locale` and
 *      flip `<NextIntlClientProvider locale=...>` + `<html lang=...>`
 *      to the cookie value if valid.
 *   3. Falls back to DEFAULT_LOCALE if the cookie is missing or
 *      carries an unsupported value (forward-compat with the
 *      `SUPPORTED_LOCALES` union).
 *
 * The brief FOUC on first paint (EN → cookie-resolved locale) is
 * acceptable for an authenticated portal — visible only on initial
 * cold load before hydration, and SSR-style cookie reads aren't
 * available under static export anyway.
 */

function readLocaleCookie(): Locale {
  if (typeof document === "undefined") return DEFAULT_LOCALE;
  // Cookie format: `aurion-locale=fr` somewhere in the cookie
  // jar. Match the value between `=` and `;` (or end-of-string).
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${LOCALE_COOKIE}=([^;]*)`),
  );
  if (!match) return DEFAULT_LOCALE;
  const raw = decodeURIComponent(match[1]);
  return isLocale(raw) ? raw : DEFAULT_LOCALE;
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    const resolved = readLocaleCookie();
    setLocale(resolved);
    // Mirror onto <html lang=...> so screen readers + browser
    // hyphenation pick up the change. The server-rendered HTML
    // shipped DEFAULT_LOCALE in `app/layout.tsx`; we override
    // post-hydration when the cookie disagrees.
    if (typeof document !== "undefined") {
      document.documentElement.lang = resolved;
    }
  }, []);

  const messages = useMemo(
    () => (locale === "fr" ? frMessages : enMessages),
    [locale],
  );

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      {children}
    </NextIntlClientProvider>
  );
}
