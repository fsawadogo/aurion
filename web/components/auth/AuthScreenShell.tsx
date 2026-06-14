"use client";

import { ReactNode } from "react";
import { Lock } from "lucide-react";
import { AurionLogoLockup } from "@/components/AurionLogo";

/**
 * Shared premium chrome for the three auth screens — login,
 * forgot-password, reset-password.
 *
 * Split-hero layout (Stitch redesign): a navy brand hero on the left
 * (top on mobile) carrying the real Aurion logo lockup + a soft gold
 * halo, and a light form panel on the right holding the white card.
 * The body is what varies (form fields, copy, CTA) and lands inside
 * the max-w 400px card; everything around it lives here, so all three
 * auth screens stay pixel-consistent (DRY per AURION-CODING-WORKFLOW §6c).
 *
 * The above-the-card `slot` prop is for transient overlays the parent
 * needs to render outside the card box (the "Password reset" toast on
 * login is the only current user; positioning above the card keeps
 * the eye on the success message before it drops down to the form).
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
      {/* ── Brand hero — left on desktop, top on mobile. Uses the real
           Aurion logo lockup asset (never a substitute mark). ── */}
      <div className="relative flex shrink-0 items-center justify-center overflow-hidden aurion-chrome-navy px-8 py-16 lg:w-[46%] lg:py-0">
        {/* Ambient gold halo — premium hero glow behind the lockup. */}
        <div
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-1/2 h-[560px] w-[680px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gold-500/[0.10] blur-3xl animate-aurion-glow"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-40 -left-24 h-[440px] w-[440px] rounded-full bg-navy-500/25 blur-3xl"
        />
        <div className="relative z-10 flex flex-col items-center">
          <AurionLogoLockup height={232} glow />
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
            Aurion Clinical AI &middot; For authorized personnel only
          </p>
        </div>
      </div>
    </div>
  );
}
