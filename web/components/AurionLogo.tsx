/**
 * Aurion brand mark — SVG port of the iOS `AurionHexLogo` (Theme.swift
 * line 776 onward). Same hex geometry, same gold/navy palette, scales
 * cleanly from 16px favicon-sized chrome up to 200px hero lockups.
 *
 * Two flavors:
 *   <AurionLogo />        — mark only (the hex + "A").
 *   <AurionLogoLockup />  — mark + wordmark side-by-side, used on the
 *                            login page hero and on the sidebar header.
 *
 * Use `tone="onLight"` (default) on canvas/surface backgrounds so the
 * inner A renders navy; `tone="onDark"` (sidebar, login chrome) makes
 * the A white so it reads against navy.
 */

import { SVGProps } from "react";

type Tone = "onLight" | "onDark";

interface AurionLogoProps extends Omit<SVGProps<SVGSVGElement>, "viewBox"> {
  size?: number;
  tone?: Tone;
  /** Adds a soft pulsing gold halo behind the mark — used on the
   * login splash + the dashboard hero on first paint. */
  glow?: boolean;
}

export function AurionLogo({
  size = 40,
  tone = "onLight",
  glow = false,
  className,
  ...rest
}: AurionLogoProps) {
  const letterColor = tone === "onDark" ? "#FFFFFF" : "#0C1B37";

  return (
    <span
      className={
        "relative inline-flex shrink-0 items-center justify-center " +
        (className ?? "")
      }
      style={{ width: size, height: size }}
    >
      {glow && (
        <span
          aria-hidden
          className="absolute inset-0 -m-3 rounded-full bg-gold-300 opacity-40 blur-2xl animate-aurion-glow"
        />
      )}
      <svg
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        width={size}
        height={size}
        className="relative"
        aria-hidden="true"
        {...rest}
      >
        {/* Outer hex — 2.5px gold stroke, rounded joins. */}
        <path
          d="M32 4 L56 18 V46 L32 60 L8 46 V18 Z"
          stroke="#C9A84C"
          strokeWidth={2.5}
          strokeLinejoin="round"
        />
        {/* Inner hex — same shape inset, half-opacity. */}
        <path
          d="M32 10 L51 21 V43 L32 54 L13 43 V21 Z"
          stroke="#C9A84C"
          strokeWidth={1}
          strokeOpacity={0.5}
          strokeLinejoin="round"
        />
        {/* "A" letterform — two strokes (peak + crossbar). */}
        <path
          d="M22 42 L32 20 L42 42"
          stroke={letterColor}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M26 35 H38"
          stroke={letterColor}
          strokeWidth={2.5}
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

interface AurionLogoLockupProps {
  /** Logo mark size in px; the wordmark scales relative to this. */
  size?: number;
  tone?: Tone;
  /** Render the "The gold standard in clinical AI" tagline beneath
   * the wordmark — used on the login hero, omitted on chrome. */
  tagline?: boolean;
  className?: string;
}

export function AurionLogoLockup({
  size = 40,
  tone = "onLight",
  tagline = false,
  className,
}: AurionLogoLockupProps) {
  const wordmarkColor = tone === "onDark" ? "text-white" : "text-navy-700";
  const taglineColor = tone === "onDark" ? "text-white/60" : "text-navy-400";
  // Wordmark sized off the mark so the lockup scales as a unit.
  const wordmarkSize = Math.round(size * 0.55);

  return (
    <span
      className={
        "inline-flex items-center gap-3 " + (className ?? "")
      }
    >
      <AurionLogo size={size} tone={tone} />
      <span className="flex flex-col leading-none">
        <span
          className={wordmarkColor + " font-semibold tracking-tight"}
          style={{ fontSize: wordmarkSize, letterSpacing: "-0.02em" }}
        >
          Aurion
        </span>
        {tagline && (
          <span
            className={taglineColor + " mt-1 font-medium tracking-wider uppercase"}
            style={{ fontSize: Math.round(size * 0.18) }}
          >
            The gold standard in clinical&nbsp;AI
          </span>
        )}
      </span>
    </span>
  );
}

export default AurionLogo;
