"use client"

import { PlayCircle } from "lucide-react"
import { useTranslations } from "next-intl"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { SITE } from "@/lib/site"

/** Secondary hero CTA — opens the demo reel in place rather than navigating away. */
export function WatchVideoButton() {
  const t = useTranslations("home")

  return (
    <Dialog>
      <DialogTrigger className="inline-flex min-h-11 items-center gap-unit-2 rounded-lg px-unit-4 py-unit-3 text-[15px] font-medium text-secondary underline-offset-4 transition-colors hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
        <PlayCircle className="h-5 w-5" aria-hidden />
        {t("hero.watchVideo")}
      </DialogTrigger>

      <DialogContent className="max-w-3xl gap-unit-4 rounded-medical border-outline-variant/40 bg-surface-container-lowest p-unit-6">
        <DialogHeader>
          <DialogTitle className="font-display text-headline-md">
            {t("video.title")}
          </DialogTitle>
          <DialogDescription className="text-on-surface-variant">
            {t("video.description")}
          </DialogDescription>
        </DialogHeader>

        {/*
          eslint-disable-next-line jsx-a11y/media-has-caption
          preload="none" + mount-on-open (Radix only renders DialogContent when
          open) means the 24 MB file is fetched on click, never on page load.
        */}
        <video
          controls
          autoPlay
          playsInline
          preload="none"
          poster={SITE.heroVideoPoster}
          className="w-full rounded-lg border border-outline-variant/30"
        >
          <source src={SITE.heroVideo} type="video/mp4" />
        </video>
      </DialogContent>
    </Dialog>
  )
}
