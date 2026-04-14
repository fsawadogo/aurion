---
name: session-spec
description: >
  Load when working on session module, audit log, note versioning, or pilot metrics.
  Contains full state machine table with valid transitions and audit events, note
  versioning lifecycle with access controls, passive pilot metrics schema, and
  complete error handling per failure mode. Auto-invoked when editing modules/session/,
  modules/audit_log/, or modules/note_gen/ versioning logic.
user-invocable: true
---

# Aurion Session Specification

## Session State Machine — Full Table

Every transition requires an audit log entry. No exceptions. The record button is hard-blocked in IDLE and CONSENT_PENDING.

| State | Description | Valid Next States | Audit Event |
|---|---|---|---|
| `IDLE` | No active session. App waiting. | `CONSENT_PENDING` | `session_created` |
| `CONSENT_PENDING` | Consent form shown. Record button **disabled** until consent confirmed. | `RECORDING` | `consent_confirmed` |
| `RECORDING` | All three streams active. Audio buffering. Frames captured locally. | `PAUSED`, `PROCESSING_STAGE1` | `recording_started` |
| `PAUSED` | All streams suspended. Local data retained. Timer frozen. | `RECORDING`, `PROCESSING_STAGE1` | `session_paused` |
| `PROCESSING_STAGE1` | PHI masking complete. Audio uploaded. Whisper running. Note generation in progress. | `AWAITING_REVIEW` | `stage1_started` |
| `AWAITING_REVIEW` | Stage 1 draft delivered. 60-second review window active. | `PROCESSING_STAGE2` | `stage1_delivered` |
| `PROCESSING_STAGE2` | Frame extraction running async. Vision captioning. Conflict detection. | `REVIEW_COMPLETE` | `stage2_started` |
| `REVIEW_COMPLETE` | Full note delivered. Physician reviewing, editing, resolving conflicts. | `EXPORTED` | `full_note_delivered` |
| `EXPORTED` | Note approved. DOCX generated. Cleanup pipeline triggered. | `PURGED` | `note_exported` |
| `PURGED` | Raw audio and temp frames deleted. Eval frames migrated. Audit log finalized. | — terminal — | `session_purged` |

**PAUSED state:** physician interrupted mid-encounter can pause without losing the session. All streams suspend and restart cleanly on resume. Both pause and resume events logged with timestamps.

**Invalid transition rule:** any attempt to transition to a state not in Valid Next States must be rejected with an error logged to the audit trail. Never silently allow invalid transitions.

---

## Note Versioning

Every edit creates a new immutable version record. No version is ever deleted.

| Version Event | Trigger | Stored In | Accessible To |
|---|---|---|---|
| v1 — Stage 1 draft | Stage 1 note delivered automatically | RDS PostgreSQL | Clinician, Eval Team |
| v2+ — Physician edits | Created on each save during Stage 1 or full note review | RDS PostgreSQL | Clinician, Eval Team |
| vN — Stage 2 merged | Created when Stage 2 visual enrichment merged into note | RDS PostgreSQL | Clinician, Eval Team |
| vFinal — Approved | Created on physician approval — this version is exported | RDS PostgreSQL | Clinician, Compliance Officer |
| Full version history | All versions retained with timestamps and edit diffs | Audit log (DynamoDB) | Compliance Officer (read-only) |

**Implementation rules:**
- Clinician always sees and edits the latest version
- Previous versions are never shown in the review UI — retained silently in audit trail
- Compliance officer can query full history for any session via admin API
- Version diff (v1 → vFinal) is stored as the `physician_edit_rate` pilot metric per section

---

## Passive Pilot Metrics Schema

Stored in `pilot_metrics` PostgreSQL table. **No PHI.** Collected on 100% of sessions. Access: Eval Team and CTO only. Retained post-pilot for ML fine-tuning decisions.

```sql
CREATE TABLE pilot_metrics (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      UUID NOT NULL REFERENCES sessions(id),
  clinician_id    UUID NOT NULL,
  specialty       VARCHAR(50),
  created_at      TIMESTAMPTZ DEFAULT NOW(),

  -- Template quality
  template_section_completeness   FLOAT,   -- % required sections populated (0.0–1.0)
  citation_traceability_rate      FLOAT,   -- % claims with valid source_id

  -- Edit analysis
  physician_edit_rate_json        JSONB,   -- per-section diff: {"physical_exam": 0.3, ...}

  -- Vision pipeline
  conflict_rate                   FLOAT,   -- CONFLICTS / total frame citations
  low_confidence_frame_rate       FLOAT,   -- discarded / total frames processed

  -- Latency
  stage1_latency_ms               INTEGER, -- record_stop → stage1_delivered
  stage2_latency_ms               INTEGER, -- stage1_approved → full_note_delivered

  -- Collection integrity
  session_completeness            BOOLEAN  -- all 7 metrics above logged successfully
);
```

Metric collection rules:
- Write to `pilot_metrics` on session export — after all pipeline stages complete
- If any metric fails to collect, set `session_completeness = false` — do not fail the session
- Log a `metrics_collection_failed` audit event with the specific field that failed
- Null values are acceptable if a stage did not run (e.g. no frames processed)

---

## Audit Log Event Reference

The DynamoDB audit log is append-only. Every event must be written. The following events are required — this is not an exhaustive list, add events as needed.

| Event Type | When Written | Required Fields |
|---|---|---|
| `session_created` | Session object created | session_id, clinician_id, specialty, timestamp |
| `consent_confirmed` | Physician confirms patient consent | session_id, timestamp |
| `recording_started` | Record button pressed, streams activated | session_id, device_type, timestamp |
| `session_paused` | Physician pauses capture | session_id, timestamp |
| `session_resumed` | Physician resumes capture | session_id, timestamp |
| `masking_confirmed` | On-device masking complete, upload authorized | session_id, frames_masked, timestamp |
| `audio_uploaded` | Audio file written to S3 | session_id, s3_key, timestamp |
| `transcription_started` | Whisper job submitted | session_id, provider_used, timestamp |
| `transcription_complete` | Transcript received | session_id, provider_used, segment_count, timestamp |
| `phi_audit_complete` | Comprehend Medical scan complete | session_id, phi_detected (bool), timestamp |
| `stage1_started` | Note generation Phase 1 begins | session_id, provider_used, timestamp |
| `stage1_delivered` | Stage 1 draft sent to iOS via WebSocket | session_id, completeness_score, timestamp |
| `stage2_started` | Async vision pipeline begins | session_id, provider_used, timestamp |
| `vision_frame_processed` | Single frame captioned | session_id, frame_id, integration_status, provider_used, timestamp |
| `conflict_flagged` | CONFLICTS classification on a frame | session_id, frame_id, audio_anchor_id, timestamp |
| `full_note_delivered` | Stage 2 complete, full note sent | session_id, completeness_score, timestamp |
| `note_version_created` | Physician edit saved | session_id, version_number, timestamp |
| `conflict_resolved` | Physician resolves a CONFLICT | session_id, frame_id, resolution, timestamp |
| `note_approved` | Physician approves final note | session_id, version_number (vFinal), timestamp |
| `note_exported` | DOCX generated | session_id, export_format, timestamp |
| `audio_purged` | Raw audio deleted from S3 | session_id, s3_key, timestamp |
| `frames_purged` | Temp frames deleted | session_id, frame_count, timestamp |
| `eval_frames_migrated` | Masked eval frames moved to eval bucket | session_id, frame_count, timestamp |
| `session_purged` | All cleanup complete | session_id, timestamp |
| `provider_config_changed` | AppConfig provider update | changed_by, previous, new, appconfig_version, timestamp |
| `provider_fallback` | Registry fell back to alternate provider | session_id, attempted, fallback, reason, timestamp |
| `voice_enrollment_complete` | Physician voice profile created | clinician_id, device_id, timestamp (no embedding data) |
| `biometric_consent_confirmed` | Biometric consent accepted | clinician_id, timestamp |
| `voice_profile_deleted` | Physician deleted voice profile | clinician_id, timestamp |
| `metrics_collection_failed` | Pilot metric could not be logged | session_id, failed_field, error, timestamp |

**DynamoDB table key schema:**
- Partition key: `session_id` (String)
- Sort key: `event_timestamp` (String — ISO 8601 with millisecond precision)
- No GSI required for MVP — compliance officer queries full session by session_id

**Immutability enforcement:**
- Table policy: no `UpdateItem` or `DeleteItem` operations permitted on IAM role attached to ECS task
- Audit log module has no `update` or `delete` methods — write-only interface
