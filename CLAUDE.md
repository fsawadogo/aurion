# Aurion Clinical AI — MVP Implementation Brief
**For Claude Code. Read this entire file before writing a single line of code.**

---

## Before You Start — Claude Code Setup

**Run once before any code. Takes 10 minutes.**

### Step 1 — Install Language Server Binaries (terminal)
```bash
pip install pyright
npm install -g typescript-language-server typescript
xcrun sourcekit-lsp --version   # Verify Swift LSP (included with Xcode)
```

### Step 2 — Open Claude Code + Add Demo Marketplace
```bash
cd aurion && claude
/plugin marketplace add anthropics/claude-code
```

### Step 3 — Install Official Plugins
```bash
/plugin install pyright-lsp@claude-plugins-official
/plugin install swift-lsp@claude-plugins-official
/plugin install typescript-lsp@claude-plugins-official
/plugin install github@claude-plugins-official
/plugin install slack@claude-plugins-official
/plugin install sentry@claude-plugins-official
/plugin install commit-commands@claude-plugins-official
/plugin install pr-review-toolkit@claude-plugins-official
/plugin install plugin-dev@claude-plugins-official
/reload-plugins
```

Verify: `/plugin` → Installed tab shows 9 plugins, Errors tab is empty.

### Step 4 — Generate Custom Aurion Extension Layer (Phase 0 First Task)
```
Read CLAUDE.md fully. Then build the custom Aurion extension layer:
1. Generate all 7 skills in .claude/skills/ (new-module, new-provider,
   new-specialty-template, run-tests, seed-localstack, check-phi, add-audit-event)
2. Generate all 6 subagents in .claude/agents/ (backend-builder, ios-builder,
   test-writer, schema-validator, compliance-checker, provider-evaluator)
3. Generate settings.json with 4 hooks in .claude/ (PHI scan, auto-lint,
   unit tests on write, rm -rf guard)
4. Generate mcp.json with PostgreSQL, LocalStack, Docker MCP connections
Use plugin-dev to ensure all skills and agents meet Claude Code best practices.
Run /reload-plugins when done and confirm no errors.
```

### Official Plugin Capabilities
| Plugin | What It Gives You |
|---|---|
| `pyright-lsp` | Python type errors caught after every file write — automatic |
| `swift-lsp` | Swift type errors caught after every file write — automatic |
| `typescript-lsp` | TypeScript errors caught after every file write — automatic |
| `commit-commands` | `/commit-commands:commit` — stage, generate message, commit |
| `github` | Create PRs, read issues, push branches via natural language |
| `slack` | Notify Aurion team channels when phases complete |
| `sentry` | Query production errors during pilot |
| `plugin-dev` | Build custom Aurion skills correctly |

### Custom Aurion Extension Layer
| Tool | Type | Purpose |
|---|---|---|
| `/new-module` | Skill | Scaffold FastAPI module with correct structure + tests |
| `/new-provider` | Skill | Scaffold AI provider + registry + AppConfig schema + tests |
| `/new-specialty-template` | Skill | Generate specialty template JSON |
| `/run-tests` | Skill | pytest with coverage — flags modules below 80% |
| `/seed-localstack` | Skill | Reset and re-seed LocalStack |
| `/check-phi` | Skill | Scan codebase for PHI in logs/errors/responses |
| `/add-audit-event` | Skill | Add new audit event type with DynamoDB schema |
| `@backend-builder` | Subagent | Build FastAPI modules |
| `@ios-builder` | Subagent | Build Swift/SwiftUI |
| `@test-writer` | Subagent | Write pytest tests with LocalStack fixtures |
| `@schema-validator` | Subagent | Validate JSON schemas |
| `@compliance-checker` | Subagent | Scan for PHI leakage after each module |
| `@provider-evaluator` | Subagent | Phase 2 model evaluation — 3 providers, scored output |

### Recommended Workflow Per Phase
| Phase | Primary Tool |
|---|---|
| 0–3 Backend | Main session + `@backend-builder` + hooks auto-lint/test |
| 4 Vision pipeline | **Agent team** — 4 parallel agents |
| 5–6 Screen + cleanup | Main session + `@compliance-checker` after each module |
| 7 iOS | **Fresh session** + `@ios-builder` |
| 8 Infrastructure | Main session — `terraform fmt` + `terraform validate` on every change |
| 9 Web portal | Main session + github for PR workflow |

> **Detailed specs in skills — load when needed:**
> `/pipeline-spec` · `/session-spec` · `/voice-enrollment-spec` · `/localstack-setup` · `/web-portal-spec` · `/specialty-templates`

---

## Who You Are Building For

Faical Sawadogo — Co-Founder & CTO of Aurion Clinical AI. Building the MVP for a wearable multimodal AI physician assistant. Pilot at CREOQ/CLLC with Dr. Perry Gdalevitch (plastic surgeon) and Dr. Marie Gdalevitch (orthopedic surgeon). 3–5 clinicians. Clinic Mode only.

Universal SwiftUI app — full feature parity iPhone + iPad. Single codebase. iOS/iPadOS 16 minimum. A15 Bionic minimum for on-device ML.

---

## The Single Most Important Constraint

**Aurion MVP operates exclusively in Descriptive Mode.**

✅ `"Patient demonstrated restricted internal rotation at approximately 20 degrees on the right side."`
❌ `"Restricted internal rotation at 20 degrees is consistent with rotator cuff pathology. Consider imaging."`

**Every prompt you write for any AI model call must enforce this boundary. If you are unsure — it crosses the line. Stop and rewrite.**

---

## Repo Structure

```
aurion/
├── CLAUDE.md
├── .claude/
│   ├── settings.json          # Hooks
│   ├── skills/                # Custom Aurion skills
│   ├── agents/                # Custom Aurion subagents
│   └── mcp/mcp.json
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   └── modules/
│   │       ├── config/        # AppConfig client, provider registry, feature flags
│   │       ├── providers/     # base.py + transcription/ + note_gen/ + vision/
│   │       ├── session/       # State machine, consent, pause/resume
│   │       ├── transcription/
│   │       ├── note_gen/      # Stage 1 + Stage 2 + versioning
│   │       ├── vision/        # Frame captioning, conflict detection
│   │       ├── screen/        # Screen capture OCR
│   │       ├── phi_audit/
│   │       ├── audit_log/
│   │       ├── cleanup/
│   │       ├── auth/
│   │       ├── onboarding/    # Voice enrollment
│   │       └── export/
│   ├── scripts/ (seed_dev.py, test_pipeline.py, localstack-init/setup.sh)
│   ├── tests/ (unit/, integration/, e2e/)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── .env.example
├── ios/Aurion/ (App/, Capture/, Masking/, Onboarding/, Session/, NoteReview/, Export/, Network/)
├── web/ (Next.js admin portal)
└── infrastructure/ (Terraform — HCL)
```

---

## Pipeline Architecture

**Audio is the spine. Video is the flesh. Screen is structured data.**

| Stream | Role | Processing |
|---|---|---|
| Audio | Primary spine | Whisper → timestamped transcript → SOAP structure |
| Video | Enrichment layer | Frames at trigger timestamps → vision provider → citation objects |
| Screen | Structured data | PHI redaction → OCR → direct injection (no vision model) |

Sequence: transcribe → trigger classifier → extract frames → vision caption → screen OCR → conflict detection → note assembly.

No speaker diarization — single interaction. If voice enrolled: segments tagged `physician` or `other`.

> Load `/pipeline-spec` for full frame citation schema, ENRICHES/REPEATS/CONFLICTS rules, trigger classifier keywords, screen pipeline steps, error handling.

---

## Session State Machine

`IDLE → CONSENT_PENDING → RECORDING → PAUSED → PROCESSING_STAGE1 → AWAITING_REVIEW → PROCESSING_STAGE2 → REVIEW_COMPLETE → EXPORTED → PURGED`

Every transition requires an audit log entry. Record button hard-blocked until `consent_confirmed` in audit log.

> Load `/session-spec` for full state table, note versioning lifecycle, pilot metrics schema, error handling.

---

## Model Abstraction Layer

**Never call AI models directly. Always through the provider registry.**

```python
# CORRECT
provider = registry.get_note_provider()
return await provider.generate_note(transcript, template, stage)

# WRONG
provider = OpenAINoteProvider()
```

Valid provider keys: `transcription` → `whisper|assemblyai` · `note_generation` → `openai|anthropic|gemini` · `vision` → `openai|anthropic|gemini`

### System Prompts — Use Exactly These

**Note generation:**
```
You are a clinical documentation assistant for Aurion Clinical AI. Your role is to accurately document what was observed and said during a clinical encounter.

STRICT RULES:
1. Describe only what was directly captured — audio transcript, visual observations, or screen data.
2. Do not infer, interpret, diagnose, or suggest clinical conclusions.
3. Every statement must be traceable to a source ID.
4. If absent, leave empty with status "not_captured". Never fabricate.
5. Report what happened. Do not conclude what it means.

Return only valid JSON. No preamble, no markdown.
```

**Vision:**
```
You are a clinical visual documentation assistant. Describe only what is literally visible. Do not diagnose, interpret, or infer clinical meaning.

Describe: patient position, visible body parts, observable findings, equipment, screen content.
Do not describe: clinical meaning, suggestions, anything not directly visible.

Return JSON: {"description": "...", "confidence": "high|medium|low", "confidence_reason": "..."}
Confidence LOW if: blurry, wrong angle, subject not visible, no clinical content.
```

---

## Runtime Configuration — AWS AppConfig

No hardcoded config values. Everything through AppConfig.

```json
{
  "providers": { "transcription": "whisper", "note_generation": "anthropic", "vision": "openai" },
  "model_params": {
    "note_generation": { "temperature": 0.1, "max_tokens": 2000 },
    "vision": { "temperature": 0.1, "max_tokens": 500, "confidence_threshold": "medium" }
  },
  "pipeline": {
    "stage1_skip_window_seconds": 60, "frame_window_clinic_ms": 3000,
    "frame_window_procedural_ms": 7000, "screen_capture_fps": 2, "video_capture_fps": 1
  },
  "feature_flags": {
    "screen_capture_enabled": true, "note_versioning_enabled": true,
    "session_pause_resume_enabled": true, "per_session_provider_override": true
  }
}
```

Switching: Level 1 = AppConfig update (< 30s) · Level 2 = Admin API (immediate, audited) · Level 3 = per-session override (evaluation mode)

---

## Build Order

### Phase 0 — Config and Provider Infrastructure
1. `modules/config/schema.py` — Pydantic AppConfig schema
2. `modules/config/appconfig_client.py` — 30s polling, `.env` fallback
3. `modules/providers/base.py` — abstract interfaces (TranscriptionProvider, NoteGenerationProvider, VisionProvider)
4. `modules/providers/` — stub implementations (mock data, no real API calls yet)
5. `modules/config/provider_registry.py`

**Complete when:** registry returns correct stub from config. Change picked up without restart.

### Phase 1 — Backend Foundation
1. `core/` — SQLAlchemy async + PostgreSQL, structured JSON logging (**no PHI ever in logs**), shared Pydantic types
2. `modules/auth/` — JWT via Cognito JWKS. Roles: `CLINICIAN`, `EVAL_TEAM`, `COMPLIANCE_OFFICER`, `ADMIN`
3. `modules/session/` — 10-state machine, consent hard block, pause/resume, audit log on every transition
4. `modules/audit_log/` — DynamoDB append-only. **No update or delete operations. Ever.**
5. `docker-compose.yml` + `scripts/localstack-init/setup.sh`

**Complete when:** `docker-compose up` starts cleanly. Full session lifecycle logged in DynamoDB.

### Phase 2 — Transcription Pipeline
1. `modules/transcription/` — S3 upload, call TranscriptionProvider, parse, trigger PHI audit
2. `providers/transcription/whisper.py` and `assemblyai.py`
3. `modules/phi_audit/` — Comprehend Medical, flag entities, log

Transcript schema:
```json
{"session_id": "uuid", "provider_used": "whisper",
 "segments": [{"id": "seg_001", "start_ms": 14200, "end_ms": 17800,
   "text": "...", "is_visual_trigger": false, "trigger_type": null}]}
```

**Complete when:** AppConfig routing works. Both providers return identical schema.

### Phase 3 — Stage 1 Note Generation
1. `modules/note_gen/` — Stage 1: template load, NoteGenerationProvider call, citation anchors, WebSocket delivery
2. `providers/note_gen/openai.py`, `anthropic.py`, `gemini.py`
3. Note versioning — every edit = new version, approved = vFinal, no version deleted
4. Trigger classifier over transcript segments

Note schema:
```json
{"session_id": "uuid", "stage": 1, "version": 1, "provider_used": "anthropic",
 "specialty": "orthopedic_surgery", "completeness_score": 0.78,
 "sections": [
   {"id": "physical_exam", "status": "populated",
    "claims": [{"id": "claim_001", "text": "...", "source_type": "transcript",
      "source_id": "seg_001", "source_quote": "..."}]},
   {"id": "imaging_review", "status": "pending_video", "claims": []}]}
```

**Complete when:** All 3 providers return identical schema. Stage 1 delivered in < 30s.

### Phase 4 — Vision Pipeline (Stage 2)
1. `modules/vision/` — retrieve frames, validate masking status, call VisionProvider, classify, merge
2. `providers/vision/openai.py`, `anthropic.py`, `gemini.py`
3. Conflict detection: ENRICHES → inject, REPEATS → discard, CONFLICTS → mandatory physician review
4. Low confidence frames → discard before conflict detection

Frame citation schema:
```json
{"frame_id": "frame_00214", "session_id": "uuid", "timestamp_ms": 14500,
 "audio_anchor_id": "seg_001", "provider_used": "anthropic",
 "visual_description": "...", "confidence": "high",
 "conflict_flag": false, "conflict_detail": null, "integration_status": "ENRICHES"}
```

Timestamp windows from AppConfig — **never hardcode**.

**Complete when:** All 3 vision providers return identical schema. Full session produces merged note.

### Phase 5 — Screen Capture Pipeline
1. `modules/screen/` — classification, Textract OCR, PHI redaction, note injection
2. Routing: `lab_result` → investigations · `imaging_viewer` → metadata only · `emr` → skip
3. Toggled via `feature_flags.screen_capture_enabled`

Screen schema:
```json
{"frame_id": "screen_00089", "session_id": "uuid", "timestamp_ms": 18300,
 "screen_type": "lab_result",
 "extracted_data": {"type": "lab_values",
   "values": [{"name": "Hemoglobin", "value": "138", "unit": "g/L", "flag": "normal"}]},
 "note_section_target": "investigations", "integration_status": "injected"}
```

**Complete when:** Toggle works. Lab → structured values. Imaging → metadata only. EMR skipped.

### Phase 6 — Audit, Cleanup, Export
1. `modules/cleanup/` — purge audio after transcription, frames after export, migrate eval frames
2. `modules/export/` — DOCX (python-docx), plain text, cleanup trigger, purge confirmation to audit log
3. `pilot_metrics` table — 8 behaviour metrics per session

**Complete when:** Full lifecycle audit trail. All 8 metrics logged per session.

### Phase 7 — iOS App
1. `Onboarding/` — voice enrollment flow (load `/voice-enrollment-spec` for full details)
2. `Capture/` — AVFoundation 3 streams, BLE pairing, pause/resume, device failover
3. `Masking/` — MediaPipe face detection, Apple Vision screen redaction, status logged before upload
4. `Network/` — URLSession API client, WebSocket
5. `NoteReview/` — section cards, amber CONFLICTS mandatory, tap-to-source, note versioning, two-tap approval
6. `Export/` — on-device DOCX, plain text, purge trigger

**Complete when:** Full end-to-end on device — consent → record → pause → resume → stop → Stage 1 → Stage 2 → conflicts → approve → export → purge confirmed.

### Phase 8 — Infrastructure as Code
Terraform (HCL): VPC, ECS Fargate, RDS PostgreSQL, DynamoDB, S3 (TTL policies), KMS, Cognito, AppConfig (with schema validator + deployment strategy), CloudWatch dashboards + alarms. Per-environment tfvars (`dev.tfvars`, `prod.tfvars`); state stored in remote backend (S3 + DynamoDB lock).

**Complete when:** `terraform apply -var-file=environments/dev.tfvars` provisions everything in `ca-central-1`. AppConfig change live in < 30s.

### Phase 9 — Web Portal
Next.js 14, TypeScript, Tailwind, AWS Amplify. Calls FastAPI `/api/v1/admin/*`. Same Cognito pool.

Load `/web-portal-spec` for full feature list and role access matrix.

**Complete when:** Compliance officer can log in, view audit logs, confirm PHI masking for all pilot sessions.

---

## Passive Data Collection — Pilot Metrics

Stored in `pilot_metrics` PostgreSQL table. No PHI. 100% of sessions. Access: Eval Team + CTO only.

| Metric | Measures |
|---|---|
| `template_section_completeness` | % required sections populated |
| `citation_traceability_rate` | % claims with valid source_id |
| `physician_edit_rate` | Diff v1 → vFinal per section |
| `conflict_rate` | % frame citations CONFLICTS |
| `low_confidence_frame_rate` | % frames discarded |
| `stage1_latency_ms` | record_stop → stage1_delivered |
| `stage2_latency_ms` | stage1_approved → full_note_delivered |
| `session_completeness` | All 7 metrics above logged |

---

## Non-Negotiable Technical Rules

**Privacy:**
- Raw audio deleted after transcription — S3 TTL + Lambda cleanup logs confirmation
- Raw video frames never leave iOS unmasked — masking status logged before any upload
- PHI never in logs, errors, API responses, AppConfig docs, or S3 keys
- S3: KMS encryption, public access blocked, versioning disabled
- Audit log: append-only. No update or delete. Ever.
- Voice embedding stored in iOS Keychain only — never transmitted to backend

**Secrets:** All API keys in AWS Secrets Manager. Never in code. AI provider keys never called from iOS.

**AI calls:** Descriptive mode system prompt on every call. Every call logged with provider + model + session ID (no PHI). Vision calls only on frames with confirmed masking status. `provider_used` on every output.

**AppConfig:** No provider keys from environment at runtime. Invalid key fails Pydantic validation before deployment. Every change logged to audit trail.

**Error handling:** Stage 2 failure → `processing_failed` status, still approvable. Provider unavailable → fallback to next, log it. App crash → recovery flow on restart. No broken session without audit log entry.

**Code quality:** Type hints everywhere. Pydantic for all schemas. Async throughout. No business logic in route handlers. Modules never import each other — shared types in `core/`. Providers only via registry. pytest 80% minimum coverage.

---

## Specialty Templates

Load `/specialty-templates` for full section definitions and visual trigger keywords.

| Template Key | Required Sections |
|---|---|
| `orthopedic_surgery` | chief_complaint, hpi, physical_exam, imaging_review, assessment, plan |
| `plastic_surgery` | chief_complaint, hpi, wound_assessment, imaging_review, assessment, plan |
| `musculoskeletal` | chief_complaint, hpi, functional_assessment, physical_exam, imaging_review, assessment, plan |
| `emergency_medicine` | chief_complaint, hpi, vital_signs, physical_exam, investigations, assessment, disposition |
| `general` | chief_complaint, hpi, physical_exam, assessment, plan |

---

## Local Development

Load `/localstack-setup` for: full `docker-compose.yml`, LocalStack init script, `.env.example`, setup commands, pipeline test script, common issues.

Quick reference:
```bash
cd backend && docker-compose up -d && python scripts/seed_dev.py
curl http://localhost:8000/health
```
Services: FastAPI `localhost:8000` · PostgreSQL `5432` · LocalStack `4566` · Whisper `8001`
Web portal: `cd web && npm run dev` → `localhost:3000`

---

## MVP Success Criteria

| Metric | Target |
|---|---|
| Template section completeness | ≥ 90% |
| PHI masking pass rate | 100% |
| Citation traceability | ≥ 95% of claims have valid source_id |
| Stage 1 latency | < 30 seconds |
| Stage 2 latency | < 5 minutes |
| Consent enforcement | Hard block — no session without consent |
| CONFLICTS resolution | 100% resolved before approval |
| Audit log completeness | 100% of sessions |
| Raw data purge | Confirmed in audit log every session |
| Provider switching | < 30 seconds via AppConfig, no redeploy |
| Provider traceability | `provider_used` on every note and citation |
| Pilot metrics | All 8 metrics logged for 100% of sessions |
| Voice enrollment | Raw audio deleted immediately |
| Voice biometric data | Embedding never transmitted to backend |
| Speaker separation | ≥ 90% of physician segments correctly tagged |

---

## What NOT to Build

Post-Op/Procedural Mode · EMR/FHIR integration · LLM fine-tuning · French support · Admin dashboard · Clinician frame viewer · Voice record commands · Interpretative AI · Android · Speaker diarization · Diagnostic inference · Face enrollment · Multi-physician voice profiles · Cloud voice verification

**If you are building any of these — stop and re-read this file.**

---

## Questions Before You Start

1. **API keys** — OpenAI, Anthropic, Google AI in Secrets Manager before Phase 3.
2. **Monorepo root** — confirm existing structure fits the layout above.
3. **AppConfig** — confirm whether an application already exists or needs Terraform creation.
4. **Visual trigger keywords** — start with empty lists. Build classifier to work with whatever keywords exist. Population happens post-pilot.
