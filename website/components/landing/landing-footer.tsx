import { ChevronRight, ShieldCheck } from "lucide-react"
import Image from "next/image"
import { getTranslations } from "next-intl/server"

import { Link } from "@/i18n/navigation"
import { LOGO, SITE } from "@/lib/site"

const PLATFORM_LINKS = [
  { key: "digitalTwin", href: "#platform" },
  { key: "diagnostics", href: "#workbench" },
  { key: "continuum", href: "#continuum" },
  { key: "interoperability", href: "#colleague" },
] as const

/** Company column — Physician portal renders first, purple-outlined; rest are internal routes. */
const COMPANY_LINKS = [
  { key: "partners", href: "/partners" },
  { key: "pilots", href: "/pilots" },
  { key: "contact", href: "/contact" },
] as const

export async function LandingFooter() {
  const t = await getTranslations("common")
  const tHome = await getTranslations("home")

  return (
    <footer className="w-full border-t border-outline-variant/20 bg-surface-container-low py-unit-12 md:py-unit-16">
      <div className="mx-auto grid max-w-(--breakpoint-2xl) grid-cols-1 gap-unit-12 px-margin-mobile md:grid-cols-2 md:px-margin-desktop lg:grid-cols-4 lg:gap-gutter">

        <div className="space-y-unit-4">
          {/* Full lockup — the tagline is part of the artwork, so no separate line */}
          <Image
            src={LOGO.src}
            alt={`${t("brand")} — ${t("footer.tagline")}`}
            width={LOGO.width}
            height={LOGO.height}
            className="h-auto w-40 max-w-full md:w-[260px]"
          />
        </div>

        <div className="hidden space-y-unit-4 lg:block">
          <h2 className="font-mono text-[13px] font-bold tracking-widest text-on-surface uppercase">
            {t("footer.platform.title")}
          </h2>
          <ul className="text-[15px] text-on-surface-variant space-y-unit-1 lg:space-y-unit-2">
            {PLATFORM_LINKS.map((link) => (
              <li key={link.key}>
                <a className="inline-flex min-h-11 items-center transition-colors hover:text-secondary lg:min-h-0" href={link.href}>
                  {t(`footer.platform.${link.key}`)}
                </a>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-unit-4">
          <h2 className="font-mono text-[13px] font-bold tracking-widest text-on-surface uppercase">
            {t("footer.company.title")}
          </h2>
          <ul className="text-[15px] text-on-surface-variant space-y-unit-1 lg:space-y-unit-2">
            {/* Physician portal — purple outline so it stands out; external app */}
            <li>
              <a
                href={SITE.physicianPortalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="my-unit-1 inline-flex min-h-11 items-center rounded-lg border-[1.5px] border-secondary px-unit-4 font-medium text-secondary transition-colors hover:bg-secondary/5 lg:min-h-0 lg:py-unit-2"
              >
                {t("footer.company.physicianPortal")}
              </a>
            </li>
            {COMPANY_LINKS.map((link) => (
              <li key={link.key}>
                <Link
                  className="inline-flex min-h-11 items-center transition-colors hover:text-secondary lg:min-h-0"
                  href={link.href}
                >
                  {t(`footer.company.${link.key}`)}
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div className="hidden space-y-unit-4 lg:block">
          <h2 className="font-mono text-[13px] font-bold tracking-widest text-on-surface uppercase">
            {t("footer.connect.title")}
          </h2>
          <p className="text-[15px] leading-relaxed text-on-surface-variant">
            {t("footer.connect.body")}
          </p>
          <Link
            href="/contact"
            className="inline-flex items-center gap-unit-2 rounded-lg bg-secondary px-unit-6 py-unit-3 font-mono text-[14px] font-medium text-on-secondary transition-colors hover:bg-secondary/90"
          >
            {t("footer.connect.submit")}
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>
      </div>

      <div className="mx-auto mt-unit-12 max-w-(--breakpoint-2xl) border-t border-outline-variant/20 px-margin-mobile pt-unit-8 text-center md:px-margin-desktop lg:mt-unit-16 lg:pt-unit-12">
        {/* Reassurance CTA — mobile only; desktop carries this in its own section */}
        <Link
          href="/contact"
          className="mb-unit-8 flex min-h-14 w-full items-center justify-center gap-unit-2 rounded-xl border-[1.5px] border-primary font-mono text-[15px] font-bold text-primary transition-colors active:bg-primary/5 lg:hidden"
        >
          <ShieldCheck className="h-5 w-5" aria-hidden />
          {tHome("philosophy.title")}
        </Link>

        <p className="mb-unit-2 font-mono text-[13px] font-bold tracking-widest text-on-surface uppercase lg:hidden">
          {t("company")}
        </p>

        <p className="font-mono text-[13px] text-on-surface-variant opacity-70">
          {t("footer.copyright", {
            year: new Date().getFullYear(),
            company: SITE.companyLegalName,
          })}
        </p>
      </div>
    </footer>
  )
}
