import { getTranslations } from "next-intl/server"

import { RevealGroup } from "@/components/reveal-group"

/**
 * Intelligence — show the learning, don't claim it.
 *
 * The old version was two icon-tile cards with abstract copy
 * ("Interoperable Intelligence"). Replaced with two editorial panels,
 * each anchored by a code-built product artifact in the same receipt
 * grammar as the hero note card:
 *
 *  1. Your voice — a phrasing diff: the generic-scribe line struck
 *     through, the surgeon's learned phrasing beneath it, with a
 *     "learned from your edits" provenance tag. (The struck line is
 *     also the vaguer one — precision is the upgrade.)
 *  2. Your patients — a patient-twin ledger: four encounters, each
 *     contributing cited claims, totalled into one narrative.
 */

type TwinRow = { date: string; label: string; claims: string }

export async function IntelligenceSection() {
  const t = await getTranslations("home")
  const rows = t.raw("intelligence.memory.rows") as TwinRow[]

  return (
    <section className="bg-surface py-unit-12 md:py-unit-16">
      <div className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">

        {/* ── Header — editorial, left-aligned ── */}
        <RevealGroup>
        <div className="max-w-2xl" data-reveal>
          <p className="text-[12.5px] font-semibold tracking-[0.14em] text-secondary uppercase">
            {t("intelligence.eyebrow")}
          </p>
          <h2 className="mt-unit-4 font-display text-[1.75rem] leading-tight font-semibold tracking-[-0.01em] text-on-surface sm:text-[2rem] lg:text-headline-lg">
            {t("intelligence.title")}
          </h2>
          <p className="mt-unit-4 text-body-md leading-relaxed text-on-surface-variant lg:text-body-lg">
            {t("intelligence.subtitle")}
          </p>
        </div>

        <div className="mt-unit-12 grid grid-cols-1 gap-gutter lg:grid-cols-2">

          {/* ── Panel 1 — it learns how you write ── */}
          <article data-reveal style={{ "--rd": "120ms" } as React.CSSProperties} className="flex flex-col">
            <p className="font-mono text-[11px] tracking-[0.12em] text-primary uppercase">
              {t("intelligence.voice.kicker")}
            </p>
            <h3 className="mt-unit-2 font-display text-headline-md font-semibold text-on-surface">
              {t("intelligence.voice.title")}
            </h3>
            <p className="mt-unit-3 max-w-lg text-body-md leading-relaxed text-on-surface-variant">
              {t("intelligence.voice.body")}
            </p>

            {/* Artifact: the phrasing diff */}
            <div className="mt-unit-6 rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-unit-6 shadow-sm">
              <p className="font-mono text-[10.5px] tracking-[0.08em] text-outline uppercase">
                {t("intelligence.voice.artifactLabel")}
              </p>
              <p data-reveal style={{ "--rd": "420ms" } as React.CSSProperties} className="mt-unit-3 text-[14px] leading-relaxed text-outline line-through decoration-outline/50">
                {t("intelligence.voice.before")}
              </p>
              <p data-reveal style={{ "--rd": "560ms" } as React.CSSProperties} className="mt-unit-2 text-[14px] leading-relaxed text-on-surface">
                {t("intelligence.voice.after")}
              </p>
              <p data-reveal style={{ "--rd": "700ms" } as React.CSSProperties} className="mt-unit-4 inline-flex items-center gap-1.5 rounded-full bg-primary-fixed px-2.5 py-1 font-mono text-[10px] font-medium text-on-primary-fixed-variant">
                <span className="h-1 w-1 rounded-full bg-primary" aria-hidden />
                {t("intelligence.voice.tag")}
              </p>
            </div>
          </article>

          {/* ── Panel 2 — it remembers the patient ── */}
          <article data-reveal style={{ "--rd": "240ms" } as React.CSSProperties} className="flex flex-col">
            <p className="font-mono text-[11px] tracking-[0.12em] text-primary uppercase">
              {t("intelligence.memory.kicker")}
            </p>
            <h3 className="mt-unit-2 font-display text-headline-md font-semibold text-on-surface">
              {t("intelligence.memory.title")}
            </h3>
            <p className="mt-unit-3 max-w-lg text-body-md leading-relaxed text-on-surface-variant">
              {t("intelligence.memory.body")}
            </p>

            {/* Artifact: the twin ledger */}
            <div className="mt-unit-6 rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-unit-6 shadow-sm">
              <p className="font-mono text-[10.5px] tracking-[0.08em] text-outline uppercase">
                {t("intelligence.memory.artifactLabel")}
              </p>
              <ul className="mt-unit-2 divide-y divide-outline-variant/40">
                {rows.map((row, rowIndex) => (
                  <li
                    key={row.date}
                    data-reveal
                    style={{ "--rd": `${420 + rowIndex * 90}ms` } as React.CSSProperties}
                    className="flex items-baseline gap-unit-3 py-unit-2"
                  >
                    <span className="w-14 shrink-0 font-mono text-[11px] text-outline">
                      {row.date}
                    </span>
                    <span className="flex-1 text-[13.5px] leading-snug text-on-surface">
                      {row.label}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-primary">
                      {row.claims}
                    </span>
                  </li>
                ))}
              </ul>
              <p data-reveal style={{ "--rd": "800ms" } as React.CSSProperties} className="mt-unit-2 border-t border-outline-variant/40 pt-unit-3 font-mono text-[11px] text-on-surface-variant">
                {t("intelligence.memory.footer")}
              </p>
            </div>
          </article>

        </div>
        </RevealGroup>
      </div>
    </section>
  )
}
