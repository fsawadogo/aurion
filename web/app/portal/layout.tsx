import Sidebar from "@/components/Sidebar";

/**
 * Layout wrapper for `/portal/*` clinician-facing pages.
 *
 * Same Sidebar + content-area pattern as the admin `/dashboard` layout
 * — clinicians see a different filtered nav list per the role gate
 * inside Sidebar.tsx, but the chrome is identical. Keeping a separate
 * layout (vs collapsing into one) so the portal can diverge stylistically
 * later (e.g. brighter accent, larger note-review pane) without touching
 * the admin surface.
 */
export default function PortalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <Sidebar />
      <main className="lg:pl-64">{children}</main>
    </div>
  );
}
