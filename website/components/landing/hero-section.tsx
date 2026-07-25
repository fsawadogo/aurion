import Image from "next/image"
import { getTranslations } from "next-intl/server"

import { SourceChip } from "@/components/landing/source-chip"
import { WatchVideoButton } from "@/components/landing/watch-video-button"
import { Button } from "@/components/ui/button"
import { Link } from "@/i18n/navigation"

/**
 * Hero — typography-led thesis + the real product as the only visual.
 *
 * No stock or generated imagery: the right column is a code-built frame
 * of a grounded PeriTwin note with live citation chips (the SourceChip
 * signature), because "every sentence traceable to its source" is the
 * product's actual differentiator. Quiet eyebrow, one solid CTA, and a
 * pilot-stat strip instead of an unsubstantiated trust line.
 */
export async function HeroSection() {
  const t = await getTranslations("home")

  return (
    <section className="relative mx-auto flex max-w-(--breakpoint-2xl) items-center px-margin-mobile py-unit-12 md:px-margin-desktop md:py-unit-16 lg:min-h-[85vh]">
      <div className="relative z-10 grid w-full items-center gap-unit-12 lg:grid-cols-[1.05fr_0.95fr] lg:gap-unit-16">

        {/* ── Copy ── */}
        <div className="flex flex-col items-center text-center lg:items-start lg:text-left">
          <p className="anim-rise text-[12.5px] font-semibold tracking-[0.14em] text-secondary uppercase">
            {t("hero.badge")}
          </p>

          <h1 style={{ "--anim-delay": "90ms" } as React.CSSProperties} className="anim-rise mt-unit-6 font-display text-[2.35rem] leading-[1.06] font-bold tracking-[-0.025em] text-balance text-on-surface sm:text-[3rem] lg:text-[3.6rem]">
            {t("hero.titleLead")}{" "}
            <span className="text-primary">{t("hero.titleAccent")}</span>
          </h1>

          <p style={{ "--anim-delay": "180ms" } as React.CSSProperties} className="anim-rise mt-unit-6 max-w-xl text-body-md leading-relaxed text-on-surface-variant lg:text-body-lg">
            {t("hero.subtitle")}
            <SourceChip id="S1" source={t("hero.subtitleSource")} />
          </p>

          <div style={{ "--anim-delay": "270ms" } as React.CSSProperties} className="anim-rise mt-unit-8 flex flex-col items-center gap-unit-4 sm:flex-row">
            <Button
              asChild
              className="h-auto rounded-xl bg-primary px-unit-8 py-unit-4 text-[15.5px] font-semibold text-on-primary shadow-sm transition-all hover:bg-primary-container active:scale-[0.98]"
            >
              <Link href="/contact">{t("hero.scheduleDemo")}</Link>
            </Button>
            <WatchVideoButton />
          </div>

          {/* Pilot facts — specific beats claimed. */}
          <dl style={{ "--anim-delay": "360ms" } as React.CSSProperties} className="anim-rise mt-unit-8 grid w-full max-w-md grid-cols-3 gap-unit-4 border-t border-outline-variant/40 pt-unit-6 lg:max-w-lg">
            {([1, 2, 3] as const).map((i) => (
              <div key={i} className="text-center lg:text-left">
                <dt className="sr-only">{t(`hero.stat${i}Label`)}</dt>
                <dd className="font-display text-[1.6rem] font-bold tracking-tight text-on-surface">
                  {t(`hero.stat${i}`)}
                </dd>
                <dd className="mt-0.5 text-[12.5px] leading-snug text-on-surface-variant">
                  {t(`hero.stat${i}Label`)}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        {/* ── The clinician, the glasses, and the receipt ──
            Real capture story: the photo carries the wearable; the
            grounded-note card overlaps it so the note visibly "comes
            from" the room — with its citations attached. ── */}
        <div className="relative w-full pb-unit-12 lg:pb-unit-8">
          <div style={{ "--anim-delay": "150ms" } as React.CSSProperties} className="anim-card card-shadow relative overflow-hidden rounded-medical border border-outline-variant/40">
            <Image
              src="/clinician-glasses.jpg"
              alt={t("hero.photoAlt")}
              width={1023}
              height={935}
              priority
              sizes="(min-width: 1024px) 45vw, 100vw"
              className="aspect-[13/12] w-full object-cover"
            />
            {/* Brand wash so the photo sits in the periwinkle family */}
            <div
              className="absolute inset-0 bg-gradient-to-t from-primary/25 via-transparent to-transparent mix-blend-multiply"
              aria-hidden
            />
            {/* Capture state — the privacy story in five words */}
            <span className="absolute top-unit-4 right-unit-4 inline-flex items-center gap-1.5 rounded-full bg-surface/90 px-unit-3 py-1.5 font-mono text-[10.5px] font-medium tracking-wide text-on-surface backdrop-blur">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-error" aria-hidden />
              {t("hero.recChip")}
            </span>
          </div>

          {/* The note the room just produced — overlapping the photo */}
          <div style={{ "--anim-delay": "480ms" } as React.CSSProperties} className="anim-rise relative -mt-unit-8 mx-unit-3 rounded-xl border border-outline-variant/50 bg-surface-container-lowest/95 p-unit-4 shadow-lg backdrop-blur lg:absolute lg:-bottom-unit-2 lg:mx-0 lg:-mt-0 lg:-left-unit-8 lg:right-unit-12">
            <div className="flex items-center justify-between">
              <p className="font-mono text-[10.5px] tracking-[0.08em] text-outline uppercase">
                {t("hero.note.patientLabel")}
              </p>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-fixed px-2 py-0.5 font-mono text-[10px] font-medium text-on-primary-fixed-variant">
                <span className="h-1 w-1 rounded-full bg-primary" aria-hidden />
                {t("hero.note.chipLabel")}
              </span>
            </div>
            <p className="mt-unit-2 text-[14px] leading-relaxed text-on-surface">
              {t("hero.note.line1")}
              <SourceChip id="00:14" source={t("hero.note.line1Source")} align="end" />
            </p>
            <div className="mt-unit-3 flex items-start gap-unit-2 border-t border-outline-variant/40 pt-unit-3">
              <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary font-display text-[10px] font-bold text-on-primary">
                P
              </span>
              <p className="text-[13px] leading-relaxed text-on-surface">
                {t("hero.note.askA")}
                <SourceChip id="S2" source={t("hero.note.askASource")} align="end" />
              </p>
            </div>
          </div>
        </div>

      </div>
    </section>
  )
}
