import { notFound } from "next/navigation"
import { setRequestLocale } from "next-intl/server"

import { PrototypeApp } from "@/components/prototype/prototype-app"
import { routing, type AppLocale } from "@/i18n/routing"

type Props = {
  params: Promise<{ locale: string }>
}

export default async function PrototypePage({ params }: Props) {
  const { locale } = await params

  if (!routing.locales.includes(locale as AppLocale)) {
    notFound()
  }

  setRequestLocale(locale)

  return <PrototypeApp locale={locale as AppLocale} />
}
