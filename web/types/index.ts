/* ─── Roles ──────────────────────────────────────────────────────────────── */

export type UserRole =
  | "CLINICIAN"
  | "EVAL_TEAM"
  | "COMPLIANCE_OFFICER"
  | "CLINICAL_ADMIN"
  | "ADMIN";

/* ─── Users ──────────────────────────────────────────────────────────────── */

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  voice_enrolled: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface CreateUserPayload {
  email: string;
  full_name: string;
  role: UserRole;
  password: string;
}

export interface UpdateUserPayload {
  full_name?: string;
  role?: UserRole;
  is_active?: boolean;
}

/* ─── Audit ──────────────────────────────────────────────────────────────── */

export interface AuditEvent {
  session_id: string;
  event_timestamp: string;
  event_type: string;
  event_id?: string;
  actor_id?: string;
  actor_role?: UserRole;
  details: Record<string, unknown>;
}

export interface AuditFilters {
  clinician_id?: string;
  date_from?: string;
  date_to?: string;
  event_type?: string;
  session_id?: string;
  page?: number;
  page_size?: number;
}

/* ─── Sessions ───────────────────────────────────────────────────────────── */

export type SessionState =
  | "IDLE"
  | "CONSENT_PENDING"
  | "RECORDING"
  | "PAUSED"
  | "PROCESSING_STAGE1"
  | "AWAITING_REVIEW"
  | "PROCESSING_STAGE2"
  | "REVIEW_COMPLETE"
  | "EXPORTED"
  | "PURGED"
  | "FAILED";

export interface Session {
  id: string;
  clinician_id: string;
  clinician_name: string;
  specialty: string;
  state: SessionState;
  completeness_score: number;
  sections_populated: number;
  sections_required: number;
  provider_used: string;
  /** PHI patient identifier (MRN, encounter id, free text). Encrypted
   * at rest server-side; decrypted only for the owner of the row.
   * Absent when not set or when the caller isn't the owner. */
  external_reference_id?: string | null;
  created_at: string;
  updated_at: string;
}

/** One match from GET /api/v1/me/patients/{identifier}/sessions —
 * a slim shape for rendering 'Previous encounters with this patient'. */
export interface PatientSessionMatch {
  session_id: string;
  specialty: string;
  state: SessionState;
  created_at: string;
}

/** Per-physician text shortcut → expansion. Typing the shortcut (e.g.
 * "/ros-cv") in a note edit field expands to the body. Owner-scoped
 * server-side; the client never sees another clinician's macros. */
export interface PhysicianMacro {
  id: string;
  shortcut: string;
  body: string;
  /** Optional specialty scope. Null = available everywhere. */
  specialty?: string | null;
  is_shared: boolean;
  created_at: string;
  updated_at: string;
}

export interface PhysicianMacroCreate {
  shortcut: string;
  body: string;
  specialty?: string | null;
}

export interface PhysicianMacroUpdate {
  shortcut?: string;
  body?: string;
  specialty?: string | null;
  /** Flip to true to clear the specialty scope (specialty=null
   * already means 'no change' in patch semantics). */
  clear_specialty?: boolean;
}

/** Plain-language after-visit summary for the patient. Generated
 * from the approved note by the LLM; physician can edit. */
export interface PatientSummary {
  id: string;
  session_id: string;
  version: number;
  body: string;
  generated_by_provider: string;
  physician_edited: boolean;
  created_at: string;
  updated_at: string;
}

export type NoteSectionStatus =
  | "populated"
  | "pending_video"
  | "not_captured"
  | "processing_failed";

export interface SectionDetail {
  id: string;
  title: string;
  required: boolean;
  status: NoteSectionStatus;
  claims_count: number;
  // Keys are NoteClaim source_type values ("transcript", "visual",
  // "screen", "physician_edit"). Backend may return additional keys
  // for unknown source types, so keep this open.
  claim_sources: Record<string, number>;
}

export interface SessionDetail extends Session {
  note_version: number;
  note_stage: number;
  is_approved: boolean;
  sections: SectionDetail[];
}

export interface SessionFilters {
  clinician_id?: string;
  specialty?: string;
  state?: SessionState;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

/* ─── Notes ──────────────────────────────────────────────────────────────── */

export interface Claim {
  id: string;
  text: string;
  source_type: "transcript" | "visual" | "screen" | "physician_edit";
  source_id: string;
  source_quote: string;
  physician_edited?: boolean;
  original_text?: string | null;
}

export type SectionStatus =
  | "populated"
  | "not_captured"
  | "pending_video"
  | "processing_failed";

export interface NoteSection {
  id: string;
  title: string;
  status: SectionStatus;
  claims: Claim[];
}

/** Slim, count-only summary of the prior-encounter context Stage 1
 * note-gen consumed for this note (#61, full slice).
 *
 * Mirrors the backend `PriorContextUsedSummary` Pydantic type
 * (`backend/app/core/types.py`) and the iOS `PriorContextUsed`
 * struct. Carries NO PHI — only:
 *   - `encounters_referenced`: integer count of prior visits the LLM
 *     actually saw (drives the badge's visibility gate).
 *   - `last_encounter_date`: ISO-8601 calendar date of the most
 *     recent prior visit, or null when the lookup found nothing.
 *
 * Older payloads (pre-#61 backends) omit this field entirely; the
 * type is optional all the way down so the existing review UI
 * renders unchanged.
 */
export interface PriorContextUsed {
  encounters_referenced: number;
  last_encounter_date: string | null;
}

export interface Note {
  session_id: string;
  stage: number;
  version: number;
  provider_used: string;
  specialty: string;
  completeness_score: number;
  sections: NoteSection[];
  created_at: string;
  /** Stage 1 actually consumed prior encounters into the LLM prompt
   * for this note (#61). null for cold-start sessions (no identifier)
   * and pre-#61 backends. Read by `NoteContextBadge` to gate the
   * "Context: N prior visits" affordance. */
  prior_context_used?: PriorContextUsed | null;
}

/** Per-claim citation expansion for the note review pane. Only the
 * fields relevant to the claim's source_type are populated; others are
 * left undefined. */
export interface CitationExpansion {
  source_type: string;
  source_id: string;
  /** transcript anchor */
  transcript_text?: string | null;
  transcript_speaker?: string | null;
  transcript_start_ms?: number | null;
  transcript_end_ms?: number | null;
  /** visual / screen anchor — both reference a frame_id */
  frame_timestamp_ms?: number | null;
  frame_s3_key?: string | null;
  /** physician edit */
  original_text?: string | null;
  /** ── Dual-mode visual evidence (P1-6-FU backend, P1-FU-WEB-CLIPS UI) ──
   *  Populated for visual citations only:
   *    - frame-kind  (source_id starts `frame_`): evidence_kind="frame",
   *      duration_ms=null, clip_url=null.
   *    - clip-kind   (source_id ends `_clip`):    evidence_kind="clip",
   *      duration_ms=<encoded window in ms>, clip_url=<signed S3 URL>.
   *  All three are null/undefined for non-visual citations so older
   *  responses (and non-visual rows) decode unchanged — additive shape.
   */
  evidence_kind?: "frame" | "clip" | null;
  duration_ms?: number | null;
  clip_url?: string | null;
}

export interface ConflictState {
  has_unresolved: boolean;
  unresolved_count: number;
  unresolved_section_ids: string[];
  unresolved_claim_ids: string[];
}

export interface ExportMetadata {
  latest_version: number;
  is_approved: boolean;
  can_export: boolean;
  session_state: SessionState;
  external_reference_id?: string | null;
}

/** Full note + citation + conflict + export state for the review UI. */
export interface NoteDetail {
  note: Note;
  citations: Record<string, CitationExpansion>;
  conflict_state: ConflictState;
  export_metadata: ExportMetadata;
}

export type Stage2JobStatus =
  | "no_job"
  | "pending"
  | "running"
  | "completed"
  | "failed";

export interface Stage2Status {
  session_id: string;
  job_id?: string | null;
  status: Stage2JobStatus;
  started_at?: string | null;
  completed_at?: string | null;
  new_note_version?: number | null;
  frames_processed: number;
  error_message?: string | null;
}

/** Incremental progress event delivered by the /ws/notes/{id} channel.
 * Backend emits ~every 10% of frames during Stage 2. */
export interface Stage2ProgressEvent {
  frames_processed: number;
  frames_total: number;
}

/** WebSocket envelope on /ws/notes/{session_id}. The discriminator is
 * the `event` field; additional payload depends on the event type. */
export type NoteWebSocketMessage =
  | { event: "stage1_delivered"; session_id: string; note: Note }
  | { event: "stage2_delivered"; session_id: string; note: Note }
  | {
      event: "stage2_progress";
      session_id: string;
      frames_processed: number;
      frames_total: number;
    };

/* ─── PHI Masking ────────────────────────────────────────────────────────── */

export interface MaskingSessionResult {
  session_id: string;
  clinician_name: string;
  date: string;
  total_frames: number;
  masked_frames: number;
  failed_frames: number;
  skipped_frames: number;
  uploaded_frames: number;
  pass: boolean;
}

export interface MaskingReport {
  total_sessions: number;
  pass_count: number;
  fail_count: number;
  pass_rate: number;
  sessions: MaskingSessionResult[];
}

/* ─── Provider Config ────────────────────────────────────────────────────── */

export interface ProviderConfig {
  providers: {
    transcription: string;
    note_generation: string;
    vision: string;
  };
  model_params: {
    note_generation: { temperature: number; max_tokens: number };
    vision: {
      temperature: number;
      max_tokens: number;
      confidence_threshold: string;
    };
  };
  pipeline: {
    stage1_skip_window_seconds: number;
    frame_window_clinic_ms: number;
    frame_window_procedural_ms: number;
    screen_capture_fps: number;
    video_capture_fps: number;
  };
  feature_flags: {
    screen_capture_enabled: boolean;
    note_versioning_enabled: boolean;
    session_pause_resume_enabled: boolean;
    per_session_provider_override: boolean;
  };
}

export interface ConfigChangeEvent {
  id: string;
  changed_by: string;
  changed_at: string;
  previous_config: Partial<ProviderConfig>;
  new_config: Partial<ProviderConfig>;
  appconfig_version: number;
}

/* ─── Feature Flags ──────────────────────────────────────────────────────── */
// Mirrors backend/app/api/v1/admin/feature_flags.py:FeatureFlagsResponse.
// The four `*_card_enabled` flags gate the post-pilot cards on the iOS
// note-review screen (lane-full/card-visibility-flags). ADMIN-only —
// the Feature Flags page in the portal is the only writer.
export interface FeatureFlags {
  screen_capture_enabled: boolean;
  note_versioning_enabled: boolean;
  session_pause_resume_enabled: boolean;
  per_session_provider_override: boolean;
  meta_wearables_enabled: boolean;
  per_session_visual_evidence_mode_override: boolean;
  orders_card_enabled: boolean;
  coding_card_enabled: boolean;
  patient_summary_card_enabled: boolean;
  emr_writeback_card_enabled: boolean;
}

export interface UpdateFeatureFlagsResponse {
  feature_flags: FeatureFlags;
  appconfig_version: number;
  changed_fields: string[];
}

/* ─── Pilot Metrics ──────────────────────────────────────────────────────── */

export interface PilotMetric {
  session_id: string;
  clinician_id: string;
  clinician_name: string;
  specialty: string;
  template_section_completeness: number;
  citation_traceability_rate: number;
  physician_edit_rate: number;
  conflict_rate: number;
  low_confidence_frame_rate: number;
  stage1_latency_ms: number;
  stage2_latency_ms: number;
  session_completeness: boolean;
  created_at: string;
}

export interface MetricFilters {
  clinician_id?: string;
  specialty?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export interface MetricTimeseriesBucket {
  date: string; // ISO date, e.g. "2026-05-26"
  session_count: number;
  template_section_completeness: number | null;
  citation_traceability_rate: number | null;
  physician_edit_rate: number | null;
  conflict_rate: number | null;
  low_confidence_frame_rate: number | null;
  stage1_latency_ms: number | null;
  stage2_latency_ms: number | null;
  session_completeness: number | null;
}

export interface MetricTimeseriesResponse {
  from: string;
  to: string;
  bucket: "day"; // forward-compat: backend may add "hour" / "week"
  buckets: MetricTimeseriesBucket[];
}

export interface MetricTimeseriesFilters {
  from?: string;
  to?: string;
  specialty?: string;
  clinician_id?: string;
}

/* ─── Eval ───────────────────────────────────────────────────────────────── */

export interface EvalSession {
  id: string;
  session_id: string;
  clinician_name: string;
  specialty: string;
  transcript_masked: boolean;
  frames_masked: boolean;
  note_version: number;
  scored: boolean;
  scores: EvalScore | null;
  created_at: string;
  // EVAL-3 assignment columns. assigned_to is the assignee's email
  // (denormalized for cheap rendering); null when no open assignment.
  assigned_to?: string | null;
  assignment_completed_at?: string | null;
}

export interface EvalAssignee {
  user_id: string;
  email: string;
  full_name: string;
  role: UserRole;
}

export interface EvalScore {
  transcript_accuracy: number;
  citation_correctness: number;
  descriptive_mode_compliance: number;
  overall: number;
  notes: string;
  scored_by: string;
  scored_at: string;
  // Spec-aligned fields (slice 2). Nullable on the wire — older scores
  // submitted before the migration land here with null values.
  descriptive_mode_pass?: boolean | null;
  soap_section_scores?: Record<string, number> | null;
  hallucination_count?: number | null;
  discrepancies?: string[] | null;
}

export interface EvalScoreSubmission {
  transcript_accuracy: number;
  citation_correctness: number;
  descriptive_mode_compliance: number;
  notes: string;
  // Spec-aligned (slice 2) — all optional.
  descriptive_mode_pass?: boolean | null;
  soap_section_scores?: Record<string, number> | null;
  hallucination_count?: number | null;
  discrepancies?: string[] | null;
}

export interface EvalTranscriptSegment {
  id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  is_visual_trigger: boolean;
  trigger_type: string | null;
}

export interface EvalSessionDetail extends EvalSession {
  transcript_provider: string;
  transcript_segments: EvalTranscriptSegment[];
  note_specialty: string;
  note_stage: number;
  note_completeness_score: number;
  // Note sections come straight from the persisted note JSON — each
  // section has id, title, status, claims[]. The Claim shape (see above)
  // anchors back to transcript segments / frame ids via source_id.
  note_sections: NoteSection[];
}

/* ─── API Responses ──────────────────────────────────────────────────────── */

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  user_id: string;
  full_name: string;
}

export interface CurrentUser {
  user_id: string;
  email: string;
  full_name: string;
  role: UserRole;
}

/* ─── Clinician Portal ───────────────────────────────────────────────────── */

/** Mirrors `backend.app.api.v1.profile.PhysicianProfileResponse`.
 *
 * `practice_type` is stored as a comma-joined string on the wire
 * (multiple select on iOS), so the web treats it as a Set<string>
 * locally and serialises with `.join(",")` on save.
 */
/** One context row under a visit type (#313/W1). Mirrors the backend
 * `VisitTypeContext` (`backend/app/api/v1/profile.py`) and the iOS
 * struct.
 *
 * A "context" is a clinician-authored sub-mode of a visit type — e.g.
 * under "new_patient", contexts "Left knee" or "Revision" — each
 * optionally pinned to a built-in specialty template.
 *
 *  - `id` is server-assigned (`ctx_<8 hex>`); the client mints a
 *    well-formed one for new rows so React keys stay stable and the
 *    backend preserves it on round-trip.
 *  - `template_key` is one of the 8 built-in template keys, or `null`
 *    to inherit the physician's specialty default.
 *  - `template_ref` (custom-template pointer) is ALWAYS `null` in
 *    phase 1 — custom templates land in phase 2 (#318).
 */
export interface VisitTypeContext {
  id: string;
  label: string;
  template_key: string | null;
  template_ref: string | null;
}

export interface PhysicianProfile {
  clinician_id: string;
  display_name: string;
  practice_type: string | null;
  primary_specialty: string;
  preferred_templates: string[];
  consultation_types: string[];
  /** Visit-type → context list map (#313/W1). Keyed by a
   * `consultation_types` entry (default key or custom label). Keys not
   * in `consultation_types` are pruned server-side on the next PUT.
   * Defaults to `{}` on profiles that never set a context. */
  contexts_per_visit_type: Record<string, VisitTypeContext[]>;
  allied_health_team: AlliedHealthMember[];
  output_language: "en" | "fr";
  /** Portal/iOS chrome theme (#189). "system" follows OS. */
  ui_theme: "system" | "light" | "dark";
  /** Portal/iOS chrome language. Orthogonal to output_language. */
  ui_language: "en" | "fr";
  auto_upload: boolean;
  retention_days: number;
  consent_reprompt: "every_session" | "daily" | "weekly";
}

export interface AlliedHealthMember {
  role: string;
  display_name: string;
}

export interface PhysicianProfileUpdate {
  display_name?: string;
  practice_type?: string | null;
  primary_specialty?: string;
  preferred_templates?: string[];
  consultation_types?: string[];
  /** Visit-type → context list map (#313/W1). Send alongside
   * `consultation_types` so the server can prune orphan keys in the
   * same request. Omit to leave the stored map untouched. */
  contexts_per_visit_type?: Record<string, VisitTypeContext[]>;
  allied_health_team?: AlliedHealthMember[];
  output_language?: "en" | "fr";
  /** Portal/iOS chrome theme (#189). Distinct from output_language —
   *  output_language controls the note content; ui_theme + ui_language
   *  control the chrome. */
  ui_theme?: "system" | "light" | "dark";
  /** Portal/iOS chrome language. Locked to en/fr today; widen the union
   *  when the supported locales grow (matches backend's enum). */
  ui_language?: "en" | "fr";
  auto_upload?: boolean;
  retention_days?: number;
  consent_reprompt?: "every_session" | "daily" | "weekly";
}

/** A specialty template (built-in or custom). Used for the
 * `preferred_templates` picker and the template library list. */
export interface TemplateSection {
  id: string;
  title: string;
  required: boolean;
  visual_trigger_keywords: string[];
  description: string;
}

export interface TemplateDefinition {
  key: string;
  display_name: string;
  version: string;
  sections: TemplateSection[];
}

/** Mirrors backend `/me/custom-templates` response. */
export interface CustomTemplate {
  id: string;
  key: string;
  display_name: string;
  version: string;
  owner_id: string;
  is_shared: boolean;
  template: TemplateDefinition;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/** Mirrors backend `/me/template-authoring` response. */
export interface TemplateAuthoringSession {
  id: string;
  status: "active" | "completed" | "abandoned";
  messages: ChatMessage[];
  draft_template: TemplateDefinition | null;
  assistant_message: string | null;
}

/** Structured order extracted from an approved note. The four kinds
 * each have a different `details` shape — narrow via the `kind`
 * discriminator. */
export type NoteOrderKind = "imaging" | "lab" | "referral" | "prescription";
export type NoteOrderStatus =
  | "draft"
  | "confirmed"
  | "sent"
  | "cancelled";

export interface NoteOrder {
  id: string;
  session_id: string;
  kind: NoteOrderKind;
  details: Record<string, unknown>;
  status: NoteOrderStatus;
  source_claim_ids: string[];
  /** Drug catalog validation flag (#58 follow-up).
   *
   *  true  — recognized in our curated drug catalog (generic or brand)
   *  false — checked and NOT in catalog; UI surfaces "verify before
   *          prescribing" amber warning
   *  null  — non-prescription order (imaging/lab/referral don't have
   *          a drug field) OR legacy row from before validation
   *
   *  The null state collapses two cases that the UI doesn't need to
   *  distinguish: both render as "no badge". */
  drug_validated?: boolean | null;
  /** Catalog version in effect when `drug_validated` was set. NULL
   *  for non-prescription kinds AND for rows from before the column
   *  existed. Audit-story field — the UI doesn't surface it but
   *  consumers (admin tools, eval team) can read it from the response. */
  catalog_version?: string | null;
  physician_confirmed_at?: string | null;
  sent_at?: string | null;
  created_at: string;
  updated_at: string;
}

/** Coding & billing suggestion — #69 strategic separate-surface
 * inference. NEVER rendered into the clinical note; lives on its own
 * card with "Assistive — physician confirms" framing. */
export type CodingSystem = "em" | "icd10" | "cpt";
export type CodingConfidence = "low" | "medium" | "high";
export type CodingSuggestionStatus =
  | "suggested"
  | "confirmed"
  | "rejected"
  | "edited";

/** Live note preview during recording — #64.
 *
 * Streaming draft snapshots generated while the encounter is still
 * happening. `stage` is always 0, `is_draft` always true — any
 * consumer that confuses this with a Stage 1 / Stage 2 note has a
 * bug. The `sections` shape matches Note.sections but the rows live
 * in their own table, never in note_versions. */
export interface LivePreviewSection {
  id: string;
  title?: string;
  status: string;
  claims: Array<{
    id: string;
    text: string;
    source_type: string;
    source_id: string;
    source_quote?: string;
    physician_edited?: boolean;
    original_text?: string | null;
  }>;
}

export interface LivePreview {
  id: string;
  session_id: string;
  version: number;
  stage: 0;
  is_draft: true;
  sections: LivePreviewSection[];
  transcript_chars: number;
  completeness_score: number;
  provider_used: string;
  created_at: string;
}

/** EMR/EHR outbound write-back attempt — #57.
 *
 * One row per send attempt. Foundation supports `stub` connector
 * only; real backends (Oscar, Epic, generic FHIR) land in follow-ups.
 * `payload_fingerprint` is sha256 hex of the serialized payload —
 * never the payload itself. */
export type EmrWriteBackStatus = "queued" | "sending" | "sent" | "failed";

export interface EmrWriteBack {
  id: string;
  session_id: string;
  connector: string;
  status: EmrWriteBackStatus;
  external_id?: string | null;
  payload_fingerprint: string;
  error_reason?: string | null;
  attempt_count: number;
  sent_at?: string | null;
  /** Auto-retry timestamp set by the orchestration on retryable
   * failures. Three-state semantics paired with `status`:
   *   - `null` + `status=failed` → terminal (no more retries budgeted)
   *   - datetime + `status=failed` → auto-retry queued for that time
   *   - `null` + `status=sent` → succeeded
   *
   * The UI surfaces "Will retry at HH:MM" when set and disables the
   * "Send again" CTA in favor of "Cancel retry & send fresh" — a
   * brand-new send creates a NEW row; this scheduled retry mutates
   * the existing one. */
  scheduled_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface EmrConnectorsCatalog {
  available: string[];
  default: string;
}

export interface CodingSuggestion {
  id: string;
  session_id: string;
  code_system: CodingSystem;
  code: string;
  description: string;
  justification: string;
  source_claim_ids: string[];
  confidence: CodingConfidence;
  status: CodingSuggestionStatus;
  /** Catalog validation flag (#69 follow-up).
   *
   *  true  — in our curated billing catalog; silent success
   *  false — checked and NOT in catalog; UI surfaces "verify before
   *          billing" amber warning
   *  null  — legacy row from before validation existed; UI stays neutral
   *
   *  The three states are distinct in the UI; do NOT collapse to a
   *  boolean. */
  code_validated?: boolean | null;
  /** Catalog version in effect when `code_validated` was set. NULL
   *  for rows that predate the version column. Audit-story field —
   *  UI doesn't currently surface it but the type round-trips it. */
  catalog_version?: string | null;
  physician_action_at?: string | null;
  created_at: string;
  updated_at: string;
}

/* ─── AI Prompts Transparency (AI-PROMPTS-A + B) ─────────────────────────── */

export type PromptCategory = "note" | "vision" | "extraction" | "preview";

/**
 * One LLM system prompt the encounter-analysis pipeline uses,
 * surfaced on /portal/prompts.
 *
 * Phase A: read-only catalog. Phase B (replacement semantics) added
 * per-physician REPLACEMENT user prompts:
 *
 *  - `system_prompt` is the registry default — the FALLBACK used when
 *    the calling physician has not saved their own prompt.
 *  - `system_prompt_is_fallback` is always `true`; the portal uses it
 *    to render the system prompt with muted styling so the physician
 *    sees clearly that it's a fallback, not the active default.
 *  - `user_prompt_text` is the calling physician's saved REPLACEMENT
 *    prompt (or `null` when they haven't saved one).
 *  - `is_overridden` is the convenience flag (`user_prompt_text != null`).
 *  - `active_prompt` is the exact text the LLM would receive for this
 *    physician's next call: `user_prompt_text` when set,
 *    `system_prompt` otherwise. There is NO concatenation — replacement
 *    semantics, not append-overlay.
 *
 * Clients should render `active_prompt` when they want the "what the
 * AI is actually told" view, and `system_prompt` when they
 * specifically want the system default (the fallback).
 */
export interface AIPrompt {
  id: string;
  name: string;
  purpose: string;
  category: PromptCategory;
  runs_when: string;
  provider_field: string;
  system_prompt: string;
  system_prompt_is_fallback: boolean;
  schema_note: string | null;
  user_prompt_text: string | null;
  is_overridden: boolean;
  active_prompt: string;
}

/**
 * Phase B PATCH error shape (replacement semantics). The server
 * returns 400 with this structure when a saved user prompt fails
 * structural validation. The frontend uses `code` to localise the
 * message, `matched_phrase` to highlight which banned phrase tripped
 * the gate, and `missing_anchor_group` to render the right localised
 * hint when the descriptive-mode anchor check fails (0 → "describe /
 * document / record"; 1 → "do not interpret / diagnose").
 */
export interface PromptUserPromptValidationError {
  code:
    | "empty"
    | "too_long"
    | "banned_phrase"
    | "missing_descriptive_anchor";
  message: string;
  matched_phrase: string | null;
  missing_anchor_group: number | null;
}
