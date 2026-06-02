import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import "./globals.css";
import { AurionProviders } from "./providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Aurion Clinical AI — Admin Portal",
  description:
    "Administration and compliance portal for Aurion Clinical AI pilot.",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Server-side locale + message load. next-intl reads the
  // `aurion-locale` cookie via the request config in
  // `web/i18n/request.ts` — see there for the cookie-based locale
  // detection rationale (cookie over URL routing because the
  // portal is internal, no SEO).
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    // `suppressHydrationWarning` is the standard next-themes pattern
    // — the provider sets `<html class="dark">` on mount, which
    // technically diverges from the server-rendered (theme-less)
    // HTML. The warning suppression is scoped to <html> and doesn't
    // affect any child component's hydration checks.
    // `lang={locale}` is the standard a11y move — screen readers
    // switch pronunciation when this changes.
    <html lang={locale} suppressHydrationWarning>
      <body className={inter.className}>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <AurionProviders>{children}</AurionProviders>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
