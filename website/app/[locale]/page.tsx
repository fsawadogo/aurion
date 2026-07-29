import { setRequestLocale } from "next-intl/server"

import { AnimateIn } from "@/components/animate-in"
import { ColleagueSection } from "@/components/landing/colleague-section"
import { ContinuumSection } from "@/components/landing/continuum-section"
import { HeroSection } from "@/components/landing/hero-section"
import { IntelligenceSection } from "@/components/landing/intelligence-section"
import { LandingFooter } from "@/components/landing/landing-footer"
import { PhilosophySection } from "@/components/landing/philosophy-section"
import { WearableSection } from "@/components/landing/wearable-section"
import { WorkbenchSection } from "@/components/landing/workbench-section"

type Props = { params: Promise<{ locale: string }> }

export default async function Home({ params }: Props) {
  const { locale } = await params
  // Bind the locale so getTranslations() in child sections renders
  // statically (no headers() fallback) — required for output: "export".
  setRequestLocale(locale)

  return (
    <>
      {/*
        `overflow-x-clip`, not `overflow-x-hidden`: setting one axis to `hidden`
        forces the other from `visible` to `auto`, which turned <main> into a
        nested scroll container and made touch scrolling fight the page scroller.
        `clip` contains the same overflow without creating a scrollport.
      */}
      <main className="overflow-x-clip pt-24 md:pt-32">

        {/* Personalized Clinical Intelligence. Ask Peri. */}
        <HeroSection />

        {/* ER → clinic → pre-op → OR → post-op */}
        <AnimateIn direction="up" threshold={0.06} duration={900}>
          <ContinuumSection />
        </AnimateIn>

        {/* How the twin sees and hears */}
        <AnimateIn direction="up" threshold={0.06} duration={850}>
          <WearableSection />
        </AnimateIn>

        {/* What it learns */}
        <AnimateIn direction="up" threshold={0.08}>
          <IntelligenceSection />
        </AnimateIn>

        {/* Where you work with it */}
        <WorkbenchSection />

        {/* What it is to you */}
        <AnimateIn direction="up" threshold={0.08}>
          <ColleagueSection />
        </AnimateIn>

        {/* Why it exists */}
        <AnimateIn direction="up" threshold={0.08}>
          <PhilosophySection />
        </AnimateIn>
      </main>

      <LandingFooter />
    </>
  )
}
