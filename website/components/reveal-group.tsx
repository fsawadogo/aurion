"use client"

import { ReactNode, useEffect, useRef } from "react"

/**
 * Scroll-reveal orchestrator — element-level, per-element triggered.
 *
 * Wrap a region once; every descendant carrying `data-reveal` (plus an
 * optional `--rd` custom property for sibling stagger) animates in when
 * IT enters the viewport — not when the section's top does. That keeps
 * the reveal visible at every scroll depth: a card two screens down
 * animates when you reach it, instead of having finished invisibly.
 * Signature motions ride the same observer: `.spine-line` /
 * `.spine-line-v` draw the journey rail, `.grow-bar` raises chart bars.
 *
 * Elements shift only 14px and trigger slightly inside the viewport, so
 * nothing ever reads as a blank region. Reduced motion is neutered in
 * CSS (globals.css) — the observer always fires; the media query makes
 * it a no-op visually.
 */
const REVEAL_SELECTOR = "[data-reveal], .spine-line, .spine-line-v, .grow-bar"

export function RevealGroup({
  children,
  className = "",
}: {
  children: ReactNode
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const root = ref.current
    if (!root) return

    const targets = root.matches(REVEAL_SELECTOR)
      ? [root, ...root.querySelectorAll(REVEAL_SELECTOR)]
      : [...root.querySelectorAll(REVEAL_SELECTOR)]

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in")
            observer.unobserve(entry.target)
          }
        }
      },
      // Fire once ~6% of the viewport height inside the bottom edge —
      // late enough that the motion is actually seen, early enough that
      // content never feels withheld.
      { threshold: 0.01, rootMargin: "0px 0px -6% 0px" },
    )

    targets.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={ref} className={`reveal-group ${className}`}>
      {children}
    </div>
  )
}
