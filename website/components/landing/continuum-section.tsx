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
import { cn } from "@/lib/utils"

type Stage = { title: string; body: string; cta?: string }

/**
 * Visual treatment per stage. Order matches `home.continuum.stages`.
 * `featured` is the OR/Procedure card — the moment PeriTwin is most active,
 * so it carries the filled primary surface and the only CTA in the row.
 */
const STAGE_STYLES: Array<{
  icon: LucideIcon
  iconClass: string
  dotClass: string
  featured?: boolean
}> = [
  { icon: Siren, iconClass: "bg-error/10 text-error", dotClass: "bg-primary ring-4 ring-primary/20" },
  { icon: Stethoscope, iconClass: "bg-primary/10 text-primary", dotClass: "bg-primary/40" },
  { icon: CalendarCheck, iconClass: "bg-secondary/10 text-secondary", dotClass: "bg-primary/60" },
  { icon: Syringe, iconClass: "bg-on-primary/20 text-on-primary", dotClass: "bg-primary ring-4 ring-primary/20", featured: true },
  { icon: TrendingUp, iconClass: "bg-tertiary/10 text-tertiary", dotClass: "bg-primary" },
]

export async function ContinuumSection() {
  const t = await getTranslations("home")
  const stages = t.raw("continuum.stages") as Stage[]

  return (
    <section
      id="continuum"
      className="scroll-mt-24 bg-surface-container-low py-unit-12 md:py-unit-16"
    >
      <div className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">
        <div className="mb-unit-8 lg:mb-unit-16 lg:text-center">
          <h2 className="mb-unit-2 font-display text-[1.75rem] leading-tight font-semibold tracking-[-0.01em] text-on-surface sm:text-[2rem] lg:mb-unit-6 lg:text-headline-lg">
            {t("continuum.title")}
          </h2>
          <p className="text-body-md text-on-surface-variant lg:mx-auto lg:max-w-3xl lg:text-body-lg">
            {t("continuum.subtitle")}
          </p>
        </div>

        <div className="relative lg:mx-auto lg:max-w-none">
          {/* Horizontal connector on desktop */}
          <div
            className="journey-line absolute top-1/2 left-0 hidden h-1 w-full -translate-y-1/2 opacity-20 lg:block"
            aria-hidden
          />

          {/* Dashed vertical rail behind the mobile timeline */}
          <div
            className="absolute top-6 bottom-6 left-[23px] w-0.5 opacity-30 lg:hidden"
            style={{
              background:
                "repeating-linear-gradient(to bottom, var(--primary) 0, var(--primary) 4px, transparent 4px, transparent 8px)",
            }}
            aria-hidden
          />

          <ul className="relative z-10 flex flex-col gap-unit-4 lg:grid lg:grid-cols-5 lg:gap-unit-6">
            {stages.map((stage, index) => {
              const style = STAGE_STYLES[index]
              const Icon = style.icon

              return (
                <li key={stage.title} className="group flex items-center gap-unit-6 lg:block">
                  {/* Timeline node — becomes the card's icon tile from lg */}
                  <div
                    className={cn(
                      "z-10 flex h-12 w-12 shrink-0 items-center justify-center rounded-full lg:hidden",
                      style.featured
                        ? "bg-primary text-on-primary ring-2 ring-primary ring-offset-2 ring-offset-surface-container-low"
                        : "bg-surface-container-highest text-on-surface-variant",
                    )}
                  >
                    <Icon className="h-6 w-6" aria-hidden />
                  </div>

                  <div
                    className={cn(
                      "flex-1 rounded-xl border p-unit-4 lg:flex lg:h-full lg:flex-col lg:items-center lg:justify-center lg:rounded-2xl lg:p-unit-8 lg:text-center lg:shadow-[0_20px_50px_rgba(0,35,149,0.08)] lg:transition-transform lg:hover:-translate-y-2",
                      style.featured
                        ? "border-2 border-primary bg-surface shadow-md lg:border lg:bg-primary lg:text-on-primary lg:shadow-none"
                        : "border-outline-variant bg-surface lg:border-outline-variant/30 lg:bg-surface-container-lowest",
                    )}
                  >
                    {/* Icon tile — desktop only; mobile uses the timeline node */}
                    <div
                      className={cn(
                        "mb-unit-6 hidden h-16 w-16 items-center justify-center rounded-full transition-transform group-hover:scale-110 lg:flex",
                        style.iconClass,
                      )}
                    >
                      <Icon className="h-8 w-8" aria-hidden />
                    </div>

                    <h3
                      className={cn(
                        "font-display text-[1rem] leading-snug font-semibold lg:text-[1.25rem]",
                        style.featured && "text-primary lg:text-on-primary",
                      )}
                    >
                      {stage.title}
                    </h3>

                    {/*
                      Mobile shows body copy only on the active stage, per the
                      design — five paragraphs would bury the timeline.
                    */}
                    <p
                      className={cn(
                        "text-[12px] leading-relaxed lg:mt-unit-2 lg:block lg:text-[15px]",
                        style.featured ? "mt-unit-1 block" : "hidden",
                        style.featured
                          ? "text-on-surface-variant lg:text-on-primary/80"
                          : "text-on-surface-variant",
                      )}
                    >
                      {stage.body}
                    </p>

                    {stage.cta && (
                      <Link
                        href="/contact"
                        className="mt-unit-4 inline-flex min-h-11 items-center rounded-lg bg-primary px-unit-6 font-mono text-[13px] font-medium text-on-primary transition-colors lg:mt-unit-6 lg:min-h-0 lg:bg-surface-container-lowest lg:py-unit-2 lg:text-[14px] lg:text-primary lg:hover:bg-surface-container-lowest/90"
                      >
                        {stage.cta}
                      </Link>
                    )}
                  </div>

                  {/* Progress node on the desktop connector */}
                  <div className="mt-unit-6 hidden justify-center lg:flex" aria-hidden>
                    <span className={cn("block h-4 w-4 rounded-full", style.dotClass)} />
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </section>
  )
}
