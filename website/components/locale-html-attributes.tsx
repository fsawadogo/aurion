"use client"

import { useLocale } from "next-intl"
import { useEffect } from "react"

/** Syncs `<html lang>` with the active locale (root layout stays locale-agnostic). */
export function LocaleHtmlAttributes() {
  const locale = useLocale()

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  return null
}
