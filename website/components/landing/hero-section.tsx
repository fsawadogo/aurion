import { BrainCircuit, Sparkles } from "lucide-react"
import Image from "next/image"
import { getTranslations } from "next-intl/server"

import { WatchVideoButton } from "@/components/landing/watch-video-button"
import { Button } from "@/components/ui/button"
import { Link } from "@/i18n/navigation"

export async function HeroSection() {
  const t = await getTranslations("home")

  return (
    <section className="relative mx-auto flex max-w-(--breakpoint-2xl) items-center overflow-clip px-margin-mobile py-unit-12 md:px-margin-desktop md:py-unit-16 lg:min-h-[85vh]">
      {/* Ambient bloom — anchors the centred mobile hero, which carries no image */}
      <div
        className="absolute -top-24 -right-24 h-64 w-64 rounded-full bg-primary/10 blur-3xl lg:hidden"
        aria-hidden
      />

      <div className="relative z-10 grid items-center gap-unit-12 lg:grid-cols-2 lg:gap-unit-16">

        {/* Copy — centred on mobile, left-aligned from lg */}
        <div className="flex flex-col items-center text-center lg:items-start lg:text-left">
          <div className="inline-flex items-center gap-unit-2 rounded-full border border-secondary/20 bg-secondary/10 px-unit-4 py-unit-2 font-mono text-[13px] font-medium text-secondary sm:text-[14px] lg:border-primary/20 lg:bg-primary/10 lg:text-primary">
            <Sparkles className="h-4 w-4" aria-hidden />
            {t("hero.badge")}
          </div>

          <h1 className="mt-unit-6 font-display text-[2rem] leading-tight font-bold tracking-[-0.02em] text-balance text-on-surface sm:text-[2.5rem] lg:mt-unit-8 lg:text-display-lg lg:leading-[1.1]">
            {t("hero.titleLead")}{" "}
            <span className="text-primary">{t("hero.titleAccent")}</span>
          </h1>

          <p className="mt-unit-4 max-w-md text-body-md text-on-surface-variant lg:mt-unit-6 lg:max-w-2xl lg:text-body-lg">
            {t("hero.subtitle")}
          </p>

          {/*
            Mobile leads with a single gradient CTA; the secondary actions and
            the trust line appear from lg, where there is room for them.
          */}
          <Button
            asChild
            className="mt-unit-8 h-auto w-full rounded-xl bg-linear-to-br from-primary to-secondary px-unit-8 py-unit-4 font-mono text-[15px] font-medium text-on-primary shadow-lg shadow-primary/25 transition-transform active:scale-[0.98] sm:w-auto lg:hidden"
          >
            <Link href="/contact">{t("philosophy.cta")}</Link>
          </Button>

          {/* Mobile: watch-video sits under the primary CTA so it's reachable on phones too. */}
          <div className="mt-unit-4 lg:hidden">
            <WatchVideoButton />
          </div>

          <div className="mt-unit-8 hidden flex-wrap items-center gap-unit-4 lg:flex">
            <Button
              asChild
              className="h-auto rounded-lg bg-secondary px-unit-8 py-unit-4 font-mono text-[15px] font-medium text-on-secondary shadow-xl transition-all hover:bg-secondary/90 active:scale-95"
            >
              <Link href="/contact">{t("hero.scheduleDemo")}</Link>
            </Button>
            <WatchVideoButton />
          </div>

          <div className="mt-unit-6 hidden w-full items-center gap-unit-4 lg:flex">
            <p className="font-mono text-[14px] whitespace-nowrap text-outline">
              {t("hero.trustedBy")}
            </p>
            <div className="h-px flex-grow bg-outline-variant/40" />
          </div>
        </div>

        {/* Visual — desktop only; the mobile design leads with type alone */}
        <div className="relative hidden lg:block">
          <div
            className="absolute -inset-8 rounded-full bg-linear-to-tr from-primary/10 to-secondary/10 blur-[100px]"
            aria-hidden
          />

          <div className="card-shadow relative overflow-hidden rounded-medical border border-outline-variant/30 bg-surface-container-lowest">
            <Image
              src="/hero-digital-twin.jpg"
              alt={t("hero.imageAlt")}
              width={1376}
              height={768}
              priority
              sizes="50vw"
              className="aspect-16/9 w-full object-cover"
            />

            <div className="glass-panel absolute right-unit-6 bottom-unit-6 left-unit-6 flex items-center gap-unit-4 rounded-xl p-unit-4">
              <div className="ai-pulse flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary">
                <BrainCircuit className="h-6 w-6" aria-hidden />
              </div>
              <div className="min-w-0">
                <p className="font-mono text-[14px] font-bold text-primary">
                  {t("hero.callout.name")}
                </p>
                <p className="text-[13px] leading-snug text-on-surface-variant">
                  {t("hero.callout.quote")}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
