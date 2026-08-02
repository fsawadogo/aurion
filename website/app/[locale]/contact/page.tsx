import type { Metadata } from "next"
import { getTranslations, setRequestLocale } from "next-intl/server"

import { ContactForm } from "@/components/contact-form"
import { Link } from "@/i18n/navigation"
import { routing } from "@/i18n/routing"

type Props = { params: Promise<{ locale: string }> }

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "contact" })
  return {
    title: t("meta.title"),
    description: t("meta.description"),
  }
}

export default async function ContactPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations("contact")

  return (
    <main className="min-h-[calc(100vh-6rem)] bg-surface px-margin-mobile pb-24 pt-28 md:px-margin-desktop md:pt-32">
      <div className="mx-auto max-w-lg">
        <p className="mb-3 font-mono text-[12px] font-bold tracking-[0.25em] text-secondary uppercase">
          {t("eyebrow")}
        </p>
        <h1 className="font-display text-3xl font-bold tracking-tight text-on-surface md:text-4xl">
          {t("title")}
        </h1>
        <p className="mt-4 text-body-md leading-relaxed text-on-surface-variant">
          {t("subtitle")}
        </p>

        <div className="card-shadow mt-10 rounded-medical border border-outline-variant/40 bg-surface-container-lowest p-6 md:p-8">
          <ContactForm />
        </div>

        <p className="mt-8 text-center">
          <Link
            href="/"
            className="text-sm text-on-surface-variant underline-offset-4 hover:underline"
          >
            {t("backHome")}
          </Link>
        </p>
      </div>
    </main>
  )
}
