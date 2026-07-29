import { getTranslations } from "next-intl/server"

import { Button } from "@/components/ui/button"
import { Link } from "@/i18n/navigation"

export async function PhilosophySection() {
  const t = await getTranslations("home")

  return (
    // Hidden on mobile: the footer's outlined CTA carries this message there,
    // matching the mobile design and avoiding a duplicate call to action.
    <section className="hidden bg-surface px-margin-mobile py-unit-12 md:px-margin-desktop md:py-unit-16 lg:block">
      <div className="mx-auto max-w-5xl space-y-unit-8 rounded-[2rem] border border-primary/10 bg-linear-to-b from-primary/5 to-transparent p-unit-8 text-center md:p-unit-16">
        <h2 className="font-display text-[1.75rem] leading-tight sm:text-[2rem] font-semibold tracking-[-0.01em] text-on-surface lg:text-headline-lg">
          {t("philosophy.title")}
        </h2>

        <p className="mx-auto max-w-3xl text-body-md text-on-surface-variant lg:text-body-lg">
          {t("philosophy.body")}
        </p>

        <Button
          asChild
          className="h-auto rounded-xl bg-secondary px-unit-12 py-unit-6 font-display text-[1.125rem] font-bold text-on-secondary shadow-xl transition-transform hover:scale-105 hover:bg-secondary active:scale-95"
        >
          <Link href="/contact">{t("philosophy.cta")}</Link>
        </Button>
      </div>
    </section>
  )
}
