import CommandPalette from "@/components/portal/CommandPalette";
import NotificationBell from "@/components/portal/NotificationBell";
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
 *
 * The `<main>` element's left padding reads a CSS custom property
 * (`--aurion-sidebar-width`) that the Sidebar publishes on every
 * collapse toggle. The fallback of 256px matches the initial uncollapsed
 * width so SSR + first paint look right before the client hydrates and
 * reads localStorage. The pl-aurion-sidebar utility lives in globals.css.
 */
export default function PortalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <Sidebar />
      <main className="lg:pl-aurion-sidebar transition-[padding-left] duration-aurion ease-aurion">
        {children}
      </main>
      {/* Notification bell — pinned top-right; visible from every
          portal page. Same /me/audit data source as ActivityFeed
          on the dashboard, but with unread tracking + dropdown
          presentation. */}
      <NotificationBell />

      {/* ⌘K command palette — mounted at layout level so it's
          available on every portal route. Self-managed open state
          via global keyboard listener; no provider needed. */}
      <CommandPalette />
    </div>
  );
}
