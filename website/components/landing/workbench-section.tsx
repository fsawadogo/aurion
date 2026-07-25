import {
  ArrowUp,
  ArrowUpRight,
  BarChart3,
  History,
  LayoutDashboard,
  Ruler,
  Send,
  Settings,
  Users,
} from "lucide-react"
import Image from "next/image"
import { getTranslations } from "next-intl/server"

import { RevealGroup } from "@/components/reveal-group"
import { SITE } from "@/lib/site"

/**
 * Workbench — the portal console, in the receipt grammar.
 *
 * The console mock stays (it is the actual product surface), but the
 * dashboard cosplay is gone: no "AI Engine: Active" chips, no pulsing
 * sparkles, no alarm-red context tags. One real mono chip (the portal
 * domain), the P avatar from the hero, and — the point of the page —
 * Peri's answer carries its source receipts as citation chips.
 */

/** CRP trend, in mg/L — drives the bar heights in the lab card. */
const CRP_SERIES = [12, 38, 74, 52, 31]
const CRP_MAX = 80

const SIDEBAR_ITEMS = [
  { key: "dashboard", icon: LayoutDashboard },
  { key: "patients", icon: Users },
  { key: "analytics", icon: BarChart3 },
  { key: "history", icon: History },
] as const

/** The hero's "P" avatar, reused so Peri looks the same everywhere. */
function PeriAvatar({ size = "md" }: { size?: "sm" | "md" }) {
  const dims = size === "sm" ? "h-5 w-5 text-[9px]" : "h-6 w-6 text-[10px]"
  return (
    <span
      className={`inline-flex ${dims} shrink-0 items-center justify-center rounded-full bg-primary font-display font-bold text-on-primary`}
      aria-hidden
    >
      P
    </span>
  )
}

export async function WorkbenchSection() {
  const t = await getTranslations("home")
  const suggested = t.raw("workbench.chat.suggested") as string[]
  const sources = t.raw("workbench.chat.sources") as string[]

  const crpBars = CRP_SERIES.map((value, index) => (
    <div
      key={index}
      className="grow-bar flex-1 rounded-t-sm bg-primary"
      style={{
        height: `${(value / CRP_MAX) * 100}%`,
        opacity: 0.35 + (value / CRP_MAX) * 0.65,
        "--rd": `${350 + index * 90}ms`,
      } as React.CSSProperties}
    />
  ))

  const sourceChips = (
    <div className="mt-unit-3 flex flex-wrap gap-unit-2">
      {sources.map((source) => (
        <span
          key={source}
          className="rounded-full bg-primary-fixed px-2 py-0.5 font-mono text-[10px] font-medium text-on-primary-fixed-variant"
        >
          {source}
        </span>
      ))}
    </div>
  )

  return (
    <section
      id="workbench"
      className="scroll-mt-24 overflow-clip bg-surface-container-low py-unit-12 md:py-unit-16"
    >
      <RevealGroup className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">

        {/* ── Header — editorial, left-aligned ── */}
        <div data-reveal className="mb-unit-8 flex flex-wrap items-end justify-between gap-unit-6 lg:mb-unit-12">
          <div className="max-w-2xl">
            <p className="text-[12.5px] font-semibold tracking-[0.14em] text-secondary uppercase">
              {t("workbench.eyebrow")}
            </p>
            <h2 className="mt-unit-4 font-display text-[1.75rem] leading-tight font-semibold tracking-[-0.01em] text-on-surface sm:text-[2rem] lg:text-headline-lg">
              {t("workbench.title")}
            </h2>
            <p className="mt-unit-4 text-body-md leading-relaxed text-on-surface-variant lg:text-body-lg">
              {t("workbench.subtitle")}
            </p>
          </div>

          {/* The chip is the actual portal — let it behave like one. */}
          <a
            href={SITE.physicianPortalUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="hidden items-center gap-1.5 rounded-full border border-outline-variant px-unit-4 py-unit-2 font-mono text-[12px] text-on-surface-variant transition-colors hover:border-primary hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary lg:inline-flex"
          >
            {t("workbench.portalChip")}
            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
          </a>
        </div>

        {/* ── Mobile: stacked bento ── */}
        <div data-reveal style={{ "--rd": "140ms" } as React.CSSProperties} className="space-y-unit-4 lg:hidden">

          <div className="relative aspect-square overflow-hidden rounded-2xl bg-black">
            <Image
              src="/radiograph-ldfa.jpg"
              alt={t("workbench.imagingCard.imageAlt")}
              fill
              sizes="100vw"
              className="object-cover opacity-90"
            />
            <span className="absolute top-unit-4 left-unit-4 rounded-md bg-black/60 px-unit-3 py-unit-1 font-mono text-[10px] tracking-wider text-white/80 uppercase">
              {t("workbench.xrayLabel")}
            </span>
            <span
              className="absolute right-unit-4 bottom-unit-4 flex h-10 w-10 items-center justify-center rounded-full bg-primary text-on-primary shadow-lg"
              aria-hidden
            >
              <Ruler className="h-5 w-5" />
            </span>
          </div>

          <div className="rounded-2xl border border-outline-variant/50 bg-surface-container-lowest p-unit-4">
            <p className="font-mono text-[10.5px] tracking-[0.08em] text-outline uppercase">
              {t("workbench.labCard.title")}
            </p>
            <div className="mt-unit-4 flex h-24 items-end gap-1 px-1">{crpBars}</div>
            <p className="mt-unit-2 font-mono text-[11px] text-on-surface-variant">
              {t("workbench.labCard.caption")}
            </p>
          </div>

          <div className="rounded-2xl border border-outline-variant/50 bg-surface-container-lowest p-unit-4">
            <div className="flex items-center gap-unit-2">
              <PeriAvatar />
              <span className="font-display text-[15px] font-semibold text-on-surface">
                {t("workbench.chat.title")}
              </span>
            </div>

            <div className="mt-unit-4 space-y-unit-4">
              <p className="ml-auto max-w-[90%] rounded-2xl rounded-tr-none bg-primary p-unit-3 text-[14px] leading-relaxed text-on-primary">
                {t("workbench.chat.question")}
              </p>
              <div className="max-w-[90%] rounded-2xl rounded-tl-none border border-outline-variant/50 bg-surface-container-low p-unit-3 shadow-sm">
                <p className="text-[14px] leading-relaxed text-on-surface">
                  {t("workbench.chat.answer")}
                </p>
                {sourceChips}
              </div>
            </div>

            <div className="relative mt-unit-4">
              <span className="block w-full rounded-full border border-outline-variant bg-surface-container-lowest py-unit-3 pr-12 pl-unit-4 text-[14px] text-outline">
                {t("workbench.chat.placeholder")}
              </span>
              <span
                className="absolute top-1/2 right-2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full bg-primary text-on-primary"
                aria-hidden
              >
                <ArrowUp className="h-4 w-4" />
              </span>
            </div>
          </div>
        </div>

        {/* ── Desktop: full console ── */}
        <div data-reveal style={{ "--rd": "140ms" } as React.CSSProperties} className="card-shadow hidden overflow-hidden rounded-medical border border-outline-variant/30 bg-surface-container-lowest lg:flex lg:h-[750px]">

          <div
            className="flex w-24 shrink-0 flex-col items-center gap-unit-12 border-r border-outline-variant/20 bg-surface-container-low py-unit-12"
            aria-hidden
          >
            {SIDEBAR_ITEMS.map((item, index) => {
              const Icon = item.icon
              return (
                <div
                  key={item.key}
                  className={
                    index === 0
                      ? "flex h-12 w-12 items-center justify-center rounded-xl bg-primary-fixed text-primary"
                      : "text-outline"
                  }
                >
                  <Icon className="h-6 w-6" />
                </div>
              )
            })}
            <div className="mt-auto text-outline">
              <Settings className="h-6 w-6" />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto bg-surface-bright p-unit-12 dark:bg-surface-container-low">
            <div className="mb-unit-8 flex flex-wrap items-center justify-between gap-unit-4">
              <h3 className="font-display text-headline-md font-semibold text-on-surface">
                {t("workbench.patientView")}
              </h3>
              <span className="rounded-full border border-outline-variant px-unit-4 py-unit-2 font-mono text-[12px] tracking-wide text-on-surface-variant">
                {t("workbench.patientTag")}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-unit-6">
              <article className="rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-unit-6 shadow-sm">
                <p className="font-mono text-[10.5px] tracking-[0.08em] text-outline uppercase">
                  {t("workbench.labCard.title")}
                </p>
                <div className="mt-unit-4 flex h-40 w-full items-end gap-unit-2 rounded-lg bg-primary/5 p-unit-4">
                  {crpBars}
                </div>
                <p className="mt-unit-4 font-mono text-[12px] text-on-surface-variant">
                  {t("workbench.labCard.caption")}
                </p>
              </article>

              <article className="rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-unit-6 shadow-sm">
                <p className="font-mono text-[10.5px] tracking-[0.08em] text-outline uppercase">
                  {t("workbench.imagingCard.title")}
                </p>
                <div className="relative mt-unit-4 h-40 overflow-hidden rounded-lg bg-[#080a12]">
                  <Image
                    src="/radiograph-ldfa.jpg"
                    alt={t("workbench.imagingCard.imageAlt")}
                    fill
                    sizes="30vw"
                    className="object-cover object-top"
                  />
                </div>
                <div className="mt-unit-4 flex flex-wrap items-center justify-between gap-unit-2">
                  <p className="font-mono text-[12px] text-on-surface-variant">
                    {t("workbench.imagingCard.caption")}
                  </p>
                  <span className="rounded-full bg-primary-fixed px-unit-3 py-unit-1 font-mono text-[12px] font-medium text-on-primary-fixed-variant">
                    {t("workbench.imagingCard.measurement")}
                  </span>
                </div>
              </article>
            </div>
          </div>

          <div className="flex w-96 shrink-0 flex-col border-l border-outline-variant/20">
            <div className="flex items-center gap-unit-2 border-b border-outline-variant/20 bg-surface-container p-unit-6">
              <PeriAvatar />
              <span className="font-display text-[1.1rem] font-semibold text-on-surface">
                {t("workbench.chat.title")}
              </span>
            </div>

            <div className="flex-1 space-y-unit-6 overflow-y-auto bg-surface-container-low p-unit-6">
              <div className="rounded-lg border border-outline-variant/30 bg-surface-container-lowest p-unit-4">
                <p className="text-[14.5px] leading-relaxed text-on-surface-variant">
                  {t("workbench.chat.question")}
                </p>
              </div>

              <div className="rounded-lg border border-primary/10 bg-primary/5 p-unit-4">
                <p className="font-mono text-[10.5px] tracking-[0.08em] text-primary uppercase">
                  {t("workbench.chat.answerLabel")}
                </p>
                <p className="mt-unit-2 text-[14.5px] leading-relaxed text-on-surface">
                  {t("workbench.chat.answer")}
                </p>
                {sourceChips}
              </div>

              <div className="space-y-unit-2 pt-unit-4">
                <p className="font-mono text-[10.5px] tracking-[0.08em] text-outline uppercase">
                  {t("workbench.chat.suggestedLabel")}
                </p>
                {suggested.map((query) => (
                  <p
                    key={query}
                    className="rounded-lg border border-outline-variant/30 bg-surface-container-lowest p-unit-4 text-[13.5px] leading-snug text-on-surface-variant"
                  >
                    {query}
                  </p>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-unit-2 border-t border-outline-variant/20 bg-surface-container-lowest p-unit-6">
              <span className="flex-1 rounded-lg bg-surface-container px-unit-4 py-unit-3 text-[14.5px] text-outline">
                {t("workbench.chat.placeholder")}
              </span>
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary text-on-primary" aria-hidden>
                <Send className="h-5 w-5" />
              </span>
            </div>
          </div>
        </div>
      </RevealGroup>
    </section>
  )
}
