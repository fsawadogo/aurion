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
