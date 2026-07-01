import PatientChartClient from "./PatientChartClient";

/**
 * Server shell for `/portal/admin/patients/[identifier]` under
 * `output: "export"` — the cross-clinician Patient Chart (#604).
 *
 * Same `generateStaticParams` + Amplify SPA-fallback pattern as the
 * owner-scoped `/portal/patients/[identifier]` shell: identifiers are
 * free-form and unknown at build time, so we emit one placeholder entry
 * and rely on the Amplify rewrite to serve this `index.html` for any real
 * identifier path. The client reads the identifier via `useRouteSegment`.
 *
 * ### PHI note — different rationale from the owner page
 * The owner page justifies the identifier-in-URL on the endpoint being
 * owner-scoped (another clinician gets an empty list). That does NOT hold
 * here: this page's backend endpoint
 * (`/admin/patients/{identifier}/encounters`) returns OTHER clinicians'
 * sessions by design. The compensating control is instead
 * **role gate (CLINICAL_ADMIN/ADMIN) ∧ the `cross_clinician_chart_enabled`
 * feature flag** — both enforced server-side; the endpoint 404s otherwise.
 * The client still keeps `document.title` generic and never logs the
 * identifier, and URL-encodes it on any outbound nav.
 */

export const dynamicParams = false;

export async function generateStaticParams(): Promise<{ identifier: string }[]> {
  return [{ identifier: "_" }];
}

export default function AdminPatientChartPage() {
  return <PatientChartClient />;
}
