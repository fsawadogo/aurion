import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AurionProviders } from "./providers";
import { LocaleProvider } from "@/i18n/LocaleProvider";
import { DEFAULT_LOCALE } from "@/i18n/config";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Aurion Clinical AI — Admin Portal",
  description:
    "Administration and compliance portal for Aurion Clinical AI pilot.",
};

/**
 * Root layout (DEPLOY-WEB):
 *
 * Server shell only. Under `output: "export"` we can't call
 * `getLocale()` / `getMessages()` (those need a request to read the
 * cookie from). Locale resolution moved to the client-side
 * `<LocaleProvider />`, which:
 *   - hydrates DEFAULT_LOCALE on first render (matches what `next
 *     build` baked into the static HTML)
 *   - reads `aurion-locale` from `document.cookie` on mount
 *   - swaps the locale + `<html lang>` if the cookie disagrees
 *
 * The `lang={DEFAULT_LOCALE}` here matches what the static HTML
 * ships; LocaleProvider updates `document.documentElement.lang` on
 * mount when the cookie carries a different locale.
 *
 * `suppressHydrationWarning` on <html> is the standard next-themes
 * pattern (theme class flips on mount) + now also covers the
 * locale-attribute flip on first paint. Scope is limited to <html>
 * so it doesn't mask hydration mismatches in any child.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang={DEFAULT_LOCALE} suppressHydrationWarning>
      <body className={inter.className}>
        <LocaleProvider>
          <AurionProviders>{children}</AurionProviders>
        </LocaleProvider>
      </body>
    </html>
  );
}
