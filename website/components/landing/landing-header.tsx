"use client"

import { Menu, X } from "lucide-react"
import Image from "next/image"
import { useTranslations } from "next-intl"
import { useState } from "react"

import { LanguageSwitcher } from "@/components/language-switcher"
import { Button } from "@/components/ui/button"
import { Link } from "@/i18n/navigation"
import { SITE } from "@/lib/site"

/** Page menu — Partners and Pilots; Physician portal and Contact us render distinctly. */
const PAGE_LINKS = [
  { href: "/partners", key: "partners" },
  { href: "/pilots", key: "pilots" },
] as const

export function LandingHeader() {
  const t = useTranslations("common")
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <header className="glass-panel fixed top-0 z-100 w-full border-x-0 border-t-0 border-b border-b-outline-variant/30">
      <div className="mx-auto flex max-w-(--breakpoint-2xl) items-center justify-between gap-unit-6 px-margin-mobile py-unit-4 md:px-margin-desktop md:py-unit-6">

        <Link
          href="/"
          className="flex min-h-11 min-w-0 items-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
          aria-label={`${t("brand")} — ${t("nav.home")}`}
        >
          {/* Icon + wordmark as separate pieces (per CPO: icon bigger, writing
              as-is). icon = crop of peritwin-mark.png; word = crop of the
              deleted peritwin-nav.png (git history) — see
              docs/plans/website-header-icon-bigger.md. The labeled Link
              carries the accessible name, so both imgs are decorative (alt="") */}
          <Image
            src="/peritwin-icon.png"
            alt=""
            width={331}
            height={524}
            priority
            className="h-12 w-auto min-[360px]:h-18 md:h-28"
          />
          <Image
            src="/peritwin-word.png"
            alt=""
            width={705}
            height={250}
            priority
            className="ml-1 h-10 w-auto min-[360px]:h-14 md:ml-3 md:h-18"
          />
        </Link>

        <div className="flex items-center gap-unit-4">
          {/* Page menu — desktop */}
          <nav className="hidden items-center gap-unit-6 lg:flex">
            {PAGE_LINKS.map((link) => (
              <Link
                key={link.key}
                href={link.href}
                className="font-mono text-[14px] font-medium tracking-tight text-on-surface-variant transition-colors hover:text-primary"
              >
                {t(`nav.${link.key}`)}
              </Link>
            ))}
            {/* Physician portal — purple outline so it stands out; external app */}
            <a
              href={SITE.physicianPortalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-lg border-[1.5px] border-secondary px-unit-4 py-unit-2 font-mono text-[14px] font-medium text-secondary transition-colors hover:bg-secondary/5"
            >
              {t("nav.physicianPortal")}
            </a>
          </nav>

          {/* From md the switcher lives in-row; below md it gets its own
              row under the logo (per pilot feedback: EN/FR under, logo
              takes the whole space next to the menu). */}
          <div className="hidden md:block">
            <LanguageSwitcher />
          </div>

          <Button
            asChild
            className="hidden h-11 rounded-lg bg-secondary px-unit-6 font-mono text-[14px] font-medium text-on-secondary transition-all hover:bg-secondary/90 active:scale-95 sm:inline-flex"
          >
            <Link href="/contact">{t("nav.contact")}</Link>
          </Button>

          {/* Mobile menu toggle */}
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            className="-mr-unit-2 flex h-11 w-11 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:text-primary lg:hidden"
            aria-expanded={menuOpen}
            aria-controls="landing-mobile-nav"
            aria-label={menuOpen ? t("nav.closeMenu") : t("nav.openMenu")}
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Sub-md switcher row — EN/FR under the logo row, right-aligned. */}
      <div className="flex justify-end px-margin-mobile pb-unit-2 md:hidden">
        <LanguageSwitcher />
      </div>

      {menuOpen && (
        <nav
          id="landing-mobile-nav"
          className="border-t border-outline-variant/30 bg-surface-container-lowest px-margin-mobile py-unit-6 lg:hidden"
        >
          <ul className="flex flex-col gap-unit-2">
            {PAGE_LINKS.map((link) => (
              <li key={link.key}>
                <Link
                  href={link.href}
                  onClick={() => setMenuOpen(false)}
                  className="block rounded-lg px-unit-4 py-unit-3 font-mono text-[15px] text-on-surface-variant transition-colors hover:bg-surface-container hover:text-primary"
                >
                  {t(`nav.${link.key}`)}
                </Link>
              </li>
            ))}
            <li>
              <a
                href={SITE.physicianPortalUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setMenuOpen(false)}
                className="block rounded-lg border-[1.5px] border-secondary px-unit-4 py-unit-3 font-mono text-[15px] font-medium text-secondary transition-colors hover:bg-secondary/5"
              >
                {t("nav.physicianPortal")}
              </a>
            </li>
            <li className="mt-unit-2 pt-unit-2">
              <Button
                asChild
                className="h-12 w-full rounded-lg bg-secondary font-mono text-[15px] font-medium text-on-secondary hover:bg-secondary/90"
              >
                <Link href="/contact" onClick={() => setMenuOpen(false)}>
                  {t("nav.contact")}
                </Link>
              </Button>
            </li>
          </ul>
        </nav>
      )}
    </header>
  )
}
