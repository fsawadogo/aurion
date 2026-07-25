import { getTranslations } from "next-intl/server"

import { RevealGroup } from "@/components/reveal-group"
import { Button } from "@/components/ui/button"
import { Link } from "@/i18n/navigation"

/**
 * Philosophy — the page's one dark moment.
 *
 * A deep-indigo closing band (the logo's indigo), opened by the same
 * gradient rule the patient-journey spine uses, so the page ends on
 * the motif it traveled on. Left-aligned statement, one solid CTA,
 * and a specific pilot line instead of a vague community claim.
 * Visible on every breakpoint — the footer no longer duplicates it
 * on mobile.
 */
export async function PhilosophySection() {
  const t = await getTranslations("home")

  return (
    <section className="relative bg-[#0F1334] py-unit-12 md:py-unit-16">
      {/* The journey spine, closing the loop. */}
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-primary/15 via-primary/45 to-primary"
      />

      <RevealGroup className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">
        <p data-reveal className="text-[12.5px] font-semibold tracking-[0.14em] text-[#A695D6] uppercase">
          {t("philosophy.eyebrow")}
        </p>

        <h2 data-reveal style={{ "--rd": "110ms" } as React.CSSProperties} className="mt-unit-6 max-w-3xl font-display text-[2rem] leading-[1.1] font-bold tracking-[-0.02em] text-white sm:text-[2.6rem]">
          {t("philosophy.title")}
        </h2>

        <p data-reveal style={{ "--rd": "220ms" } as React.CSSProperties} className="mt-unit-6 max-w-2xl text-body-md leading-relaxed text-white/70 lg:text-body-lg">
          {t("philosophy.body")}
        </p>

        <div data-reveal style={{ "--rd": "330ms" } as React.CSSProperties} className="mt-unit-8 flex flex-col items-start gap-unit-6 sm:flex-row sm:items-center">
          <Button
            asChild
            className="h-auto rounded-xl bg-primary px-unit-8 py-unit-4 text-[15.5px] font-semibold text-on-primary shadow-sm transition-all hover:bg-primary-container active:scale-[0.98]"
          >
            <Link href="/contact">{t("philosophy.cta")}</Link>
          </Button>
          <p className="font-mono text-[11.5px] tracking-wide text-white/50">
            {t("philosophy.pilotLine")}
          </p>
        </div>
      </RevealGroup>
    </section>
  )
}
