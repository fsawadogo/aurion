import path from "path"
import { fileURLToPath } from "url"

import createNextIntlPlugin from "next-intl/plugin"

const withNextIntl = createNextIntlPlugin("./i18n/request.ts")

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export for AWS Amplify manual-deploy hosting (platform WEB),
  // mirroring the portal's architecture. trailingSlash gives dir-style
  // index.html files, which is how Amplify's CDN serves static routes.
  output: "export",
  trailingSlash: true,
  turbopack: {
    root: __dirname,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default withNextIntl(nextConfig)
