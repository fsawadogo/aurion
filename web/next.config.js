/**
 * Next.js config for the Aurion admin / clinician portal.
 *
 * `output: "export"` (DEPLOY-WEB):
 *   Builds the portal as a fully static bundle in `web/out/`. The
 *   bundle is uploaded to AWS Amplify via the manual-deploy API
 *   (see `web/scripts/deploy.sh` and `.github/workflows/web.yml`).
 *   Manual deploy avoids needing a GitHub PAT in Amplify's GitHub
 *   source connector — that would otherwise be a rotation toil +
 *   secret-management surface for a 5-clinician pilot.
 *
 *   Trade-offs documented in `docs/plans/deploy-web.md`:
 *     - no server components touching cookies / headers at request
 *       time (i18n migrated to client-side LocaleProvider)
 *     - no app/api/* route handlers (Aurion API lives on FastAPI)
 *     - no `dynamic = "force-dynamic"` (the cognito callback page
 *       hydrates and reads the URL on mount — no dynamic flag
 *       needed)
 *
 * No `createNextIntlPlugin` wrap: the plugin's purpose is to wire
 * the server-side `getRequestConfig` consumer at `i18n/request.ts`,
 * and that consumer is incompatible with static export (no request
 * to serve). We migrated to client-side i18n via
 * `web/i18n/LocaleProvider.tsx`, which just uses `NextIntlClientProvider`
 * directly — no plugin needed.
 *
 * `trailingSlash: true` ensures Amplify (and any CDN) serves
 * `/dashboard/` as `dashboard/index.html` — the file Next.js
 * actually emits under static export — avoiding a 404 round-trip.
 *
 * `images.unoptimized: true` is required for static export — the
 * default `next/image` loader needs a runtime server. The portal
 * doesn't currently use `next/image`, so this is forward-looking.
 */

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
