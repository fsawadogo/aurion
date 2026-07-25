"use client"

import { Moon, Sun } from "lucide-react"
import { useTranslations } from "next-intl"
import { useTheme } from "next-themes"
import { useEffect, useState } from "react"

/**
 * Light/dark toggle — follows the system until the visitor chooses.
 * Renders a fixed-size placeholder until mounted so the icon can't
 * mismatch between server HTML and the client's resolved theme.
 */
export function ThemeToggle() {
  const t = useTranslations("common")
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => setMounted(true), [])

  const dark = resolvedTheme === "dark"

  return (
    <button
      type="button"
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="flex h-11 w-11 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      aria-label={t(dark ? "theme.light" : "theme.dark")}
    >
      {mounted ? (
        dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />
      ) : (
        <span className="h-5 w-5" aria-hidden />
      )}
    </button>
  )
}
