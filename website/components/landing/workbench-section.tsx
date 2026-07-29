import {
  ArrowUp,
  BarChart3,
  Bot,
  History,
  LayoutDashboard,
  Maximize2,
  Ruler,
  Send,
  Settings,
  Sparkles,
  Users,
} from "lucide-react"
import Image from "next/image"
import { getTranslations } from "next-intl/server"

/** CRP trend, in mg/L — drives the bar heights in the lab card. */
const CRP_SERIES = [12, 38, 74, 52, 31]
const CRP_MAX = 80

const SIDEBAR_ITEMS = [
  { key: "dashboard", icon: LayoutDashboard },
  { key: "patients", icon: Users },
  { key: "analytics", icon: BarChart3 },
  { key: "history", icon: History },
] as const

export async function WorkbenchSection() {
  const t = await getTranslations("home")
  const suggested = t.raw("workbench.chat.suggested") as string[]

  const crpBars = CRP_SERIES.map((value, index) => (
    <div
      key={index}
      className="flex-1 rounded-t-sm bg-primary"
      style={{
        height: `${(value / CRP_MAX) * 100}%`,
        opacity: 0.35 + (value / CRP_MAX) * 0.65,
      }}
    />
  ))

  return (
    <section
      id="workbench"
      className="scroll-mt-24 overflow-clip bg-surface-container-low py-unit-12 md:py-unit-16"
    >
      <div className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">

        {/* Heading */}
        <div className="mb-unit-6 flex items-center justify-between gap-unit-4 lg:mb-unit-12 lg:items-end">
          <div className="max-w-2xl">
            <h2 className="font-display text-[1.75rem] leading-tight font-semibold tracking-[-0.01em] text-on-surface sm:text-[2rem] lg:mb-unit-6 lg:text-headline-lg">
              {t("workbench.title")}
            </h2>
            <p className="font-mono text-[13px] text-on-surface-variant lg:font-sans lg:text-body-lg">
              <span className="lg:hidden">{t("workbench.patientView")}</span>
              <span className="hidden lg:inline">{t("workbench.subtitle")}</span>
            </p>
          </div>

          <div className="hidden flex-wrap gap-unit-4 lg:flex">
            <span className="rounded-full border border-outline-variant px-unit-6 py-unit-2 font-mono text-[14px] text-on-surface-variant">
              {t("workbench.statusChip")}
            </span>
            <span className="rounded-full bg-primary/10 px-unit-6 py-unit-2 font-mono text-[14px] text-primary">
              {t("workbench.engineChip")}
            </span>
          </div>

          <span
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-primary text-primary lg:hidden"
            aria-hidden
          >
            <Maximize2 className="h-5 w-5" />
          </span>
        </div>

        {/* ── Mobile: stacked bento ── */}
        <div className="space-y-unit-4 lg:hidden">

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

          <div className="rounded-2xl border border-outline-variant bg-surface-container-lowest p-unit-4">
            <p className="mb-unit-4 font-mono text-[13px] font-medium text-on-surface">
              {t("workbench.labCard.title")}
            </p>
            <div className="flex h-24 items-end gap-1 px-1">{crpBars}</div>
            <p className="mt-unit-2 font-mono text-[11px] text-on-surface-variant">
              {t("workbench.labCard.caption")}
            </p>
          </div>

          <div className="rounded-2xl border border-primary/20 bg-surface-container-high p-unit-4">
            <div className="mb-unit-4 flex items-center gap-unit-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-on-primary" aria-hidden>
                <Bot className="h-4 w-4" />
              </span>
              <span className="font-mono text-[13px] font-bold text-primary">
                {t("workbench.chat.title")}
              </span>
            </div>

            <div className="space-y-unit-4">
              <p className="ml-auto max-w-[90%] rounded-2xl rounded-tr-none bg-primary p-unit-3 text-[14px] leading-relaxed text-on-primary">
                {t("workbench.chat.question")}
              </p>
              <p className="max-w-[90%] rounded-2xl rounded-tl-none border border-outline-variant bg-surface-container-lowest p-unit-3 text-[14px] leading-relaxed text-on-surface shadow-sm">
                {t("workbench.chat.answer")}
              </p>
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
        <div className="card-shadow hidden overflow-hidden rounded-medical border border-outline-variant/30 bg-surface-container-lowest lg:flex lg:h-[750px]">

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
                      ? "flex h-12 w-12 items-center justify-center rounded-xl bg-secondary text-on-secondary"
                      : "text-outline"
                  }
                >
                  <Icon className="h-7 w-7" />
                </div>
              )
            })}
            <div className="mt-auto text-outline">
              <Settings className="h-7 w-7" />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto bg-surface-bright p-unit-12">
            <div className="mb-unit-8 flex flex-wrap items-center justify-between gap-unit-4">
              <h3 className="font-display text-headline-md font-semibold text-on-surface">
                {t("workbench.patientView")}
              </h3>
              <span className="rounded-full bg-error/10 px-unit-4 py-unit-2 font-mono text-[13px] tracking-wider text-error uppercase">
                {t("workbench.patientTag")}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-unit-6">
              <article className="rounded-xl border border-outline-variant/20 border-l-4 border-l-primary bg-surface-container-lowest p-unit-6 shadow-sm">
                <div className="mb-unit-6 flex items-center justify-between gap-unit-2">
                  <h4 className="font-mono text-[13px] font-bold tracking-widest uppercase">
                    {t("workbench.labCard.title")}
                  </h4>
                  <BarChart3 className="h-5 w-5 text-primary" aria-hidden />
                </div>
                <div className="flex h-40 w-full items-end gap-unit-2 rounded-lg bg-primary/5 p-unit-4">
                  {crpBars}
                </div>
                <p className="mt-unit-4 font-mono text-[13px] text-on-surface-variant">
                  {t("workbench.labCard.caption")}
                </p>
              </article>

              <article className="rounded-xl border border-outline-variant/20 border-l-4 border-l-secondary bg-surface-container-lowest p-unit-6 shadow-sm">
                <div className="mb-unit-6 flex items-center justify-between gap-unit-2">
                  <h4 className="font-mono text-[13px] font-bold tracking-widest uppercase">
                    {t("workbench.imagingCard.title")}
                  </h4>
                  <Ruler className="h-5 w-5 text-secondary" aria-hidden />
                </div>
                <div className="relative h-40 overflow-hidden rounded-lg bg-[#080a12]">
                  <Image
                    src="/radiograph-ldfa.jpg"
                    alt={t("workbench.imagingCard.imageAlt")}
                    fill
                    sizes="30vw"
                    className="object-cover object-top"
                  />
                </div>
                <div className="mt-unit-4 flex flex-wrap items-center justify-between gap-unit-2">
                  <p className="font-mono text-[13px] text-on-surface-variant">
                    {t("workbench.imagingCard.caption")}
                  </p>
                  <span className="rounded-full bg-secondary/10 px-unit-3 py-unit-1 font-mono text-[13px] font-bold text-secondary">
                    {t("workbench.imagingCard.measurement")}
                  </span>
                </div>
              </article>
            </div>
          </div>

          <div className="flex w-96 shrink-0 flex-col border-l border-outline-variant/20">
            <div className="flex items-center justify-between gap-unit-4 border-b border-outline-variant/20 bg-surface-container p-unit-6">
              <span className="flex items-center gap-unit-2 font-display text-[1.25rem] font-bold text-secondary">
                <Sparkles className="ai-pulse h-6 w-6" aria-hidden />
                {t("workbench.chat.title")}
              </span>
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" aria-hidden />
            </div>

            <div className="flex-1 space-y-unit-6 overflow-y-auto bg-surface-container-low p-unit-6">
              <div className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest p-unit-4">
                <p className="text-[15px] leading-relaxed text-on-surface-variant italic">
                  {t("workbench.chat.question")}
                </p>
              </div>

              <div className="rounded-lg border border-primary/10 bg-primary/5 p-unit-4">
                <p className="mb-unit-2 font-mono text-[13px] font-bold text-primary">
                  {t("workbench.chat.answerLabel")}
                </p>
                <p className="text-[15px] leading-relaxed text-on-surface">
                  {t("workbench.chat.answer")}
                </p>
              </div>

              <div className="space-y-unit-2 pt-unit-4">
                <p className="font-mono text-[13px] font-bold tracking-widest text-outline uppercase">
                  {t("workbench.chat.suggestedLabel")}
                </p>
                {suggested.map((query) => (
                  <p
                    key={query}
                    className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest p-unit-4 text-[14px] leading-snug text-on-surface-variant italic"
                  >
                    {query}
                  </p>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-unit-2 border-t border-outline-variant/20 bg-surface-container-lowest p-unit-6">
              <span className="flex-1 rounded-lg bg-surface-container px-unit-4 py-unit-3 text-[15px] text-outline">
                {t("workbench.chat.placeholder")}
              </span>
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary text-on-secondary" aria-hidden>
                <Send className="h-5 w-5" />
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
