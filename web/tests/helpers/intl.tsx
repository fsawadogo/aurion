import { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

/**
 * Shared next-intl wrapper for component tests. `useTranslations` only
 * works inside a `NextIntlClientProvider`, so every component test
 * that touches an i18n key needs this shell.
 *
 * Defaults to English; pass `locale="fr"` to validate FR catalog
 * parity.
 */
export function withIntl(
  children: ReactNode,
  locale: "en" | "fr" = "en",
) {
  const messages = locale === "fr" ? frMessages : enMessages;
  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      {children}
    </NextIntlClientProvider>
  );
}
