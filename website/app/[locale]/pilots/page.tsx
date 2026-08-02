import type { Metadata } from "next"
import { getTranslations, setRequestLocale } from "next-intl/server"

import { Button } from "@/components/ui/button"
import { Link } from "@/i18n/navigation"
import { routing } from "@/i18n/routing"

type Props = { params: Promise<{ locale: string }> }

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "pilots" })
  return {
    title: t("meta.title"),
    description: t("meta.description"),
  }
}

export default async function PilotsPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations("pilots")

  return (
    <main className="flex min-h-[calc(100vh-6rem)] items-center bg-surface px-margin-mobile pt-28 pb-24 md:px-margin-desktop md:pt-48">
      <div className="mx-auto max-w-2xl text-center">
        <p className="mb-4 font-mono text-[12px] font-bold tracking-[0.25em] text-secondary uppercase">
          {t("eyebrow")}
        </p>

        <span className="mb-6 inline-flex items-center gap-unit-2 rounded-full border border-primary/20 bg-primary/10 px-unit-4 py-unit-2 font-mono text-[13px] font-medium text-primary">
          <span className="ai-pulse block h-2.5 w-2.5 rounded-full bg-emerald-500" aria-hidden />
          {t("status")}
        </span>

        <h1 className="font-display text-3xl font-bold tracking-tight text-on-surface md:text-5xl">
          {t("title")}
        </h1>
        <p className="mx-auto mt-6 max-w-xl text-body-md leading-relaxed text-on-surface-variant md:text-body-lg">
          {t("subtitle")}
        </p>

        <div className="mt-10 flex justify-center">
          <Button
            asChild
            className="h-auto rounded-lg bg-secondary px-unit-8 py-unit-4 font-mono text-[15px] font-medium text-on-secondary hover:bg-secondary/90"
          >
            <Link href="/contact">{t("cta")}</Link>
          </Button>
        </div>

        <p className="mt-8">
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
