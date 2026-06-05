"use client";

import { ReactNode } from "react";
import { Lock } from "lucide-react";
import { AurionLogoLockup } from "@/components/AurionLogo";

/**
 * Shared premium chrome for the three auth screens — login,
 * forgot-password, reset-password.
 *
 * Pulled out as a component on the THIRD copy of the same shell per
 * the DRY rule in AURION-CODING-WORKFLOW.md §6c. The body is what
 * varies (form fields, copy, CTA), so children get rendered inside
 * a centered max-w 400px card; everything around it — navy gradient,
 * gold halo, brand lockup, footer lock line — lives here.
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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden aurion-chrome-navy px-4">
      {/* Ambient gold halo — premium hero glow behind the form card. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-48 left-1/2 h-[640px] w-[760px] -translate-x-1/2 rounded-full bg-gold-500/[0.10] blur-3xl animate-aurion-glow"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 right-[-10%] h-[440px] w-[440px] rounded-full bg-navy-500/30 blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-20 -left-20 h-[360px] w-[360px] rounded-full bg-navy-500/20 blur-3xl"
      />

      <div className="relative z-10 w-full max-w-[400px] animate-aurion-slide-up">
        {slot}

        {/* Brand lockup — pixel-identical to the iOS splash hero. */}
        <div className="mb-10 flex justify-center">
          <AurionLogoLockup height={220} glow />
        </div>

        {/* Card */}
        <div className="rounded-aurion-xl bg-white/[0.98] p-8 shadow-[0_24px_60px_-12px_rgba(8,18,38,0.50)] ring-1 ring-white/10 backdrop-blur">
          {children}
        </div>

        <p className="mt-8 flex items-center justify-center gap-1.5 text-center text-[11.5px] text-white/55 tracking-wide">
          <Lock className="h-3 w-3" />
          Aurion Clinical AI &middot; For authorized personnel only
        </p>
      </div>
    </div>
  );
}
