"use client"

import { useEffect } from "react"

/**
 * Root redirect — static export has no middleware, so "/" ships as a
 * tiny client bounce to the default locale. In production Amplify also
 * 302s "/" → "/en/" at the CDN (see infrastructure/amplify_marketing.tf
 * in the main repo), so crawlers and curl never see this page; it only
 * covers local dev and direct index.html opens.
 */
export default function RootRedirect() {
  useEffect(() => {
    window.location.replace("/en/")
  }, [])
  return null
}
