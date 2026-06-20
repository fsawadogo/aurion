/**
 * Clinician-portal API client.
 *
 * Extends `web/lib/api.ts` for the `/api/v1/me/*` endpoint family
 * shipped in backend PR-B. Shares the `fetchWithAuth` wrapper (so the
 * bearer-token attach + silent-refresh + 401-retry behaviour is identical
 * to the admin surface) but groups portal-only call sites here to keep
 * `api.ts` from sprawling.
 *
 * Pure typed wrappers around the JSON responses; no caching, no
 * client-side state. Components hold their own `useState` + call the
 * functions in `useEffect`.
 */

import { fetchWithAuth } from "@/lib/api";
import type {
  AudioReplayUrlResponse,
  AuditFilters,
  CodingSuggestion,
  CustomTemplate,
  EmrConnectorsCatalog,
  EmrWriteBack,
  LivePreview,
  Note,
  NoteDetail,
  NoteOrder,
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
 *
 * #313/W1: `contexts_per_visit_type` round-trips here. Send it together
 * with `consultation_types` so the server prunes contexts whose visit
 * type the same request dropped. Context labels can be PHI — they ride
 * the PUT body only, never a query string or client log.
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

/* ─── Audio replay (own session, #338) ───────────────────────────────────── */

/** GET /api/v1/notes/{id}/audio-replay-url — mint a short-lived presigned
 * URL the physician can use to REPLAY the raw audio of their own session in
 * the browser. Ownership-gated server-side (404 when the caller doesn't own
 * the session), so it lives here beside the other `/notes/*` own-session
 * calls rather than in the admin client.
 *
 * Outcomes the caller distinguishes:
 *   - 200 with `audio_url` set  → playable presigned URL (≈1h TTL).
 *   - 200 with `audio_url` null → no audio retained / transient mint error.
 *   - 403 → `media_review_retention_enabled` feature flag is OFF.
 *   - 409 → session isn't in a state that retains audio (only
 *           AWAITING_REVIEW / PROCESSING_STAGE2 / REVIEW_COMPLETE).
 *   - 404 → caller doesn't own the session.
 * The 4xx cases surface through fetchWithAuth's thrown `API {status}: …`
 * Error (same convention as every other call in this file); the caller maps
 * the status to a localized message.
 *
 * SIDE EFFECT: each successful call mints a URL AND writes an
 * EVIDENCE_REPLAYED audit row server-side. Call this ONLY on an explicit
 * user action (a button click), never automatically on page load, or the
 * audit trail fills with spurious replay rows. The returned URL is for
 * playback only — never offer it as a download and never log it.
 */
export async function getAudioReplayUrl(
  sessionId: string,
): Promise<AudioReplayUrlResponse> {
  const r = await fetchWithAuth(
    `/api/v1/notes/${encodeURIComponent(sessionId)}/audio-replay-url`,
  );
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

/* ─── Orders (extract from approved note) ────────────────────────────────── */

export async function listMySessionOrders(
  sessionId: string,
): Promise<NoteOrder[]> {
  const r = await fetchWithAuth(`/api/v1/me/notes/${sessionId}/orders`);
  return r.json();
}

export async function extractMySessionOrders(
  sessionId: string,
): Promise<NoteOrder[]> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/orders/extract`,
    { method: "POST" },
  );
  return r.json();
}

export async function confirmMySessionOrder(
  sessionId: string,
  orderId: string,
): Promise<NoteOrder> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/orders/${orderId}/confirm`,
    { method: "POST" },
  );
  return r.json();
}

export async function editMySessionOrder(
  sessionId: string,
  orderId: string,
  details: Record<string, unknown>,
): Promise<NoteOrder> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/orders/${orderId}`,
    { method: "PATCH", body: JSON.stringify({ details }) },
  );
  return r.json();
}

export async function cancelMySessionOrder(
  sessionId: string,
  orderId: string,
): Promise<NoteOrder> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/orders/${orderId}`,
    { method: "DELETE" },
  );
  return r.json();
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

/* ─── Coding & billing suggestions (#69 — separate inference surface) ────── */

/** GET /me/notes/{id}/coding-suggestions */
export async function listMyCodingSuggestions(
  sessionId: string,
): Promise<CodingSuggestion[]> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/coding-suggestions`,
  );
  return r.json();
}

/** POST /me/notes/{id}/coding-suggestions/extract — runs the LLM
 * suggestion engine against the approved note. 409 when not approved;
 * 502 when the upstream LLM fails. */
export async function extractMyCodingSuggestions(
  sessionId: string,
): Promise<CodingSuggestion[]> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/coding-suggestions/extract`,
    { method: "POST" },
  );
  return r.json();
}

export async function confirmMyCodingSuggestion(
  sessionId: string,
  suggestionId: string,
): Promise<CodingSuggestion> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/coding-suggestions/${suggestionId}/confirm`,
    { method: "POST" },
  );
  return r.json();
}

export async function rejectMyCodingSuggestion(
  sessionId: string,
  suggestionId: string,
): Promise<CodingSuggestion> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/coding-suggestions/${suggestionId}/reject`,
    { method: "POST" },
  );
  return r.json();
}

export async function editMyCodingSuggestion(
  sessionId: string,
  suggestionId: string,
  patch: { code: string; description: string },
): Promise<CodingSuggestion> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/coding-suggestions/${suggestionId}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
  return r.json();
}

/* ─── EMR write-back (#57) ────────────────────────────────────────────────── */

/** GET /me/emr/connectors — what's available in this deployment. */
export async function listEmrConnectors(): Promise<EmrConnectorsCatalog> {
  const r = await fetchWithAuth("/api/v1/me/emr/connectors");
  return r.json();
}

/** GET /me/notes/{id}/emr — full write-back history for the session. */
export async function listMySessionEmrWriteBacks(
  sessionId: string,
): Promise<EmrWriteBack[]> {
  const r = await fetchWithAuth(`/api/v1/me/notes/${sessionId}/emr`);
  return r.json();
}

/** POST /me/notes/{id}/emr/send — kick off a write-back attempt.
 *
 * The returned row may be in any terminal state (sent or failed) — the
 * orchestration runs the connector synchronously today. Connector
 * errors land as `status=failed` rows (NOT HTTP errors); only auth /
 * not-approved / unknown-connector conditions surface as HTTP errors. */
export async function sendMySessionToEmr(
  sessionId: string,
  connector?: string,
): Promise<EmrWriteBack> {
  const r = await fetchWithAuth(
    `/api/v1/me/notes/${sessionId}/emr/send`,
    {
      method: "POST",
      body: JSON.stringify({ connector: connector ?? null }),
    },
  );
  return r.json();
}

/* ─── Live note preview (#64) ────────────────────────────────────────────── */

/** GET /me/sessions/{id}/previews — full preview history (newest first). */
export async function listMySessionPreviews(
  sessionId: string,
): Promise<LivePreview[]> {
  const r = await fetchWithAuth(`/api/v1/me/sessions/${sessionId}/previews`);
  return r.json();
}

/** GET /me/sessions/{id}/preview — latest preview, or null. */
export async function getMyLatestSessionPreview(
  sessionId: string,
): Promise<LivePreview | null> {
  const r = await fetchWithAuth(`/api/v1/me/sessions/${sessionId}/preview`);
  const data = await r.json();
  return data && typeof data === "object" ? (data as LivePreview) : null;
}

/** POST /me/sessions/{id}/preview — generate a fresh draft snapshot.
 *
 * Pass the partial transcript text the device has captured so far.
 * The backend caps at 8KB (TAIL-preserving) and runs a draft-stage
 * LLM call — separate code path from canonical Stage 1, so a hung
 * preview never blocks recording-stop. */
export async function generateMySessionPreview(
  sessionId: string,
  payload: {
    partial_transcript: string;
    specialty_override?: string;
    output_language?: "en" | "fr";
  },
): Promise<LivePreview> {
  const r = await fetchWithAuth(
    `/api/v1/me/sessions/${sessionId}/preview`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  return r.json();
}

/* ─── AI Prompts Transparency (AI-PROMPTS-A + B) ─────────────────────────── */

/** GET /api/v1/me/prompts — catalog of LLM system prompts + caller's
 *  saved user prompts (replacement semantics).
 *
 * Backs the /portal/prompts Transparency page. Accessible to CLINICIAN
 * + ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER (the support roles get
 * system-default views — user prompts are per-physician personal
 * config). The response shape carries `user_prompt_text` /
 * `is_overridden` / `active_prompt` for the Phase B editor.
 */
export async function listMyPrompts(): Promise<import("@/types").AIPrompt[]> {
  const r = await fetchWithAuth("/api/v1/me/prompts");
  return r.json();
}

/** PATCH /api/v1/me/prompts/{promptId} — save or update the user prompt
 *  that REPLACES the system default for this physician's sessions.
 *
 * CLINICIAN-only on the server. Returns the updated `AIPrompt` shape
 * on success. On structural safety failure the server returns 400
 * with a `PromptUserPromptValidationError` in `detail`; callers should
 * pull `matched_phrase` (banned phrase) or `missing_anchor_group` (the
 * descriptive-mode anchor check) and surface a localised inline error.
 */
export async function patchMyUserPrompt(
  promptId: string,
  userPromptText: string,
): Promise<import("@/types").AIPrompt> {
  const r = await fetchWithAuth(
    `/api/v1/me/prompts/${encodeURIComponent(promptId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ user_prompt_text: userPromptText }),
    },
  );
  return r.json();
}

/** DELETE /api/v1/me/prompts/{promptId} — remove the saved user prompt
 *  so the system default takes over.
 *
 * Idempotent — returns 200 with the system-default `AIPrompt` shape
 * even when no user prompt exists.
 */
export async function deleteMyUserPrompt(
  promptId: string,
): Promise<import("@/types").AIPrompt> {
  const r = await fetchWithAuth(
    `/api/v1/me/prompts/${encodeURIComponent(promptId)}`,
    { method: "DELETE" },
  );
  return r.json();
}

/* ─── Security: MFA + active sessions (#163) ─────────────────────────────── */

/** Body of GET /api/v1/me/mfa/status. */
export interface MfaStatus {
  enrolled: boolean;
  last_verified_at: string | null;
}

/** Body of POST /api/v1/me/mfa/enroll. The plaintext `recovery_codes`
 * are returned ONCE — surface them in the modal, never refetch them.
 */
export interface MfaEnrollResponse {
  qr_uri: string;
  secret: string;
  recovery_codes: string[];
  setup_token: string;
}

/** One row of GET /api/v1/me/sessions. `is_current` is set on the row
 * that corresponds to the access token of the request issuing this
 * call, so the UI can label it as "this device" instead of "another
 * device that I should probably revoke". */
export interface ActiveSession {
  id: string;
  device_hint: string;
  ip_class: string;
  created_at: string;
  last_used_at: string | null;
  is_current: boolean;
}

/** GET /api/v1/me/mfa/status. Cheap probe — caller renders an MFA
 * status pill from this alone. */
export async function getMfaStatus(): Promise<MfaStatus> {
  const r = await fetchWithAuth("/api/v1/me/mfa/status");
  return r.json();
}

/** POST /api/v1/me/mfa/enroll. Returns the QR URI + plaintext recovery
 * codes + a 5-minute setup token. Nothing is persisted yet — the
 * caller MUST follow up with `verifyMfaEnroll` or the candidate
 * secret never reaches the DB.
 */
export async function enrollMfa(): Promise<MfaEnrollResponse> {
  const r = await fetchWithAuth("/api/v1/me/mfa/enroll", {
    method: "POST",
  });
  return r.json();
}

/** POST /api/v1/me/mfa/verify-enroll. Finalizes enrollment — server
 * persists the secret + hashed codes only after this call succeeds.
 */
export async function verifyMfaEnroll(
  setupToken: string,
  code: string,
): Promise<void> {
  await fetchWithAuth("/api/v1/me/mfa/verify-enroll", {
    method: "POST",
    body: JSON.stringify({ setup_token: setupToken, code }),
  });
}

/** DELETE /api/v1/me/mfa. Requires a fresh TOTP code to confirm the
 * caller is the authenticator-holder, not just a session hijacker.
 */
export async function disableMfa(currentCode: string): Promise<void> {
  await fetchWithAuth("/api/v1/me/mfa", {
    method: "DELETE",
    body: JSON.stringify({ current_code: currentCode }),
  });
}

/** GET /api/v1/me/sessions. Lists the caller's own active refresh-
 * token rows, most recently used first. */
export async function listSessions(): Promise<ActiveSession[]> {
  const r = await fetchWithAuth("/api/v1/me/sessions");
  return r.json();
}

/** POST /api/v1/me/sessions/{id}/revoke. Hard-kills the named row;
 * any access token still in flight from that refresh row will fail
 * on its next refresh attempt. */
export async function revokeSession(sessionId: string): Promise<void> {
  await fetchWithAuth(
    `/api/v1/me/sessions/${encodeURIComponent(sessionId)}/revoke`,
    { method: "POST" },
  );
}

/** POST /api/v1/me/sessions/revoke-all. Kills every active row for
 * the caller EXCEPT the one used to make this call. */
export async function revokeAllSessions(): Promise<void> {
  await fetchWithAuth("/api/v1/me/sessions/revoke-all", {
    method: "POST",
  });
}

// ── Video import (VID-05) ─────────────────────────────────────────────────
// Clinician uploads a recorded encounter video; the backend runs it through
// the same AI pipeline as a live session and produces a note reviewable in
// the existing note-review screen. The whole surface is gated behind the
// backend `video_import_enabled` flag (every call 404s while it is off).

export interface VideoImportCreateBody {
  specialty: string;
  encounter_type: string;
  output_language: string;
  /** Required-true: the clinician attests consent was obtained at the
   *  original recording (the import substitute for the live consent gate). */
  consent_attested: true;
  consent_method?: string;
}

export interface VideoImportCreated {
  session_id: string;
  job_id: string;
  /** Presigned S3 PUT URL — upload the raw video straight to S3 (no bearer). */
  upload_url: string;
  s3_key: string;
}

export interface VideoImportStatus {
  session_id: string;
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  session_state: string;
  frames_extracted: number;
  frames_masked: number;
  frames_dropped: number;
  raw_video_purged: boolean;
  new_note_version: number | null;
  error_message: string | null;
}

export async function createVideoImport(
  body: VideoImportCreateBody,
): Promise<VideoImportCreated> {
  const r = await fetchWithAuth("/api/v1/me/video-imports", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return r.json();
}

export async function processVideoImport(
  sessionId: string,
): Promise<VideoImportStatus> {
  const r = await fetchWithAuth(
    `/api/v1/me/video-imports/${sessionId}/process`,
    { method: "POST" },
  );
  return r.json();
}

export async function getVideoImportStatus(
  sessionId: string,
): Promise<VideoImportStatus> {
  const r = await fetchWithAuth(
    `/api/v1/me/video-imports/${sessionId}/status`,
  );
  return r.json();
}

/** Read-only portal feature flags for the current user (VID-10 nav gating). */
export async function getPortalFeatureFlags(): Promise<{
  video_import_enabled: boolean;
}> {
  const r = await fetchWithAuth("/api/v1/me/feature-flags");
  return r.json();
}

// ── Video import: multipart upload (VID-11) ───────────────────────────────
// For large videos a single PUT is fragile; these back a browser-driven S3
// multipart upload against the same job s3_key.

export interface VideoImportMultipartStart {
  upload_id: string;
  key: string;
  part_size: number;
  parts: { part_number: number; url: string }[];
}

export async function startVideoImportMultipart(
  sessionId: string,
  sizeBytes: number,
): Promise<VideoImportMultipartStart> {
  const r = await fetchWithAuth(
    `/api/v1/me/video-imports/${sessionId}/multipart/start`,
    { method: "POST", body: JSON.stringify({ size_bytes: sizeBytes }) },
  );
  return r.json();
}

export async function completeVideoImportMultipart(
  sessionId: string,
  uploadId: string,
  parts: { part_number: number; etag: string }[],
): Promise<{ status: string }> {
  const r = await fetchWithAuth(
    `/api/v1/me/video-imports/${sessionId}/multipart/complete`,
    { method: "POST", body: JSON.stringify({ upload_id: uploadId, parts }) },
  );
  return r.json();
}

export async function abortVideoImportMultipart(
  sessionId: string,
  uploadId: string,
): Promise<void> {
  await fetchWithAuth(
    `/api/v1/me/video-imports/${sessionId}/multipart/abort`,
    { method: "POST", body: JSON.stringify({ upload_id: uploadId }) },
  );
}
