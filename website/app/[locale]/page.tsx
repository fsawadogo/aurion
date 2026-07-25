import { setRequestLocale } from "next-intl/server"

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

        Motion restraint (2026-07-24 redesign): sections render immediately —
        the previous whole-section AnimateIn reveals left entire viewports
        blank mid-scroll and read as template motion. The page keeps exactly
        one orchestrated moment (the hero) and hover micro-interactions
        (SourceChip receipts).
      */}
      <main className="overflow-x-clip pt-20 md:pt-24">

        {/* Personalized Clinical Intelligence. Ask Peri. */}
        <HeroSection />

        {/* ER → clinic → pre-op → OR → post-op */}
        <ContinuumSection />

        {/* How the twin listens and observes */}
        <WearableSection />

        {/* What it learns */}
        <IntelligenceSection />

        {/* Where you work with it */}
        <WorkbenchSection />

        {/* What it is to you */}
        <ColleagueSection />

        {/* Why it exists */}
        <PhilosophySection />
      </main>

      <LandingFooter />
    </>
  )
}
