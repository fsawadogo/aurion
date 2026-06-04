"use client";

import { useParams, usePathname } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * Returns the dynamic segment value for the current route, robust
 * against the Next.js static-export gotchas that have broken the
 * deployed portal twice now. The browser address bar is the only
 * source of truth this hook trusts.
 *
 * Background — two compounding bugs:
 *
 *  1. Under `output: "export"`, every dynamic route declares a
 *     `generateStaticParams()` set. We don't know real IDs at build
 *     time, so each page returns `[{ id: "_" }]` (sentinel) and leans
 *     on Amplify's SPA-fallback rewrite to serve the `_/index.html`
 *     shell for any real URL. But `useParams()` reads from the
 *     *matched route params*, baked at build time — so it returns
 *     `"_"` regardless of the URL bar. (PR #228 v1.)
 *
 *  2. With `dynamicParams = false`, the App Router's pathname context
 *     refuses to recognise the unknown dynamic segment and *collapses*
 *     the pathname back to the closest matching parent route. For
 *     `/portal/notes/<uuid>` that's `/portal/notes` (the list page).
 *     So `usePathname()` returns `/portal/notes`, the last-segment
 *     trick produces `"notes"`, and downstream fetches hit
 *     `/api/v1/notes/notes/detail` → 422. (Found immediately after
 *     v1 deployed; this is v2.)
 *
 * `window.location.pathname` always reflects the literal URL bar,
 * which Amplify's 200-status rewrite never modifies. That's the only
 * value safe to trust in static export.
 *
 * Two-pass render keeps hydration warning-free: the initial render
 * uses the param (matches the SSR'd shell), then the post-mount
 * effect rewrites to the URL-derived value. The effect re-runs on
 * Next router navigations (`pathname` dep) and on browser
 * back/forward (`popstate` listener), so navigating between dynamic
 * routes stays correct without a full reload.
 *
 * @param paramKey  The `[slug]` name from the route, used as the
 *                  hydration-safe initial value.
 */
export function useRouteSegment(paramKey: string): string {
  const params = useParams<Record<string, string | string[]>>();
  // `usePathname()` is wrong (see header), but we still depend on it
  // so this hook re-evaluates after a Next router push — that fires a
  // pathname change even when the value collapses to the parent route.
  const pathname = usePathname();

  // Initial state mirrors what the SSR shell rendered with: the
  // baked-in build-time param ("_"). The effect immediately replaces
  // it on mount; the initial value just keeps hydration mismatch-free.
  const [segment, setSegment] = useState<string>(() => {
    const p = params?.[paramKey];
    const raw = Array.isArray(p) ? p[0] : p;
    return raw ?? "";
  });

  useEffect(() => {
    if (typeof window === "undefined") return;

    function readFromUrl(): void {
      const segs = window.location.pathname.split("/").filter(Boolean);
      const last = segs[segs.length - 1] ?? "";
      try {
        setSegment(decodeURIComponent(last));
      } catch {
        // Identifier with invalid % escapes — render the raw segment
        // rather than crashing. The downstream API call will surface
        // the 422 in the page's normal failure banner.
        setSegment(last);
      }
    }

    readFromUrl();
    window.addEventListener("popstate", readFromUrl);
    return () => window.removeEventListener("popstate", readFromUrl);
  }, [pathname]);

  return segment;
}
