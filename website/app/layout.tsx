import { Analytics } from "@vercel/analytics/next"
import { Hanken_Grotesk, Inter, JetBrains_Mono } from "next/font/google"

import "./globals.css"

/** Body — clinical notes and patient data. Chosen for legibility at length. */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
})

/** Headlines — sharp, contemporary, anchors the page visually. */
const hanken = Hanken_Grotesk({
  subsets: ["latin"],
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
      className={`${inter.variable} ${hanken.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="font-sans antialiased">
        {children}
        {enableVercelAnalytics && <Analytics />}
      </body>
    </html>
  )
}
