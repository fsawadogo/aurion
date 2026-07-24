"use client";

import { ReactNode } from "react";
import { Lock } from "lucide-react";
import { AurionLogoLockup } from "@/components/AurionLogo";

/**
 * Shared premium chrome for the three auth screens — login,
 * forgot-password, reset-password.
 *
 * PeriTwin light hero (2026-07-23 redesign, per Faïçal): the brand
 * panel runs on the light periwinkle field (`aurion-chrome-brand`),
 * so the white PeriTwin lockup card reads as part of the page instead
 * of a floating rectangle on navy — and the lockup itself sits at a
 * restrained size. A soft accent halo + a circuit-purple bloom (both
 * logo hues) give the hero depth without darkness. The form panel is
 * unchanged: light canvas, white card, max-w 400px.
 *
 * The above-the-card `slot` prop is for transient overlays the parent
 * needs to render outside the card box (the "Password reset" toast on
 * login is the only current user).
 */

interface AuthScreenShellProps {
  /** Inside the white card. Title, subtitle, error banner, form. */
  children: ReactNode;
  /** Transient overlays above the card — currently the reset toast. */
  slot?: ReactNode;
}

export default function AuthScreenShell({
  children,
  slot,
}: AuthScreenShellProps) {
  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* ── Brand hero — left on desktop, compact band on mobile. ── */}
      <div className="relative flex shrink-0 items-center justify-center overflow-hidden aurion-chrome-brand px-8 py-10 lg:w-[46%] lg:py-0">
        {/* Accent halo — soft periwinkle breath behind the lockup. */}
        <div
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-1/2 h-[480px] w-[600px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gold-500/[0.10] blur-3xl animate-aurion-glow"
        />
        {/* Circuit-purple bloom — the logo's third hue, bottom-left. */}
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-32 -left-20 h-[380px] w-[380px] rounded-full bg-[#A695D6]/[0.18] blur-3xl"
        />
        <div className="relative z-10 flex flex-col items-center">
          <AurionLogoLockup height={150} />
        </div>
      </div>

      {/* ── Form panel — right on desktop, below on mobile. ── */}
      <div className="relative flex flex-1 items-center justify-center bg-canvas px-4 py-12 sm:px-8">
        <div className="w-full max-w-[400px] animate-aurion-slide-up">
          {slot}

          {/* Card */}
          <div className="rounded-aurion-xl bg-surface p-8 shadow-card ring-1 ring-hairline">
            {children}
          </div>

          <p className="mt-7 flex items-center justify-center gap-1.5 text-center text-[11.5px] tracking-wide text-navy-400">
            <Lock className="h-3 w-3" />
            PeriTwin &middot; For authorized personnel only
          </p>
        </div>
      </div>
    </div>
  );
}
