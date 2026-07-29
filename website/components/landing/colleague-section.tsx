import { Gavel, RefreshCw, type LucideIcon } from "lucide-react"
import { getTranslations } from "next-intl/server"

type Card = { title: string; body: string }

const CARD_ICONS: LucideIcon[] = [RefreshCw, Gavel]

export async function ColleagueSection() {
  const t = await getTranslations("home")
  const cards = t.raw("colleague.cards") as Card[]

  return (
    <section
      id="colleague"
      className="scroll-mt-24 bg-surface-container-low py-unit-12 md:py-unit-16"
    >
      <div className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">
        <div className="grid items-center gap-unit-12 lg:grid-cols-2 lg:gap-unit-16">

          <div className="space-y-unit-6">
            <h2 className="font-display text-[1.75rem] leading-tight sm:text-[2rem] font-semibold tracking-[-0.01em] text-on-surface lg:text-headline-lg">
              {t("colleague.title")}
            </h2>
            <p className="text-body-md text-on-surface-variant lg:text-body-lg">
              {t("colleague.body")}
            </p>
          </div>

          <div className="grid grid-cols-1 gap-unit-6">
            {cards.map((card, index) => {
              const Icon = CARD_ICONS[index]

              return (
                <article
                  key={card.title}
                  className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest p-unit-8 shadow-sm"
                >
                  <div className="mb-unit-4 flex items-center gap-unit-4">
                    <Icon className="h-7 w-7 shrink-0 text-primary" aria-hidden />
                    <h3 className="font-display text-[1.25rem] font-bold text-on-surface lg:text-headline-md">
                      {card.title}
                    </h3>
                  </div>
                  <p className="text-body-md text-on-surface-variant">{card.body}</p>
                </article>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}
