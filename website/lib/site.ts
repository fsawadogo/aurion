/**
 * Absolute origin used to resolve metadata URLs (openGraph images, canonicals).
 * Netlify injects `URL` at build time; set NEXT_PUBLIC_SITE_URL to override.
 */
const baseUrl =
  process.env.NEXT_PUBLIC_SITE_URL ??
  process.env.URL ??
  "http://localhost:3000"

/** Public marketing URLs — no secrets */
export const SITE = {
  baseUrl,
  /**
   * FastAPI backend origin for public endpoints (waitlist). Static export:
   * baked at build time; override per environment with NEXT_PUBLIC_API_BASE.
   */
  apiBaseUrl:
    process.env.NEXT_PUBLIC_API_BASE ?? "https://api-dev.aurionclinical.com",
  /** Legal entity for copyright, bylines, and metadata */
  companyLegalName: "Aurion Intelligence Inc.",
  /** Platform / digital twin. The assistant inside it is "Peri" ("Ask Peri"). */
  productName: "PeriTwin",
  assistantName: "Peri",
  email: "contact@aurion.health",
  /** Physician portal (external app, separate domain). Opens in a new tab. */
  physicianPortalUrl: "https://portal.peritwin.com",
  bookDemoMailto:
    "mailto:contact@aurion.health?subject=Request%20a%20demo%20%E2%80%94%20PeriTwin",
  contactSalesMailto:
    "mailto:contact@aurion.health?subject=Enterprise%20inquiry%20%E2%80%94%20PeriTwin",
  /** Demo reel played by the hero's "Watch video" control. Click-to-play only. */
  heroVideo: "/peritwin-demo.mp4",
  heroVideoPoster: "/peritwin-demo-poster.jpg",
}

/** Full brand lockup (tagline is part of the artwork). Single source for the
 * footer and OG image so the intrinsic dims can't drift. */
export const LOGO = {
  src: "/peritwin-logo.png",
  width: 1248,
  height: 667,
} as const

