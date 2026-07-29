import Image from "next/image"
import { getTranslations } from "next-intl/server"

export async function WearableSection() {
  const t = await getTranslations("home")

  const streams = [
    { src: "/wearable-or-surgeon.jpg", alt: t("wearable.imageAltPrimary"), name: t("wearable.streamPrimaryRole") },
    { src: "/wearable-clinic-surgeon.jpg", alt: t("wearable.imageAltSecondary"), name: t("wearable.streamSecondaryRole") },
  ]

  return (
    <section id="platform" className="scroll-mt-24 bg-surface py-unit-12 md:py-unit-16">
      <div className="mx-auto max-w-(--breakpoint-2xl) px-margin-mobile md:px-margin-desktop">

        {/* Mobile headline — the desktop copy lives inside the card below */}
        <h2 className="mb-unit-6 font-display text-[1.75rem] leading-tight font-semibold tracking-[-0.01em] text-on-surface sm:text-[2rem] lg:hidden">
          {t("wearable.mobileTitle")}
        </h2>

        {/* Dark stream console — full-bleed card on mobile, right column on desktop */}
        <div className="lg:flex lg:flex-row lg:items-center lg:gap-unit-16 lg:rounded-[2rem] lg:border lg:border-outline-variant/20 lg:bg-surface-container-lowest lg:p-unit-16 lg:shadow-[0_20px_50px_rgba(0,35,149,0.08)]">

          <div className="hidden flex-1 space-y-unit-6 lg:block">
            <h2 className="font-display text-[2.25rem] leading-tight font-bold tracking-[-0.02em] text-on-surface lg:text-display-lg">
              {t("wearable.title")}
            </h2>
            <p className="text-[1.25rem] leading-relaxed text-on-surface-variant lg:text-headline-md lg:leading-relaxed">
              {t("wearable.bodyLead")}{" "}
              <span className="font-bold text-secondary">{t("wearable.bodyAccent")}</span>{" "}
              {t("wearable.bodyRest")}
            </p>
          </div>

          <div className="w-full flex-1 overflow-hidden rounded-3xl bg-inverse-surface text-inverse-on-surface shadow-2xl lg:rounded-medical lg:border lg:border-outline-variant/20 lg:bg-surface-container-low lg:text-on-surface lg:shadow-none">

            {/* Console header */}
            <div className="flex items-center justify-between gap-unit-4 border-b border-white/10 bg-black/20 p-unit-4 lg:border-none lg:bg-transparent lg:px-unit-12 lg:pt-unit-12">
              <div className="flex items-center gap-unit-2">
                <span className="ai-pulse block h-2.5 w-2.5 rounded-full bg-emerald-500" aria-hidden />
                <span className="font-mono text-[13px] tracking-wider uppercase lg:font-bold lg:text-outline">
                  {t("wearable.streamLabel")}
                </span>
              </div>
              <span className="font-mono text-[13px] text-white/60 lg:text-emerald-600">
                <span className="lg:hidden">{t("wearable.streamTimecode")}</span>
                <span className="hidden lg:inline">{t("wearable.streamStatus")}</span>
              </span>
            </div>

            {/* Feeds — stacked 16:9 on mobile, side-by-side 4:3 on desktop */}
            <div className="grid grid-cols-1 gap-px lg:grid-cols-2 lg:gap-unit-4 lg:px-unit-12 lg:pt-unit-6">
              {streams.map((stream) => (
                <div
                  key={stream.src}
                  className="relative aspect-video overflow-hidden lg:aspect-4/3 lg:rounded-xl lg:border lg:border-outline-variant/20"
                >
                  <Image
                    src={stream.src}
                    alt={stream.alt}
                    fill
                    sizes="(max-width: 1024px) 100vw, 22vw"
                    className="object-cover"
                  />
                  <div className="absolute bottom-unit-4 left-unit-4 flex items-center gap-unit-2 rounded-full bg-black/40 px-unit-3 py-unit-1 font-mono text-[11px] text-white backdrop-blur-md lg:hidden">
                    {stream.name}
                  </div>
                </div>
              ))}
            </div>

            <p className="hidden text-center text-[15px] leading-relaxed text-on-surface-variant italic lg:block lg:px-unit-12 lg:pt-unit-6 lg:pb-unit-12">
              {t("wearable.streamCaption")}
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
