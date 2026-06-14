import AurionSplash from "@/components/AurionSplash";

/**
 * Root route-segment loading UI — the branded app-entry splash
 * (Stitch prompt 04). Next.js renders this while the matched segment
 * resolves, so the navy/gold splash fills the real load moment.
 */
export default function RootLoading() {
  return <AurionSplash variant="root" />;
}
