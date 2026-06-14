"use client";

import { useTranslations } from "next-intl";
import { AurionLogo, AurionLogoLockup } from "@/components/AurionLogo";

/**
 * Full-screen branded splash — the calm, momentary loading state shown
 * while a route segment resolves. Wired as `app/loading.tsx` (root) and
 * `app/portal/loading.tsx` (in-app entry), so it fills the *real* Next.js
 * navigation/data-load moment rather than faking a delay on an instant
 * server redirect.
 *
 * Stitch redesign direction (prompts 04 / 05): a deep navy radial field,
 * the real Aurion logo (lockup at root, mark + "Portal" eyebrow in-app)
 * with a soft pulsing gold halo, and a thin gold shimmer loader beneath.
 * Premium, clinical-grade, brief.
 *
 * Logo is the real brand asset via `AurionLogo*` — never a substitute.
 */

interface AurionSplashProps {
  /** `root` = full lockup. `portal` = squircle mark + "Portal" eyebrow. */
  variant?: "root" | "portal";
}

export default function AurionSplash({ variant = "root" }: AurionSplashProps) {
  const t = useTranslations("Common");

  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={t("loadingWorkspace")}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center overflow-hidden bg-navy-700"
    >
      {/* Deep navy radial field — matches the login hero + iOS launch. */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 90% at 50% 42%, #16284E 0%, #0C1B37 48%, #081226 100%)",
        }}
      />
      {/* Soft pulsing gold halo behind the mark. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 h-[520px] w-[520px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gold-500/[0.10] blur-3xl animate-aurion-glow"
      />

      <div className="relative z-10 flex flex-col items-center gap-9 animate-aurion-fade-in">
        {variant === "portal" ? (
          <div className="flex flex-col items-center gap-3.5">
            <AurionLogo size={84} glow rounded={false} />
            <span className="text-aurion-micro uppercase tracking-[0.32em] text-gold-300">
              {t("portalEyebrow")}
            </span>
          </div>
        ) : (
          <AurionLogoLockup height={196} glow />
        )}

        {/* Thin gold shimmer loader — indeterminate sweep. */}
        <div className="relative h-[3px] w-44 overflow-hidden rounded-full bg-white/10">
          <div
            aria-hidden
            className="absolute inset-0"
            style={{
              backgroundImage:
                "linear-gradient(90deg, transparent 0%, rgb(var(--accent-400)) 50%, transparent 100%)",
              backgroundSize: "200% 100%",
              animation: "aurion-shimmer 1.4s linear infinite",
            }}
          />
        </div>

        <p className="text-aurion-caption text-navy-300">
          {t("loadingWorkspace")}
        </p>
      </div>
    </div>
  );
}
