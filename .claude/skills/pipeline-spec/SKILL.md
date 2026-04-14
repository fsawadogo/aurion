---
name: pipeline-spec
description: >
  Load when working on any pipeline module: vision, transcription, screen capture,
  note generation, conflict detection, or frame extraction. Contains full frame citation
  schema, ENRICHES/REPEATS/CONFLICTS classification rules, trigger classifier keyword
  lists, screen capture pipeline steps, and error handling table. Auto-invoked when
  editing modules/vision/, modules/screen/, modules/note_gen/, or modules/transcription/.
user-invocable: true
---

# Aurion Pipeline Specification

## Anchor-and-Enrich Model — Principles

Audio is the spine. Every note claim originates from audio. Video and screen are enrichment layers.

| Principle | Implementation | Why |
|---|---|---|
| Audio is the spine | Whisper transcript generates the document skeleton. Every section and claim originates from audio. | Audio is continuous, reliable, and complete. Video has gaps, blur, and angle problems. |
| Video is the flesh | Frames extracted only at trigger-classifier-flagged moments — not every frame. | Anchor-based extraction processes 10–30 frames vs 1,200 for a 20-min session at 1fps. 97% compute reduction. |
| Screen is structured data | Screen frames bypass the vision model entirely. OCR extracts structured values and injects directly into note sections. | OCR on a lab results table is faster, cheaper, and more accurate than a vision model description. |
| One source of truth | Timestamped transcript is the canonical reference. All frame citations and screen extractions anchored to transcript segment IDs. | Prevents duplication, contradiction, and alignment drift. |

---

## Frame Citation Data Contract

Every frame processed by the vision pipeline returns this typed citation object. The note generator never receives raw descriptions — only citation objects.

```json
{
  "frame_id": "frame_00214",
  "session_id": "uuid",
  "timestamp_ms": 14500,
  "audio_anchor_id": "seg_001",
  "provider_used": "anthropic",
  "visual_description": "Patient demonstrated visible guarding on palpation of the medial aspect of the right knee. No visible swelling or erythema observed.",
  "confidence": "high",
  "confidence_reason": "Subject clearly visible, appropriate angle, clinically relevant activity",
  "conflict_flag": false,
  "conflict_detail": null,
  "integration_status": "ENRICHES"
}
```

---

## ENRICHES / REPEATS / CONFLICTS Classification

| Status | Definition | Note Generator Behaviour | Physician Action |
|---|---|---|---|
| `ENRICHES` | Visual adds information absent from audio — e.g. audio says "restricted motion", frame shows goniometer at 70° | Inject visual description alongside audio claim with citation marker | None — automatic |
| `REPEATS` | Visual and audio describe the same finding, no additional detail | Discard visual silently. Audio stands alone. | None — silent |
| `CONFLICTS` | Visual contradicts audio — e.g. audio says "no visible swelling", frame shows edema | Surface both side by side in review UI. Flag amber. Note cannot be approved until resolved. | **Mandatory** — physician resolves before approval |

**Low confidence frames (`confidence: low`) are discarded before conflict detection runs. Never injected.**

Confidence is LOW when: image is blurry, wrong angle, subject not clearly visible, no clinically relevant content visible.

---

## Trigger Classifier

Keyword/phrase detector over the timestamped transcript. Not an ML model — a curated specialty-specific keyword list. More reliable, explainable, and maintainable.

### Trigger Categories (stored in specialty template JSON — not hardcoded)

| Category | Example Phrases | Confidence | Specialties |
|---|---|---|---|
| Live imaging review | looking at the X-ray, on the MRI, CT shows, you can see here, pulling up | High | All |
| Active physical examination | range of motion, ROM, flexion, extension, palpation, tenderness, guarding | Medium-High | Orthopedic, MSK |
| Wound and tissue assessment | wound edges, granulation, dimensions, measuring, drainage, flap, perfusion | High | Plastic surgery |
| Gait and functional observation | gait, walking, limping, antalgic, weight bearing, loading | High | Orthopedic, MSK |
| General visual pointer | you can see, look at this, right here, this area, comparing | High | All |

### Suppression List — These Must NOT Trigger Frame Extraction

These phrases describe retrospective narration, not live observation. Pulling a frame captures nothing useful:
- `last visit`, `previously`, `the patient reported`, `history of`, `they mentioned`, `recalled`, `prior to`, `at baseline`

### Frame Extraction Windows (always read from AppConfig — never hardcode)
- Clinic exam triggers: `pipeline.frame_window_clinic_ms` (default 3000ms)
- Procedural triggers: `pipeline.frame_window_procedural_ms` (default 7000ms)

---

## Screen Capture Pipeline

Screen frames bypass the vision provider entirely.

| Step | Action | Tool |
|---|---|---|
| 1 — PHI redaction | On-device: Apple Vision OCR identifies and redacts patient names, MRN, DOB, health card numbers | Apple Vision (on-device) |
| 2 — Screen type classification | Rule-based: `lab_result`, `imaging_viewer`, `emr`, `other` | Rule-based (no ML) |
| 3 — OCR extraction | Structured data per type | AWS Textract |
| 4 — Timestamp anchoring | Link to transcript segment where physician was discussing that content | session/note_gen modules |
| 5 — Note injection | Route to correct note section | note_gen module |

**Routing rules:**
- `lab_result` → structured key-value extraction → inject into `investigations`
- `imaging_viewer` → metadata only (modality, laterality, series label — not the image) → inject into `imaging_review`
- `emr` → log to audit trail only, never inject
- `other` → discard

Screen capture output schema:
```json
{
  "frame_id": "screen_00089",
  "session_id": "uuid",
  "timestamp_ms": 18300,
  "screen_type": "lab_result",
  "extracted_data": {
    "type": "lab_values",
    "values": [
      {"name": "Hemoglobin", "value": "138", "unit": "g/L", "flag": "normal"},
      {"name": "WBC", "value": "9.2", "unit": "10^9/L", "flag": "normal"}
    ]
  },
  "note_section_target": "investigations",
  "integration_status": "injected"
}
```

Screen capture toggled via `feature_flags.screen_capture_enabled` in AppConfig.

---

## Two-Stage Processing Spec

### Stage 1 — Audio-First Draft
- Trigger: immediately on Record Stop
- Target: < 30 seconds from stop to draft delivery on device
- Steps: Whisper transcription → trigger classifier → template-keyed note generation → WebSocket delivery
- Visual sections flagged `status: "pending_video"`
- Stage 1 review window: `pipeline.stage1_skip_window_seconds` (default 60s). Auto-skip triggers Stage 2.

### Stage 2 — Video Enrichment (Async)
- Trigger: Stage 1 approval OR skip window timeout
- Target: < 5 minutes for a 20-minute session
- Steps: retrieve frames → validate masking status → vision provider captions → conflict classification → screen OCR injection → note merge → push notification
- Physician not blocked — runs fully async

---

## Error Handling

| Failure | System Behaviour | Physician Experience | Audit Log Entry |
|---|---|---|---|
| Transcription failure | Session → FAILED. Raw audio purged. | "Transcription failed — session could not be processed." | `transcription_failed` + `session_failed` + `purge_confirmed` |
| Stage 2 timeout/failure | Visual sections → `status: processing_failed`. Note still approvable. | "Visual processing incomplete — you can still approve the audio-based note." | `stage2_failed` + `partial_note_delivered` |
| Vision provider unavailable | Registry falls back to next available. If all fail, Stage 2 marked failed. | Transparent if fallback succeeds. Notification if all fail. | `provider_fallback` + provider name |
| iOS crash during recording | Session stays in RECORDING. Recovery flow on restart. | "Incomplete session detected. Recover or discard?" | `app_crash_detected` + `recovery_initiated` |
| Glasses disconnect | iPhone camera activates automatically. Session continues. | Glasses icon → phone icon in status bar. | `device_failover` + `fallback_device` |
| S3 upload failure | Retry 3× exponential backoff. If all fail, Stage 2 skips affected frames. | Transparent on retry success. `processing_failed` on affected sections. | `upload_failed` + retry count |
| Consent not confirmed | Hard block. Record button disabled. No data captured. | "Confirm patient consent to begin recording." | `consent_block_enforced` |
