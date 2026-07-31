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

        {/* Wordmark */}
        <Link
          href="/"
          className="flex min-h-11 shrink-0 items-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
          aria-label={`${t("brand")} — ${t("nav.home")}`}
        >
          {/* Icon + wordmark lockup, tagline omitted so it stays legible at nav height */}
          <Image
            src="/peritwin-nav.png"
            alt={t("brand")}
            width={901}
            height={250}
            priority
            className="h-11 w-auto md:h-14 lg:h-16"
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

          <LanguageSwitcher />

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
            <li className="mt-unit-2 flex flex-col gap-unit-2 pt-unit-2">
              <Button
                asChild
                className="h-12 rounded-lg bg-secondary font-mono text-[15px] font-medium text-on-secondary hover:bg-secondary/90"
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
