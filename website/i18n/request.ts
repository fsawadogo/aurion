import { getRequestConfig } from "next-intl/server"

import { routing } from "./routing"

type AppMessages = {
  common: typeof import("../messages/en/common.json")
  home: typeof import("../messages/en/home.json")
  metadata: typeof import("../messages/en/metadata.json")
  contact: typeof import("../messages/en/contact.json")
  partners: typeof import("../messages/en/partners.json")
  pilots: typeof import("../messages/en/pilots.json")
}

async function loadMessages(locale: string): Promise<AppMessages> {
  const [common, home, metadata, contact, partners, pilots] = await Promise.all([
    import(`../messages/${locale}/common.json`),
    import(`../messages/${locale}/home.json`),
    import(`../messages/${locale}/metadata.json`),
    import(`../messages/${locale}/contact.json`),
    import(`../messages/${locale}/partners.json`),
    import(`../messages/${locale}/pilots.json`),
  ])

  return {
    common: common.default,
    home: home.default,
    metadata: metadata.default,
    contact: contact.default,
    partners: partners.default,
    pilots: pilots.default,
  }
}

export default getRequestConfig(async ({ requestLocale }) => {
  let locale = await requestLocale
  if (
    !locale ||
    !routing.locales.includes(locale as (typeof routing.locales)[number])
  ) {
    locale = routing.defaultLocale
  }

  return {
    locale,
    messages: await loadMessages(locale),
  }
})
