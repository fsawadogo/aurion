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

export interface Note {
  session_id: string;
  stage: number;
  version: number;
  provider_used: string;
  specialty: string;
  completeness_score: number;
  sections: NoteSection[];
  created_at: string;
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
export interface PhysicianProfile {
  clinician_id: string;
  display_name: string;
  practice_type: string | null;
  primary_specialty: string;
  preferred_templates: string[];
  consultation_types: string[];
  allied_health_team: AlliedHealthMember[];
  output_language: "en" | "fr";
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
  allied_health_team?: AlliedHealthMember[];
  output_language?: "en" | "fr";
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
  physician_action_at?: string | null;
  created_at: string;
  updated_at: string;
}
