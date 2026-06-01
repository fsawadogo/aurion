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
  Note,
  NoteDetail,
  PaginatedResponse,
  PatientSessionMatch,
  PatientSummary,
  PhysicianMacro,
  PhysicianMacroCreate,
  PhysicianMacroUpdate,
  PhysicianProfile,
  PhysicianProfileUpdate,
  Session as SessionRow,
  Stage2Status,
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

/* ─── Sessions (own) ─────────────────────────────────────────────────────── */

/** GET /api/v1/sessions — the caller's own sessions.
 *
 * The base /sessions endpoint is already clinician-scoped server-
 * side (it filters on clinician_id == user.user_id), so the portal
 * uses the same path as iOS rather than introducing a /me/sessions
 * duplicate. Server returns the full list — pagination + filtering
 * happen client-side at pilot scale.
 */
export async function listMySessions(): Promise<SessionRow[]> {
  const r = await fetchWithAuth("/api/v1/sessions");
  return r.json();
}

/** GET /api/v1/sessions/{id} — own session by id.
 *
 * 404s when the caller isn't the owner (assert_owner in PR-A masks
 * other clinicians' rows as not-found rather than 403).
 */
export async function getSession(sessionId: string): Promise<SessionRow> {
  const r = await fetchWithAuth(`/api/v1/sessions/${sessionId}`);
  return r.json();
}

/** PATCH /api/v1/sessions/{id}/identifier — set or clear the patient
 * identifier. Empty / whitespace-only value clears the column (audit
 * row gets cleared=True). */
export async function setSessionExternalReferenceId(
  sessionId: string,
  identifier: string | null,
): Promise<SessionRow> {
  const r = await fetchWithAuth(`/api/v1/sessions/${sessionId}/identifier`, {
    method: "PATCH",
    body: JSON.stringify({ external_reference_id: identifier }),
  });
  return r.json();
}

/** GET /api/v1/me/patients/{identifier}/sessions — prior encounters
 * with the same identifier, scoped to the caller. Empty list when
 * none match. Used by the review screen's 'previous encounters' link. */
export async function listMySessionsByPatientIdentifier(
  identifier: string,
): Promise<PatientSessionMatch[]> {
  const r = await fetchWithAuth(
    `/api/v1/me/patients/${encodeURIComponent(identifier)}/sessions`,
  );
  return r.json();
}

/* ─── Notes ──────────────────────────────────────────────────────────────── */

/** GET /api/v1/notes/{id}/full — latest note (may include Stage 2). */
export async function getFullNote(sessionId: string): Promise<Note> {
  const r = await fetchWithAuth(`/api/v1/notes/${sessionId}/full`);
  return r.json();
}

/** GET /api/v1/notes/{id}/detail — full review-pane payload: note +
 * per-claim citations + conflict summary + export readiness. */
export async function getNoteDetail(sessionId: string): Promise<NoteDetail> {
  const r = await fetchWithAuth(`/api/v1/notes/${sessionId}/detail`);
  return r.json();
}

/** POST /api/v1/notes/{id}/approve-stage1 — transitions to PROCESSING_STAGE2. */
export async function approveStage1(sessionId: string): Promise<void> {
  await fetchWithAuth(`/api/v1/notes/${sessionId}/approve-stage1`, {
    method: "POST",
  });
}

/** POST /api/v1/notes/{id}/approve — final approval, transitions to REVIEW_COMPLETE.
 *
 * iOS calls approve-stage1 then approve sequentially as a single
 * user-visible action. The web mirrors that behaviour via approveAll()
 * below — caller almost never needs to invoke this directly.
 */
export async function approveFinal(sessionId: string): Promise<void> {
  await fetchWithAuth(`/api/v1/notes/${sessionId}/approve`, {
    method: "POST",
  });
}

/** Single-tap approve from the web UI. Mirrors the iOS NoteReviewView
 * pattern of firing /approve-stage1 then /approve back-to-back; the
 * second call 409s if the first already drove the session past
 * AWAITING_REVIEW, which we tolerate (state has already advanced). */
export async function approveAll(sessionId: string): Promise<void> {
  try {
    await approveStage1(sessionId);
  } catch (e) {
    // If the session was already past stage1 (e.g. tab was open before
    // the user approved on iOS) the call 409s — fine, fall through to
    // the final approve which is what we really care about.
    const msg = e instanceof Error ? e.message : "";
    if (!msg.includes("409")) throw e;
  }
  await approveFinal(sessionId);
}

/** PATCH /api/v1/notes/{id}/edit — physician edits. Body is a dict
 * mapping section_id to new claim text. */
export async function editNote(
  sessionId: string,
  edits: Record<string, string>,
): Promise<Note> {
  const r = await fetchWithAuth(`/api/v1/notes/${sessionId}/edit`, {
    method: "PATCH",
    body: JSON.stringify({ edits }),
  });
  return r.json();
}

/** PATCH /api/v1/notes/{id}/conflicts/{claimId}/resolve.
 * action: 'accept_visual' | 'reject_visual' | 'edit' (the last carries resolution_text). */
export async function resolveConflict(
  sessionId: string,
  claimId: string,
  action: "accept_visual" | "reject_visual" | "edit",
  resolutionText?: string,
): Promise<Note> {
  const body: Record<string, string> = { action };
  if (action === "edit" && resolutionText) body.resolution_text = resolutionText;
  const r = await fetchWithAuth(
    `/api/v1/notes/${sessionId}/conflicts/${claimId}/resolve`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
  return r.json();
}

/** GET /api/v1/notes/{id}/stage2-status — poll fallback for the
 * WebSocket-based progress flow. */
export async function getStage2Status(sessionId: string): Promise<Stage2Status> {
  const r = await fetchWithAuth(`/api/v1/notes/${sessionId}/stage2-status`);
  return r.json();
}

/* ─── Single-session export ──────────────────────────────────────────────── */

/** POST /api/v1/notes/{id}/export — server-side DOCX render. Returns
 * the raw blob so callers can trigger a browser download. */
export async function exportNote(sessionId: string): Promise<Blob> {
  const r = await fetchWithAuth(`/api/v1/notes/${sessionId}/export`, {
    method: "POST",
  });
  return r.blob();
}

/* ─── Patient summary (after-visit) ──────────────────────────────────────── */

/** GET /me/notes/{id}/patient-summary — null when none generated yet. */
export async function getMyPatientSummary(
  sessionId: string,
): Promise<PatientSummary | null> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/patient-summary`,
  );
  const data = await r.json();
  // Backend returns `null` literally when no summary exists; preserve that.
  return data && typeof data === "object" ? (data as PatientSummary) : null;
}

/** POST /me/notes/{id}/patient-summary — fresh LLM generation. 409 when
 * the note isn't approved yet; caller surfaces the message. */
export async function generateMyPatientSummary(
  sessionId: string,
): Promise<PatientSummary> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/patient-summary`,
    { method: "POST" },
  );
  return r.json();
}

/** PATCH /me/notes/{id}/patient-summary — save the physician's edit
 * as a new version. */
export async function editMyPatientSummary(
  sessionId: string,
  body: string,
): Promise<PatientSummary> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/patient-summary`,
    { method: "PATCH", body: JSON.stringify({ body }) },
  );
  return r.json();
}

/* ─── Macros (physician phrase shortcuts) ────────────────────────────────── */

export async function listMyMacros(
  specialty?: string,
): Promise<PhysicianMacro[]> {
  const q = specialty ? `?specialty=${encodeURIComponent(specialty)}` : "";
  const r = await fetchWithAuth(`/api/v1/me/macros${q}`);
  return r.json();
}

export async function createMyMacro(
  body: PhysicianMacroCreate,
): Promise<PhysicianMacro> {
  const r = await fetchWithAuth("/api/v1/me/macros", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return r.json();
}

export async function updateMyMacro(
  macroId: string,
  body: PhysicianMacroUpdate,
): Promise<PhysicianMacro> {
  const r = await fetchWithAuth(`/api/v1/me/macros/${macroId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return r.json();
}

export async function deleteMyMacro(macroId: string): Promise<void> {
  await fetchWithAuth(`/api/v1/me/macros/${macroId}`, { method: "DELETE" });
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
