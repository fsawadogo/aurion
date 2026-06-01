/**
 * Aurion brand mark — pulls the canonical PNG assets verbatim from
 * the iOS app (`AppIcon.appiconset/icon-1024.png` and
 * `AurionLogoFull.imageset/AurionLogoFull.png`). Web and iOS render
 * pixel-identical brand chrome — no SVG re-creation, no drift between
 * platforms.
 *
 * Files live in `web/public/brand/` after `cp` from
 * `ios/Aurion/Aurion/Assets.xcassets/`. Re-copy when the iOS art
 * updates; this component picks up the change with no code edit.
 *
 * Two flavors:
 *
 *   <AurionLogo />        — mark only (squircle icon: navy background,
 *                            gold "A" with the comet + star). Used in
 *                            the sidebar header and as a small visual
 *                            anchor anywhere chrome needs the brand.
 *
 *   <AurionLogoLockup />  — full lockup (mark + "Aurion" wordmark +
 *                            "the gold standard in clinical AI"
 *                            tagline). Lives only on the login hero
 *                            today; the asset is already on a navy
 *                            background, so it sits cleanly on the
 *                            navy chrome behind it.
 */

import Image from "next/image";

interface AurionLogoProps {
  size?: number;
  /** Soft pulsing gold halo behind the mark — used on the login
   * splash and other premium chrome moments. */
  glow?: boolean;
  className?: string;
  /** When true (default for the sidebar / chrome use), the icon is
   * rendered with rounded corners on a transparent wrapper so it
   * reads as a brand chip. Set to false to render the raw squircle
   * with its own bundled corners (good for product hero shots). */
  rounded?: boolean;
}

export function AurionLogo({
  size = 40,
  glow = false,
  rounded = true,
  className,
}: AurionLogoProps) {
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
      <Image
        src="/brand/aurion-icon.png"
        alt="Aurion"
        width={size}
        height={size}
        priority
        className={
          "relative h-full w-full select-none " +
          (rounded
            ? "rounded-[22%] ring-1 ring-white/10 shadow-[0_2px_8px_-2px_rgba(8,18,38,0.35)]"
            : "")
        }
      />
    </span>
  );
}

interface AurionLogoLockupProps {
  /** Height of the rendered lockup in px. Mark + wordmark + tagline
   * scale together; the PNG is square so the actual rendered width
   * tracks naturally. */
  height?: number;
  className?: string;
  /** Soft gold glow behind the lockup — used on the login hero. */
  glow?: boolean;
}

export function AurionLogoLockup({
  height = 200,
  glow = false,
  className,
}: AurionLogoLockupProps) {
  return (
    <span
      className={
        "relative inline-flex items-center justify-center " +
        (className ?? "")
      }
      style={{ height }}
    >
      {glow && (
        <span
          aria-hidden
          className="absolute inset-0 rounded-full bg-gold-300 opacity-25 blur-3xl animate-aurion-glow"
          style={{ transform: "scale(0.7)" }}
        />
      )}
      <Image
        src="/brand/aurion-logo-full.png"
        alt="Aurion — the gold standard in clinical AI"
        width={height}
        height={height}
        priority
        className="relative h-full w-auto select-none"
      />
    </span>
  );
}

export default AurionLogo;
