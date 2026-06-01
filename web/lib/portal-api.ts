/**
 * Clinician-portal API client.
 *
 * Extends `web/lib/api.ts` for the `/api/v1/me/*` endpoint family
 * shipped in backend PR-B. Shares the `fetchWithAuth` wrapper (so
 * Cognito token refresh + 401-retry behaviour is identical to the
 * admin surface) but groups portal-only call sites here to keep
 * `api.ts` from sprawling.
 *
 * Pure typed wrappers around the JSON responses; no caching, no
 * client-side state. Components hold their own `useState` + call the
 * functions in `useEffect`.
 */

import { fetchWithAuth } from "@/lib/api";
import type {
  AuditFilters,
  CustomTemplate,
  PaginatedResponse,
  PhysicianProfile,
  PhysicianProfileUpdate,
  TemplateAuthoringSession,
  TemplateDefinition,
} from "@/types";

function buildQuery<T extends object>(params: T): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
    }
  }
  return parts.length > 0 ? `?${parts.join("&")}` : "";
}

/* ─── Profile ────────────────────────────────────────────────────────────── */

/** GET /api/v1/profile — the physician's own profile.
 *
 * Re-uses the existing `/profile` endpoint (it's already clinician-
 * scoped by virtue of the JWT subject) rather than the `/me/profile`
 * shape, so iOS and web hit the exact same row.
 */
export async function getMyProfile(): Promise<PhysicianProfile> {
  const r = await fetchWithAuth("/api/v1/profile");
  return r.json();
}

/** PUT /api/v1/profile — partial update.
 *
 * Server accepts a dict of fields to merge; only changed fields need
 * to be sent. Backend re-validates the practice_type comma-joined
 * convention.
 */
export async function updateMyProfile(
  body: PhysicianProfileUpdate,
): Promise<PhysicianProfile> {
  const r = await fetchWithAuth("/api/v1/profile", {
    method: "PUT",
    body: JSON.stringify(body),
  });
  return r.json();
}

/** GET /api/v1/profile/templates — the templates this physician
 * has preferred (full TemplateDefinition objects, not just keys). */
export async function getMyPreferredTemplates(): Promise<TemplateDefinition[]> {
  const r = await fetchWithAuth("/api/v1/profile/templates");
  return r.json();
}

/* ─── Audit (own) ────────────────────────────────────────────────────────── */

/** GET /api/v1/me/audit — own audit events.
 *
 * Same shape as the admin /audit endpoint (PaginatedAuditResponse)
 * so the existing audit table component can be reused once PR-D
 * wires the portal sessions inbox.
 */
export async function getMyAuditLog(filters: AuditFilters = {}) {
  const r = await fetchWithAuth(`/api/v1/me/audit${buildQuery(filters)}`);
  return r.json() as Promise<PaginatedResponse<unknown>>;
}

/* ─── Custom templates ───────────────────────────────────────────────────── */

export async function listMyCustomTemplates(): Promise<CustomTemplate[]> {
  const r = await fetchWithAuth("/api/v1/me/custom-templates");
  return r.json();
}

export async function createMyCustomTemplate(
  template: TemplateDefinition,
): Promise<CustomTemplate> {
  const r = await fetchWithAuth("/api/v1/me/custom-templates", {
    method: "POST",
    body: JSON.stringify({ template }),
  });
  return r.json();
}

export async function updateMyCustomTemplate(
  templateId: string,
  template: TemplateDefinition,
): Promise<CustomTemplate> {
  const r = await fetchWithAuth(
    `/api/v1/me/custom-templates/${templateId}`,
    { method: "PATCH", body: JSON.stringify({ template }) },
  );
  return r.json();
}

export async function deleteMyCustomTemplate(templateId: string): Promise<void> {
  await fetchWithAuth(`/api/v1/me/custom-templates/${templateId}`, {
    method: "DELETE",
  });
}

export async function uploadTemplateDocument(
  file: File,
): Promise<TemplateAuthoringSession> {
  // Multipart upload: we must let the browser set Content-Type so it
  // includes the multipart boundary. fetchWithAuth's default
  // "application/json" would break parsing. Empty string clears the
  // header without unsetting it (the headers spread inside
  // fetchWithAuth then overwrites with "application/json", which we
  // then re-clear via the explicit "" below — order matters).
  const form = new FormData();
  form.append("document", file);
  const r = await fetchWithAuth("/api/v1/me/custom-templates/upload", {
    method: "POST",
    body: form,
    // Setting "Content-Type" to an empty string is the simplest
    // documented way to make fetch() not auto-set the header at all.
    // The browser still injects the multipart Content-Type with
    // boundary at send time.
    headers: { "Content-Type": "" },
  });
  return r.json();
}

/* ─── Template authoring (conversational) ────────────────────────────────── */

export async function startTemplateAuthoring(): Promise<TemplateAuthoringSession> {
  const r = await fetchWithAuth("/api/v1/me/template-authoring", {
    method: "POST",
  });
  return r.json();
}

export async function getTemplateAuthoring(
  sessionId: string,
): Promise<TemplateAuthoringSession> {
  const r = await fetchWithAuth(
    `/api/v1/me/template-authoring/${sessionId}`,
  );
  return r.json();
}

export async function continueTemplateAuthoring(
  sessionId: string,
  message: string,
): Promise<TemplateAuthoringSession> {
  const r = await fetchWithAuth(
    `/api/v1/me/template-authoring/${sessionId}`,
    { method: "POST", body: JSON.stringify({ message }) },
  );
  return r.json();
}

export async function finalizeTemplateAuthoring(
  sessionId: string,
): Promise<CustomTemplate> {
  const r = await fetchWithAuth(
    `/api/v1/me/template-authoring/${sessionId}/finalize`,
    { method: "POST" },
  );
  return r.json();
}

/* ─── Bulk export ────────────────────────────────────────────────────────── */

/** POST /api/v1/me/export-bulk — returns a Blob (zip of DOCX files).
 *
 * Caller is responsible for triggering the browser download —
 * typical pattern is to URL.createObjectURL(blob) + click a hidden
 * anchor with `download` attribute. Audit log already records the
 * BULK_NOTE_EXPORT event on the server, no client-side ping needed.
 */
export async function bulkExport(sessionIds: string[]): Promise<Blob> {
  const r = await fetchWithAuth("/api/v1/me/export-bulk", {
    method: "POST",
    body: JSON.stringify({ session_ids: sessionIds }),
  });
  return r.blob();
}
