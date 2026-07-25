import { Analytics } from "@vercel/analytics/next"
import { Inter, JetBrains_Mono, Schibsted_Grotesk } from "next/font/google"

import { ThemeProvider } from "@/components/theme-provider"

import "./globals.css"

/** Body — clinical notes and patient data. Chosen for legibility at length. */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
})

/** Headlines — a grotesk with real character; used only at display sizes. */
const schibsted = Schibsted_Grotesk({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-hanken",
})

/** Data labels only — timestamps, metadata, sensor readings. Never prose. */
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["500"],
  variable: "--font-jetbrains-mono",
})

/**
 * Root shell only — locale, `<html lang>`, and copy live under `app/[locale]/`.
 * @see docs/i18n.md
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const enableVercelAnalytics = process.env.NODE_ENV === "production" && process.env.VERCEL === "1"

  return (
    <html
      className={`${inter.variable} ${schibsted.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="font-sans antialiased">
        {/* class-attribute theming: follows the OS until the visitor picks
            via the header ThemeToggle; tokens live in globals.css (.dark). */}
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
        {enableVercelAnalytics && <Analytics />}
      </body>
    </html>
  )
}
