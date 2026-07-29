"use client"

import { useEffect } from "react"

/**
 * Root redirect — static export has no middleware, so "/" ships as a
 * tiny client bounce to the default locale. In production Amplify also
 * 302s "/" → "/en/" at the CDN.
 */
export default function RootRedirect() {
  useEffect(() => {
    window.location.replace("/en/")
  }, [])
  return null
}
