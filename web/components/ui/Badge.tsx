import { ReactNode } from "react";

/**
 * Aurion badge — five semantic variants with a paired colored dot.
 *
 * Variants match iOS status colors (`aurionGreen` / `aurionAmber` /
 * `aurionRed` / `aurionBlue`) so the meaning carries between iOS and
 * web (green=done, amber=needs-review, red=conflict/failed,
 * blue=in-progress, neutral=archived/passive).
 *
 * The chip uses a 0.5px-equivalent inset ring (1px @ 0.6 opacity) so
 * the silhouette is crisp on white but doesn't fight with the card
 * shadow on hover.
 */

const variantStyles = {
  success: "bg-emerald-50 text-emerald-700 ring-emerald-600/15",
  warning: "bg-amber-50 text-amber-800 ring-amber-600/20",
  error:   "bg-red-50 text-red-700 ring-red-600/15",
  info:    "bg-blue-50 text-blue-700 ring-blue-600/15",
  neutral: "bg-canvas text-navy-600 ring-navy-600/10",
  brand:   "bg-gold-50 text-gold-700 ring-gold-600/20",
};

const dotColors: Record<keyof typeof variantStyles, string> = {
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error:   "bg-accent-red",
  info:    "bg-blue-500",
  neutral: "bg-navy-400",
  brand:   "bg-gold-500",
};

interface BadgeProps {
  variant?: keyof typeof variantStyles;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}

export default function Badge({
  variant = "neutral",
  children,
  className = "",
  dot = false,
}: BadgeProps) {
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 " +
        "text-[11px] font-semibold tracking-wide " +
        "ring-1 ring-inset " +
        variantStyles[variant] + " " +
        className
      }
    >
      {dot && (
        <span className={"h-1.5 w-1.5 rounded-full " + dotColors[variant]} />
      )}
      {children}
    </span>
  );
}
