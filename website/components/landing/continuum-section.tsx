import {
  CalendarCheck,
  Siren,
  Stethoscope,
  Syringe,
  TrendingUp,
  type LucideIcon,
} from "lucide-react"
import { getTranslations } from "next-intl/server"

import { Link } from "@/i18n/navigation"
import { RevealGroup } from "@/components/reveal-group"
import { cn } from "@/lib/utils"

type Stage = { title: string; body: string; cta?: string }

/**
 * The journey is a real sequence, so the section is drawn as one: a
 * single spine that gains weight left → right (Peri's picture of the
 * patient accumulating), five stations on the line, no cards. The OR
 * station — where PeriTwin is most active — is the only filled node
 * and carries the section's one link.
 */
const STAGE_ICONS: LucideIcon[] = [Siren, Stethoscope, CalendarCheck, Syringe, TrendingUp]
const FEATURED_INDEX = 3 // OR / Procedure

export async function ContinuumSection() {
  const t = await getTranslations("home")
  const stages = t.raw("continuum.stages") as Stage[]

  return (
    <section
      id="continuum"
      className="scroll-mt-24 bg-surface-container-low py-unit-12 md:py-unit-16"
    >
      <RevealGroup className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">
        <div className="max-w-2xl" data-reveal>
          <h2 className="font-display text-[1.75rem] leading-tight font-semibold tracking-[-0.015em] text-on-surface sm:text-[2rem] lg:text-headline-lg">
            {t("continuum.title")}
          </h2>
          <p className="mt-unit-3 text-body-md text-on-surface-variant lg:text-body-lg">
            {t("continuum.subtitle")}
          </p>
        </div>

        {/* ── Desktop: horizontal spine, weight builds toward the OR ── */}
        <div className="relative mt-unit-16 hidden lg:block">
          <div
            className="spine-line absolute top-6 right-[9%] left-[9%] h-[3px] rounded-full bg-gradient-to-r from-primary/15 via-primary/45 to-primary"
            aria-hidden
          />
          <ol className="relative grid grid-cols-5">
            {stages.map((stage, index) => {
              const Icon = STAGE_ICONS[index]
              const featured = index === FEATURED_INDEX
              return (
                <li
                  key={stage.title}
                  data-reveal
                  style={{ "--rd": `${150 + index * 110}ms` } as React.CSSProperties}
                  className="flex flex-col items-center px-unit-3 text-center"
                >
                  <span
                    className={cn(
                      "z-10 flex h-12 w-12 items-center justify-center rounded-full",
                      featured
                        ? "bg-primary text-on-primary shadow-[0_6px_20px_rgba(65,89,212,0.35)] ring-4 ring-primary/20"
                        : "border border-outline-variant bg-surface-container-lowest text-primary",
                    )}
                  >
                    <Icon className="h-5.5 w-5.5" aria-hidden />
                  </span>
                  <h3 className="mt-unit-4 font-display text-[1.05rem] font-semibold text-on-surface">
                    {stage.title}
                  </h3>
                  <p className="mt-unit-2 max-w-[28ch] text-[13.5px] leading-relaxed text-on-surface-variant">
                    {stage.body}
                  </p>
                  {stage.cta && (
                    <Link
                      href="/contact"
                      className="mt-unit-3 inline-flex min-h-11 items-center gap-1 text-[14px] font-semibold text-primary underline-offset-4 hover:underline"
                    >
                      {stage.cta}
                      <span aria-hidden>→</span>
                    </Link>
                  )}
                </li>
              )
            })}
          </ol>
        </div>

        {/* ── Mobile: vertical rail, same grammar ── */}
        <ol className="relative mt-unit-8 lg:hidden">
          <div
            className="spine-line-v absolute top-2 bottom-2 left-[23px] w-[3px] rounded-full bg-gradient-to-b from-primary/15 via-primary/45 to-primary"
            aria-hidden
          />
          {stages.map((stage, index) => {
            const Icon = STAGE_ICONS[index]
            const featured = index === FEATURED_INDEX
            return (
              <li
                key={stage.title}
                data-reveal
                style={{ "--rd": `${150 + index * 110}ms` } as React.CSSProperties}
                className="relative flex gap-unit-4 pb-unit-6 pl-0 last:pb-0"
              >
                <span
                  className={cn(
                    "z-10 flex h-12 w-12 shrink-0 items-center justify-center rounded-full",
                    featured
                      ? "bg-primary text-on-primary ring-4 ring-primary/20"
                      : "border border-outline-variant bg-surface-container-lowest text-primary",
                  )}
                >
                  <Icon className="h-5.5 w-5.5" aria-hidden />
                </span>
                <div className="pt-1">
                  <h3 className="font-display text-[1rem] font-semibold text-on-surface">
                    {stage.title}
                  </h3>
                  <p className="mt-1 text-[13.5px] leading-relaxed text-on-surface-variant">
                    {stage.body}
                  </p>
                  {stage.cta && (
                    <Link
                      href="/contact"
                      className="mt-unit-2 inline-flex min-h-11 items-center gap-1 text-[14px] font-semibold text-primary underline-offset-4 hover:underline"
                    >
                      {stage.cta}
                      <span aria-hidden>→</span>
                    </Link>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </RevealGroup>
    </section>
  )
}
