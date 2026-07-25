import { getTranslations } from "next-intl/server"

import { RevealGroup } from "@/components/reveal-group"

/**
 * Colleague — trust facts as typography, not icon cards.
 *
 * The two claims here (EHR integration, medico-legal traceability) are
 * reassurances, so they read as a quiet definition list: mono kicker,
 * title, body, hairline separators. No boxes, no decorative icons.
 */

type Item = { kicker: string; title: string; body: string }

export async function ColleagueSection() {
  const t = await getTranslations("home")
  const items = t.raw("colleague.items") as Item[]

  return (
    <section
      id="colleague"
      className="scroll-mt-24 bg-surface-container-low py-unit-12 md:py-unit-16"
    >
      <div className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">
        <RevealGroup className="grid items-start gap-unit-12 lg:grid-cols-2 lg:gap-unit-16">

          <div data-reveal>
            <p className="text-[12.5px] font-semibold tracking-[0.14em] text-secondary uppercase">
              {t("colleague.eyebrow")}
            </p>
            <h2 className="mt-unit-4 font-display text-[1.75rem] leading-tight font-semibold tracking-[-0.01em] text-on-surface sm:text-[2rem] lg:text-headline-lg">
              {t("colleague.title")}
            </h2>
            <p className="mt-unit-4 max-w-xl text-body-md leading-relaxed text-on-surface-variant lg:text-body-lg">
              {t("colleague.body")}
            </p>
          </div>

          <div className="divide-y divide-outline-variant/40">
            {items.map((item, itemIndex) => (
              <div key={item.title} data-reveal style={{ "--rd": `${150 + itemIndex * 130}ms` } as React.CSSProperties} className="py-unit-6 first:pt-0 last:pb-0">
                <p className="font-mono text-[11px] tracking-[0.12em] text-primary uppercase">
                  {item.kicker}
                </p>
                <h3 className="mt-unit-2 font-display text-headline-md font-semibold text-on-surface">
                  {item.title}
                </h3>
                <p className="mt-unit-2 text-body-md leading-relaxed text-on-surface-variant">
                  {item.body}
                </p>
              </div>
            ))}
          </div>

        </RevealGroup>
      </div>
    </section>
  )
}
