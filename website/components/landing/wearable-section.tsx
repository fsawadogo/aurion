import { getTranslations } from "next-intl/server"

import { RevealGroup } from "@/components/reveal-group"

/**
 * Wearable — the capture story as a privacy receipt.
 *
 * The old version staged a fake "LIVE MULTIMODAL STREAM" console with
 * generated OR footage and invented surgeon names — and misrepresented
 * the product (capture is processed after the encounter, not streamed).
 * Replaced with the truthful artifact: a capture manifest that says
 * what leaves the room and on what terms. It's the trust argument no
 * generic scribe can make, in the same ledger grammar as the rest of
 * the page.
 */

type ManifestRow = { item: string; chip: string }

export async function WearableSection() {
  const t = await getTranslations("home")
  const rows = t.raw("wearable.rows") as ManifestRow[]

  return (
    <section id="platform" className="scroll-mt-24 bg-surface py-unit-12 md:py-unit-16">
      <div className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">
        <RevealGroup className="grid items-center gap-unit-12 lg:grid-cols-2 lg:gap-unit-16">

          {/* ── Copy ── */}
          <div data-reveal>
            <p className="text-[12.5px] font-semibold tracking-[0.14em] text-secondary uppercase">
              {t("wearable.eyebrow")}
            </p>
            <h2 className="mt-unit-4 font-display text-[1.75rem] leading-tight font-semibold tracking-[-0.01em] text-on-surface sm:text-[2rem] lg:text-headline-lg">
              {t("wearable.title")}
            </h2>
            <p className="mt-unit-4 max-w-xl text-body-md leading-relaxed text-on-surface-variant lg:text-body-lg">
              {t("wearable.body")}
            </p>
          </div>

          {/* ── Artifact: the capture manifest ── */}
          <div data-reveal style={{ "--rd": "150ms" } as React.CSSProperties} className="rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-unit-6 shadow-sm">
            <p className="font-mono text-[10.5px] tracking-[0.08em] text-outline uppercase">
              {t("wearable.ledgerLabel")}
            </p>
            <ul className="mt-unit-2 divide-y divide-outline-variant/40">
              {rows.map((row, rowIndex) => (
                <li
                  key={row.item}
                  data-reveal
                  style={{ "--rd": `${280 + rowIndex * 90}ms` } as React.CSSProperties}
                  className="flex flex-wrap items-baseline justify-between gap-x-unit-4 gap-y-unit-1 py-unit-3"
                >
                  <span className="text-[14px] leading-snug font-medium text-on-surface">
                    {row.item}
                  </span>
                  <span className="rounded-full bg-primary-fixed px-2.5 py-0.5 font-mono text-[10.5px] font-medium text-on-primary-fixed-variant">
                    {row.chip}
                  </span>
                </li>
              ))}
            </ul>
            <p data-reveal style={{ "--rd": "660ms" } as React.CSSProperties} className="mt-unit-2 border-t border-outline-variant/40 pt-unit-3 font-mono text-[11px] leading-relaxed text-on-surface-variant">
              {t("wearable.footer")}
            </p>
          </div>

        </RevealGroup>
      </div>
    </section>
  )
}
