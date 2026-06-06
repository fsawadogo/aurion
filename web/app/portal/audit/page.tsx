import MyAuditClient from "./MyAuditClient";

/**
 * /portal/audit — clinician self-audit log (#162).
 *
 * Mirror of the compliance-officer-facing `/audit` route, but scoped
 * to the caller's own actor_id via `GET /api/v1/me/audit`. The
 * backend filter is enforced at the dependency layer, so this page
 * shell stays presentation-only — it just hands off to the client
 * component that owns the filter + pagination state.
 *
 * Server component so the layout's chrome (Sidebar, etc.) stays
 * server-rendered; the interactive table is the client child.
 */
export default function PortalSelfAuditPage() {
  return <MyAuditClient />;
}
