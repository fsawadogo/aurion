import { defineRouting } from "next-intl/routing"

/** Supported locales — add codes here and mirror `messages/<locale>.json`. */
export const routing = defineRouting({
  locales: ["en", "fr"],
  defaultLocale: "en",
  localePrefix: "always",
})

export type AppLocale = (typeof routing.locales)[number]
