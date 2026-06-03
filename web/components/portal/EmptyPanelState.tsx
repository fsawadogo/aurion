import { ReactNode } from "react";

/**
 * Friendly empty state for any portal panel — circular icon chip,
 * headline, soft hint line, centered vertically and horizontally.
 *
 * Lifted out of `app/portal/dashboard/page.tsx` during #61's
 * patient-detail slice so the new patient page can reuse the exact
 * same visual rhythm (mb-3 chip + aurion-callout title + 28ch hint
 * line). Re-implementing this in a second file would silently drift.
 *
 * Intentionally takes no CTA prop — empty states in this portal never
 * imply "start a session here", because session creation happens on
 * the iOS app. If a future panel needs an action, add it inline next
 * to the EmptyPanelState rather than baking a CTA slot into this
 * primitive.
 */
export default function EmptyPanelState({
  icon,
  title,
  hint,
}: {
  icon: ReactNode;
  title: string;
  hint: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-6 text-center">
      <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-gold-50 text-gold-600">
        {icon}
      </div>
      <p className="aurion-callout font-medium text-aurion-primary">{title}</p>
      <p className="mt-1 text-xs text-aurion-secondary max-w-[28ch] leading-relaxed">
        {hint}
      </p>
    </div>
  );
}
