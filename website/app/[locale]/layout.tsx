import type { Metadata } from "next"
import { notFound } from "next/navigation"
import { NextIntlClientProvider } from "next-intl"
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server"

import { LandingHeader } from "@/components/landing/landing-header"
import { LocaleHtmlAttributes } from "@/components/locale-html-attributes"
import { routing } from "@/i18n/routing"
import { LOGO, SITE } from "@/lib/site"

type Props = {
  children: React.ReactNode
  params: Promise<{ locale: string }>
}

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "metadata" })

  return {
    // Without this, the relative openGraph image resolves against localhost.
    // Netlify sets URL at build time; NEXT_PUBLIC_SITE_URL overrides it.
    metadataBase: new URL(SITE.baseUrl),
    title: t("title"),
    description: t("description"),
    publisher: SITE.companyLegalName,
    openGraph: {
      siteName: SITE.productName,
      title: t("title"),
      description: t("description"),
      locale,
      images: [
        {
          url: LOGO.src,
          width: LOGO.width,
          height: LOGO.height,
          alt: `${SITE.productName} — ${SITE.companyLegalName}`,
        },
      ],
    },
    generator: "v0.app",
    // Icons come from the app/icon.png and app/apple-icon.png file conventions.
    manifest: "/manifest.webmanifest",
  }
}

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params

  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) {
    notFound()
  }

  setRequestLocale(locale)
  const messages = await getMessages()

  return (
    <NextIntlClientProvider messages={messages} locale={locale}>
      <LocaleHtmlAttributes />
      <LandingHeader />
      {children}
    </NextIntlClientProvider>
  )
} 