"use client";

import { useParams, usePathname } from "next/navigation";
import { useMemo } from "react";

/**
 * Returns the dynamic segment value for the current route, robust
 * against the Next.js static-export gotcha that broke the deployed
 * portal.
 *
 * Under `output: "export"`, every dynamic route must declare a
 * `generateStaticParams()` set. We don't know real IDs at build time —
 * sessions are issued at runtime when a physician finishes a recording —
 * so each page returns `[{ id: "_" }]` (a sentinel) and we lean on
 * Amplify's SPA-fallback rewrite (see `infrastructure/amplify.tf`'s
 * `custom_rules`) to serve the `_/index.html` shell for any real URL.
 *
 * But `useParams()` from `next/navigation` reads from the *matched route
 * params*, which in static export are baked at build time — so it
 * returns the sentinel `"_"` regardless of what the browser URL bar
 * actually says. Code that does `params.id` then fetches
 * `/api/v1/notes/_/detail` and gets 422'd by the backend UUID
 * validator. `usePathname()` reflects the real URL bar at runtime;
 * the last segment is what we want.
 *
 * Build-time / SSR safe — at build there's no real URL, so we trust
 * `useParams()`. At runtime the URL always wins.
 *
 * @param paramKey  The `[slug]` name from the route, used as the
 *                  SSR fallback key (e.g. "id", "sessionId",
 *                  "identifier").
 */
export function useRouteSegment(paramKey: string): string {
  const pathname = usePathname();
  const params = useParams<Record<string, string | string[]>>();

  return useMemo(() => {
    const paramVal = params?.[paramKey];
    const raw = Array.isArray(paramVal) ? paramVal[0] : paramVal;

    // Build-time / SSR path: usePathname is unreliable; trust the param.
    if (!pathname || pathname === "/") return raw ?? "";

    // Runtime: read the real URL. The dynamic segment is the last
    // non-empty path segment in every dynamic route we ship — the routes
    // are `/sessions/[id]`, `/audit/[sessionId]`, `/eval/[id]`,
    // `/portal/notes/[id]`, `/portal/patients/[identifier]`,
    // `/portal/templates/[id]`. Last segment covers all of them.
    const segments = pathname.split("/").filter(Boolean);
    const last = segments[segments.length - 1] ?? "";

    // If the URL last segment is the placeholder sentinel itself, the
    // user really did navigate to /sessions/_ (Amplify direct hit on
    // the placeholder). Surface the sentinel — the caller's loader
    // will surface the resulting 422 in its error banner, which is
    // less confusing than silently swallowing the navigation.
    const candidate = last || raw || "";

    try {
      return decodeURIComponent(candidate);
    } catch {
      // Identifier with invalid % escapes — render raw, let the API
      // call surface the 422 rather than crashing the client.
      return candidate;
    }
  }, [pathname, params, paramKey]);
}
