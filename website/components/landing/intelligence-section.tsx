import { NotebookPen, RefreshCw, type LucideIcon } from "lucide-react"
import { getTranslations } from "next-intl/server"

type Card = { title: string; body: string; shortBody: string }

/**
 * Left-border accent categorizes the data type, per the card spec:
 * AI Violet for twin/memory features, Tertiary for interoperability.
 */
const CARD_STYLES: Array<{ icon: LucideIcon; accent: string; tint: string }> = [
  { icon: NotebookPen, accent: "border-l-secondary", tint: "bg-secondary/10 text-secondary" },
  { icon: RefreshCw, accent: "border-l-tertiary", tint: "bg-tertiary/10 text-tertiary" },
]

export async function IntelligenceSection() {
  const t = await getTranslations("home")
  const cards = t.raw("intelligence.cards") as Card[]

  return (
    <section className="bg-surface py-unit-12 md:py-unit-16">
      <div className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">
        <h2 className="mb-unit-12 text-center font-display text-[1.75rem] leading-tight sm:text-[2rem] font-semibold tracking-[-0.01em] text-on-surface lg:text-headline-lg">
          {t("intelligence.title")}
        </h2>

        <div className="grid grid-cols-1 gap-gutter md:grid-cols-2">
          {cards.map((card, index) => {
            const style = CARD_STYLES[index]
            const Icon = style.icon

            return (
              <article
                key={card.title}
                className={`card-shadow space-y-unit-6 rounded-medical border border-outline-variant/20 border-l-6 bg-surface-container-lowest p-unit-8 md:p-unit-12 ${style.accent}`}
              >
                <div className={`flex h-16 w-16 items-center justify-center rounded-xl ${style.tint}`}>
                  <Icon className="h-8 w-8" aria-hidden />
                </div>
                <h3 className="font-display text-headline-md font-semibold text-on-surface">
                  {card.title}
                </h3>
                {/* Mobile takes the condensed line; desktop keeps the full case. */}
                <p className="text-body-md text-on-surface-variant lg:hidden">
                  {card.shortBody}
                </p>
                <p className="hidden text-body-md text-on-surface-variant lg:block lg:text-body-lg">
                  {card.body}
                </p>
              </article>
            )
          })}
        </div>
      </div>
    </section>
  )
}
