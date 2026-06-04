"use client";

import { useParams, usePathname } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * Returns the dynamic segment value for the current route, robust
 * against the Next.js static-export gotchas that have broken the
 * deployed portal three times now. The browser address bar is the
 * only source of truth this hook trusts.
 *
 * Background — three compounding bugs:
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
 *     collapses the pathname back to the closest matching parent route
 *     (`/portal/notes/<uuid>` → `/portal/notes`), so `usePathname()`
 *     gives `"notes"` as last-segment. (PR #230 v2.)
 *
 *  3. Even reading `window.location.pathname` in a post-mount effect
 *     isn't enough: the calling page's data-fetch `useEffect` runs on
 *     the first render with whatever value `useState` returned, then
 *     races with our update. Two fetches fly — one with `"_"`, one
 *     with the real id — and the failed `"_"` one wins state writes
 *     intermittently. (PR #231 v3.)
 *
 * The fix is to read `window.location.pathname` SYNCHRONOUSLY in
 * `useState`'s lazy initializer, so the very first render already
 * carries the correct segment. The downside is a one-time React
 * hydration warning (SSR shell rendered "_"; client first render
 * renders the real id) — acceptable for an internal admin portal.
 *
 * Effect-based re-read stays for Next router pushes / popstate, so
 * navigating between dynamic routes still updates without a reload.
 *
 * @param paramKey  The `[slug]` name from the route. Used as the
 *                  build-time / SSR fallback when `window` is absent.
 */
export function useRouteSegment(paramKey: string): string {
  const params = useParams<Record<string, string | string[]>>();
  // `usePathname()` is wrong (see header), but we still depend on it
  // so this hook re-evaluates after a Next router push — that fires a
  // pathname change even when the value collapses to the parent route.
  const pathname = usePathname();

  const [segment, setSegment] = useState<string>(() => readSegmentSync(params, paramKey));

  useEffect(() => {
    if (typeof window === "undefined") return;

    function readFromUrl(): void {
      const next = readSegmentFromWindow();
      if (next) setSegment(next);
    }

    readFromUrl();
    window.addEventListener("popstate", readFromUrl);
    return () => window.removeEventListener("popstate", readFromUrl);
  }, [pathname]);

  return segment;
}

// ── helpers ────────────────────────────────────────────────────────

function readSegmentSync(
  params: Record<string, string | string[]> | null,
  paramKey: string,
): string {
  // Client: the URL bar is the literal truth Amplify's 200 rewrite
  // never modifies. Read it synchronously so the calling page's data
  // fetch on first render uses the real id, not the baked sentinel.
  if (typeof window !== "undefined") {
    const fromWindow = readSegmentFromWindow();
    if (fromWindow) return fromWindow;
  }
  // SSR / build time: no window, fall back to the route param. This
  // bakes "_" into the static shell — invisible to the user once the
  // client hydrates.
  const p = params?.[paramKey];
  const raw = Array.isArray(p) ? p[0] : p;
  return raw ?? "";
}

function readSegmentFromWindow(): string {
  const segs = window.location.pathname.split("/").filter(Boolean);
  const last = segs[segs.length - 1] ?? "";
  if (!last) return "";
  try {
    return decodeURIComponent(last);
  } catch {
    // Identifier with invalid % escapes — render the raw segment
    // rather than crashing. The downstream API call will surface the
    // 422 in the page's normal failure banner.
    return last;
  }
}
