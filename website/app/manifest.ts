import type { MetadataRoute } from "next"

export const dynamic = "force-static"

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "PeriTwin",
    short_name: "PeriTwin",
    description: "Personalized clinical intelligence across the continuum of care",
    start_url: "/",
    display: "standalone",
    background_color: "#fbf8ff",
    theme_color: "#264dd9",
    icons: [
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
      },
    ],
  }
}
