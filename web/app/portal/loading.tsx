import AurionSplash from "@/components/AurionSplash";

/**
 * Portal route-segment loading UI — the in-app entry splash
 * (Stitch prompt 05): squircle mark + "Portal" eyebrow. Shown while a
 * /portal/* segment resolves.
 */
export default function PortalLoading() {
  return <AurionSplash variant="portal" />;
}
