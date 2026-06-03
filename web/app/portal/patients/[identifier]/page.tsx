import PatientDetailClient from "./PatientDetailClient";

/**
 * Server shell for `/portal/patients/[identifier]` under
 * `output: "export"`.
 *
 * Same `generateStaticParams` + Amplify SPA-fallback pattern as
 * `app/sessions/[id]/page.tsx` and `app/portal/notes/[id]/page.tsx`:
 * we don't know patient identifiers at build time (they're free-form
 * strings entered by a physician at recording time), so we return a
 * single placeholder entry and rely on the Amplify rewrite to serve
 * the same `index.html` for any real identifier path. The client
 * component reads the identifier via `useParams()`.
 *
 * `dynamicParams = false` keeps the build from ever attempting to
 * render an unknown identifier server-side, which would fail under
 * static export.
 *
 * ### PHI note
 * The patient identifier appears in the URL path. This is acceptable
 * per the data classification because the underlying endpoint
 * `/me/patients/{identifier}/sessions` is owner-scoped on the backend
 * (filters by `clinician_id == user.user_id` — see
 * `backend/app/api/v1/me.py::list_my_sessions_by_patient_identifier`),
 * so another clinician hitting the same URL gets an empty list. The
 * client component also:
 *   - keeps `document.title` generic ("Patient encounters") so the
 *     identifier never leaks into browser-history previews or OS
 *     task-switcher snapshots
 *   - never logs the identifier to `console.log`
 *   - URL-encodes the identifier on any outbound nav so identifiers
 *     containing `/` or `#` stay safe
 */

export const dynamicParams = false;

export async function generateStaticParams(): Promise<{ identifier: string }[]> {
  return [{ identifier: "_" }];
}

export default function PortalPatientDetailPage() {
  return <PatientDetailClient />;
}
