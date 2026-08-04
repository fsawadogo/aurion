"use client";

import Image from "next/image";
import { ReactNode } from "react";
import { Lock } from "lucide-react";

/**
 * Shared premium chrome for the three auth screens — login,
 * forgot-password, reset-password.
 *
 * Centered-column redesign (2026-07-25, per Faïçal): the previous
 * split layout gave half the screen to a boxed lockup card, which read
 * as two competing panels. Auth is one job, so the screen is now one
 * centered column on the light periwinkle field: a prominent brand row
 * (transparent mark + live-type two-tone wordmark — the same grammar
 * as the marketing site's nav; sized up 2026-08-03 on pilot feedback
 * that it read "super small even on web"), the white form card, and
 * the authorized-personnel line. The accent halo + circuit-lilac bloom
 * stay, dialed down so the card carries the hierarchy.
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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden aurion-chrome-brand px-4 py-12 sm:px-8">
      {/* Accent halo — soft periwinkle breath behind the card. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-[40%] h-[520px] w-[680px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gold-500/[0.08] blur-3xl animate-aurion-glow"
      />
      {/* Circuit-lilac bloom — the logo's third hue, bottom-left. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 -left-24 h-[380px] w-[380px] rounded-full bg-[#A695D6]/[0.14] blur-3xl"
      />

      <div className="relative z-10 w-full max-w-[420px] animate-aurion-slide-up">
        {/* Brand row — mark + live-type wordmark, prominent per pilot feedback. */}
        <div className="mb-8 flex items-center justify-center gap-3">
          <Image
            src="/brand/peritwin-mark.png"
            alt=""
            aria-hidden
            width={600}
            height={600}
            priority
            className="h-16 w-auto sm:h-20"
          />
          {/* Brand hexes on purpose (not theme tokens): the wordmark sits
              on the light brand field in BOTH themes, and navy-900 flips
              near-white in dark mode — which made "Twin" invisible. */}
          {/* rem (not px) so the wordmark scales WITH the rem-based mark under
              browser font-size preferences: 2.25rem/2.75rem = 36/44px default. */}
          <span className="font-display text-[2.25rem] font-bold leading-none tracking-tight sm:text-[2.75rem]">
            <span className="text-[#5D72DB]">Peri</span>
            <span className="text-[#25349B]">Twin</span>
          </span>
        </div>

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
  );
}
