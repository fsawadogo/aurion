/**
 * SourceChip — the site's signature element.
 *
 * PeriTwin's core promise is that every sentence in a note is traceable
 * to its source. The marketing site holds itself to the same rule: key
 * claims carry a small superscript chip that reveals the receipt on
 * hover / focus. CSS-only (group-hover + focus-within), keyboard
 * reachable, no JS.
 */
export function SourceChip({
  id,
  source,
  align = "center",
}: {
  /** Short chip label, e.g. "S1" or "00:14" */
  id: string
  /** The receipt shown in the popover */
  source: string
  /**
   * Tooltip anchor. Chips that sit near the right edge of their
   * container (end-of-line citations) use "end" so the popover grows
   * leftward instead of poking past the viewport on mobile.
   */
  align?: "center" | "end"
}) {
  return (
    <span className="group/chip relative inline-block align-super">
      <button
        type="button"
        className="ml-0.5 inline-flex h-[18px] min-w-[26px] cursor-help items-center justify-center rounded-full border border-primary/30 bg-primary-fixed px-1.5 font-mono text-[10.5px] font-medium leading-none text-on-primary-fixed-variant transition-colors group-hover/chip:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        aria-label={`Source ${id}: ${source}`}
      >
        {id}
      </button>
      {/* Mobile: a fixed bottom toast (a popover anchored to an
          end-of-line chip clips at the viewport edge on a phone).
          sm+: a positioned popover above the chip. */}
      <span
        role="tooltip"
        className={`pointer-events-none fixed inset-x-4 bottom-6 z-50 rounded-lg border border-outline-variant/50 bg-surface-container-lowest p-3 text-left text-[12.5px] leading-snug font-normal tracking-normal text-on-surface-variant normal-case opacity-0 shadow-lg transition-opacity duration-150 group-hover/chip:opacity-100 group-focus-within/chip:opacity-100 sm:absolute sm:inset-x-auto sm:bottom-full sm:mb-2 sm:w-64 ${
          align === "end"
            ? "sm:right-0"
            : "sm:left-1/2 sm:-translate-x-1/2"
        }`}
      >
        {source}
      </span>
    </span>
  )
}
