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
      {/* Editorial split: the pitch and the trust facts on the left, the
          form card (receipt grammar) on the right. Stacks on mobile. */}
      <div className="mx-auto grid w-full max-w-(--breakpoint-xl) items-start gap-unit-12 lg:grid-cols-[0.9fr_1.1fr] lg:gap-unit-16">

        <div>
          <p className="anim-rise font-mono text-[12px] font-bold tracking-[0.25em] text-secondary uppercase">
            {t("eyebrow")}
          </p>
          <h1 style={{ "--anim-delay": "90ms" } as React.CSSProperties} className="anim-rise mt-unit-4 font-display text-3xl font-bold tracking-tight text-on-surface md:text-4xl">
            {t("title")}
          </h1>
          <p style={{ "--anim-delay": "180ms" } as React.CSSProperties} className="anim-rise mt-unit-4 max-w-md text-body-md leading-relaxed text-on-surface-variant">
            {t("subtitle")}
          </p>

          {/* Trust facts — same kicker grammar as the landing sections. */}
          <dl style={{ "--anim-delay": "270ms" } as React.CSSProperties} className="anim-rise mt-unit-8 max-w-md divide-y divide-outline-variant/40 border-t border-outline-variant/40">
            <div className="py-unit-4">
              <dt className="font-mono text-[11px] tracking-[0.12em] text-primary uppercase">
                {t("facts.responseKicker")}
              </dt>
              <dd className="mt-1 text-[14.5px] leading-relaxed text-on-surface">
                {t("facts.responseLine")}
              </dd>
            </div>
            <div className="py-unit-4">
              <dt className="font-mono text-[11px] tracking-[0.12em] text-primary uppercase">
                {t("facts.pilotKicker")}
              </dt>
              <dd className="mt-1 text-[14.5px] leading-relaxed text-on-surface">
                {t("facts.pilotLine")}
              </dd>
            </div>
          </dl>

          <p style={{ "--anim-delay": "380ms" } as React.CSSProperties} className="anim-rise mt-unit-8">
            <Link
              href="/"
              className="text-sm text-on-surface-variant underline-offset-4 hover:underline"
            >
              {t("backHome")}
            </Link>
          </p>
        </div>

        <div style={{ "--anim-delay": "280ms" } as React.CSSProperties} className="anim-rise rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-unit-6 shadow-sm md:p-unit-8">
          <ContactForm />
        </div>

      </div>
    </main>
  )
}
