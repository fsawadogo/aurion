# Aurion MVP Scope Backlog

Last updated: May 13, 2026

Source scope: "AURION - MVP Scope Definition, Clinic Mode Pilot - CREOQ / CLLC, May 11, 2026"

## Executive Summary

The repository already contains a meaningful MVP foundation:

- Backend: FastAPI session state machine, consent gate, transcription, trigger classification, Stage 1 note generation, Stage 2 vision merge path, screen OCR service, audit log service, provider registry, cleanup service, profile service, and admin APIs.
- Mobile: SwiftUI iOS app with onboarding, voice enrollment UI, local voice fingerprint generation, capture lifecycle, AVFoundation audio/video capture, local face/screen masking, note review, export UI, profile UI, and device hub.
- Web: Next.js admin portal with login, dashboard, sessions/completeness table, audit log viewer, PHI masking report, users page, provider config viewer, and eval scoring page.

The repo is not yet complete against the pasted MVP scope. The largest remaining gaps are clinical workflow depth, production-grade privacy enforcement, real wearable integration, web note review/edit/export, scheduling/patient charting/templates, persistent role-based user management, and end-to-end hardening.

Approximate remaining effort to reach the defined web + mobile MVP:

- Total: 36-50 engineer-weeks.
- Calendar time with parallel team of 4 engineers plus part-time QA/compliance: 12-16 weeks.
- Calendar time with 2 engineers: 20-28 weeks.
- Fastest credible pilot-hardening path, if Schedule/Templates/Patient Chart Workspace are deferred: 8-10 weeks.

These estimates assume existing architecture is kept, no major redesign is introduced, and Meta Wearables SDK access is available. If Ray-Ban Meta partner approval/framework access is delayed, the wearable portion remains schedule-risk and should be split from iPhone/iPad fallback readiness.

## Audit Findings By Area

### Backend Foundation

Existing implementation:

- `backend/app/main.py` wires auth, profile, config, admin, privacy, sessions, transcription, frames, notes, vision, export, and websocket routes.
- `backend/app/modules/session/service.py` implements the 10-state session machine and consent hard block.
- `backend/app/modules/transcription/service.py` and `backend/app/api/v1/transcription.py` implement transcription, trigger classification, transcript persistence, PHI audit, and Stage 1 note creation.
- `backend/app/modules/note_gen/templates/` contains the 5 scoped specialty templates: ortho, plastics, MSK, EM, general.
- `backend/app/modules/vision/service.py` implements masked frame retrieval, captioning, ENRICHES / REPEATS / CONFLICTS merge logic, and conflict claims.
- `backend/app/modules/screen/service.py` implements OCR, PHI text redaction, lab value extraction, imaging metadata extraction, and routing.
- `backend/app/api/v1/admin.py` exposes audit, masking report, metrics, sessions, config, users, and eval endpoints.

Backend gaps:

- No Alembic migration versions exist under `backend/alembic/versions`, so DB schema evolution is not production-ready.
- User management in admin API still uses an in-memory `_MOCK_USERS` store rather than the SQL `UserModel` or Cognito-backed provisioning.
- Eval scores are in-memory, not persistent.
- Screen OCR service is not fully connected to mobile screen frame upload or note injection.
- Stage 2 is triggered inline from `approve-stage1`, not as a resilient async job with status, retry, and <5 min SLA monitoring.
- Backend trusts iOS masking audit events for uploaded frames; it does not enforce masking proofs or reject uploads without verifiable masking metadata.
- Cleanup/purge policy needs end-to-end proof across audio, frames, local device copies, export events, and immutable audit entries.
- Role-based access exists, but web navigation and feature visibility are not consistently role-scoped.

### Mobile App

Existing implementation:

- Onboarding includes biometric consent, four voice enrollment sentences, processing, and local embedding storage.
- `CaptureManager` performs real audio/video capture with AVFoundation and frame extraction.
- `ScreenCaptureManager` captures ReplayKit screen frames locally.
- `MaskingPipeline` performs Apple Vision face detection/blur and OCR-based screen redaction locally.
- `SessionManager` creates sessions, confirms consent, starts/pauses/resumes/stops recording, uploads masked video frames, uploads audio, fetches Stage 1 note, and opens note review.
- `NoteReviewView` supports section review, editing, conflict block on approval, Stage 1 approval, Stage 2 trigger, and final approval.
- `ExportView` exposes DOCX export UI and share sheet.
- `ProfileView` exposes profile, voice profile status, language, privacy, and local history surfaces.

Mobile gaps:

- Meta Wearables source is explicitly stubbed; `MetaWearablesSource.start()` throws `notImplemented`.
- Voice enrollment creates a 256-float fingerprint, while `SpeakerSeparation` expects 128 dimensions. Speaker tagging is not integrated into the transcription upload path.
- Masking failure currently falls back to original image data in some paths. This violates the scope requirement that nothing unmasked leaves the phone.
- Screen frames are captured locally but are not submitted through a dedicated screen OCR pipeline endpoint, and extracted lab/imaging data is not merged into notes end-to-end.
- Export is server round-trip based through `APIClient.exportNote`; scope requires DOCX/plain text generated on-device with no server round-trip.
- Plain text export is marked unavailable; PDF appears in UI but is unavailable and not in MVP scope.
- Raw local data purge is not fully implemented as an audited, timed lifecycle.
- Demo fallback notes can appear when transcription fails, which is unsafe for pilot use unless hard-disabled in production builds.
- iPhone/iPad parity and device testing are not evidenced by automated UI tests beyond launch stubs.

### Web Portal

Existing implementation:

- Next.js app has portal routes for dashboard, sessions, audit, masking, users, config, and eval.
- Audit viewer has filtering and CSV export.
- PHI masking report has pass/fail summary and per-session table.
- Provider config viewer reads active AppConfig state.
- Eval page lists reviewable sessions and allows scoring.
- Users page exists and talks to admin user endpoints.

Web gaps:

- No browser note review/edit/export interface exists. The sessions page is a completeness table only.
- User management is backed by mock/in-memory admin users and does not map cleanly to real SQL/Cognito users.
- Eval environment does not show linked masked frames, transcript, generated note, citations, or persistent detailed scoring workflow.
- Schedule does not exist.
- Web profile/settings page does not exist.
- Template CRUD/linking UI does not exist; backend has `CustomTemplateModel` but no complete admin/user workflow.
- Patient Chart Workspace does not exist.
- Navigation shows all sections without role-specific visibility. Clinicians, compliance officers, and eval users need different portal surfaces.

## Priority Backlog

Priority definitions:

- P0: Required before any real pilot data is captured.
- P1: Required to meet the pasted MVP scope.
- P2: Important hardening or workflow completeness that can follow initial pilot if explicitly accepted.

### P0 - Pilot Safety And Compliance Blockers

| ID | Area | Backlog item | Existing basis | Done when | Estimate |
|---|---|---|---|---|---|
| P0-01 | Mobile privacy | Make masking fail-closed. Remove original-image fallback on face/OCR failure, block upload on masking errors, log `masking_failed`, and surface retry/skip to clinician. | `MaskingPipeline`, `SessionManager.submitFrames` | No unmasked frame or screen capture can be uploaded under any failure mode. | 3-5 days |
| P0-02 | Mobile/backend privacy | Add masking proof contract to frame upload. Include client masking result metadata, frame type, counts, and failure state; backend rejects frame upload without proof. | `frames.py`, `MaskingPipeline`, `AuditLogger` | PHI masking report can distinguish masked, failed, skipped, and uploaded counts per session. | 4-6 days |
| P0-03 | Mobile | Disable demo fallback notes in pilot/production builds. Keep simulator demo behind explicit dev flag only. | `SessionManager.createDemoNote`, transcription demo mode | Failed transcription never produces fabricated clinical output in pilot. | 1-2 days |
| P0-04 | Backend | Add real migrations for current models and local/prod bootstrap. | SQLAlchemy models, Alembic shell | Fresh environment can migrate DB schema without `create_all` assumptions. | 3-5 days |
| P0-05 | Backend/mobile | Complete raw data purge lifecycle. Audio deleted <1 hr after transcription; video/screen frames purged 24 hrs after export; local device cache purged; immutable audit entries prove deletion. | `cleanup/service.py`, S3 lifecycle script, local iOS storage | Compliance can inspect purge confirmations per session. | 5-8 days |
| P0-06 | Backend/web | Replace in-memory users/eval scoring with persistent storage or Cognito-backed implementation. | `UserModel`, admin API | User edits and eval scores survive process restart and are role-audited. | 5-8 days |
| P0-07 | All | Add end-to-end smoke test for consent -> record -> transcription -> Stage 1 -> review -> Stage 2 -> approve -> export -> purge. | Existing unit tests and scripts | One command verifies the core pilot workflow in local env. | 4-6 days |

P0 subtotal: 5-7 engineer-weeks.

### P1 - Mobile MVP Scope

| ID | Feature | Backlog item | Existing basis | Done when | Estimate |
|---|---|---|---|---|---|
| M-01 | Voice Enrollment | Reconcile embedding dimensions and integrate speaker tagging into transcript segments. | `VoiceEmbeddingExtractor`, `SpeakerSeparation`, `TranscriptSegment.speaker` | Enrolled physician segments are tagged as physician/other without uploading voice profile. | 4-7 days |
| M-02 | Continuous Capture | Complete capture source orchestration for audio + video + screen simultaneously, including mode-specific behavior and UI states. | `CaptureSourceRegistry`, `CaptureManager`, `ScreenCaptureManager` | One tap starts selected streams; pause/resume affects all streams consistently. | 5-8 days |
| M-03 | Ray-Ban Meta | Replace Meta stub with real SDK integration once partner framework is available; keep iPhone/iPad fallback. | `MetaWearablesSource`, `BLEPairingManager`, `BluetoothAudioSource` | Paired glasses can provide video source; fallback is explicit and audited. | 2-4 weeks, SDK-dependent |
| M-04 | On-Device PHI Masking | Expand screen PHI detection beyond current regexes, add masking QA fixtures, and fail-closed uploads. | `MaskingPipeline` | Test suite covers names, MRN, DOB, RAMQ/OHIP, labels, common EMR layouts, failure cases. | 5-8 days |
| M-05 | Patient Consent | Add paper-consent metadata capture and visible audit history in mobile session detail. | `confirmConsent`, `AuditLogger` | Consent timestamp and method are visible before record and in audit details. | 2-3 days |
| M-06 | Stage 1 Draft | Enforce <30 sec SLA instrumentation in app and backend, with timeout/retry states. | Transcription endpoint, `PilotMetricsModel` | UI shows Stage 1 status; metrics log record-stop-to-note latency. | 4-6 days |
| M-07 | Stage 2 Visual Enrichment | Make Stage 2 truly async so physician can move to next patient while status updates later. | `approve-stage1`, websocket client | Stage 2 status survives app close/reopen and completes without blocking UI. | 6-10 days |
| M-08 | Screen OCR | Upload redacted screen frames to backend OCR endpoint and merge extracted lab/imaging data into notes. | `ScreenCaptureManager`, `screen/service.py` | Lab values and imaging metadata appear as screen-sourced note claims, no AI interpretation. | 6-9 days |
| M-09 | SOAP Note Generation | Harden note schema validation, source anchoring, and specialty template selection. | Built-in templates, note provider layer | Every claim has transcript, visual frame, screen capture, or physician-edit source. | 4-6 days |
| M-10 | Review & Approval | Add explicit conflict resolution workflow, not just block approval. | `NoteReviewView`, backend conflict check | Clinician can mark/resolve each conflict with audit trail before approval. | 5-8 days |
| M-11 | Export | Generate DOCX and plain text on-device with no server call; remove non-MVP PDF option or clearly defer. | `ExportView`, backend export service | Share sheet receives locally generated DOCX/text; export audit logged after local generation. | 6-10 days |
| M-12 | Raw Data Purge | Add device-local timers, background cleanup, export-triggered purge, and visible status. | `ExportView`, cleanup service | Local audio/video/screen artifacts are deleted on the MVP schedule and audit logged. | 5-8 days |
| M-13 | iPad parity | Verify and adjust iPhone/iPad layouts for capture, review, export, profile, device setup. | SwiftUI universal app | All primary flows pass on iPhone and iPad simulators/devices. | 5-8 days |

Mobile P1 subtotal: 12-18 engineer-weeks, excluding Meta SDK approval delay.

### P1 - Web Portal MVP Scope

| ID | Feature | Backlog item | Existing basis | Done when | Estimate |
|---|---|---|---|---|---|
| W-01 | User Management | Replace mock user store with real user CRUD, role changes, activation/deactivation, audit entries, and backend tests. | `UserModel`, `auth/service.py`, `users/page.tsx` | Admin can manage clinicians, nurses, compliance, eval users; changes persist. | 5-8 days |
| W-02 | Audit Log Viewer | Harden audit filters, retention metadata, session drill-down, and role-specific access. | `audit/page.tsx`, admin audit APIs | Compliance can inspect full immutable session log and export filtered evidence. | 3-5 days |
| W-03 | PHI Masking Report | Back report with verified masking/upload counts and failure reasons. | `masking/page.tsx`, masking report API | Report proves 100% on-device masking before transmission, or shows exact blockers. | 4-6 days |
| W-04 | Note Review Interface | Build browser note review with full note, section edit, citations, conflict resolution, approval, and export. | Mobile `NoteReviewView`, notes API | Clinician can complete end-of-clinic review in browser. | 8-12 days |
| W-05 | Provider Config Viewer | Add status, propagation time, provider health, and config history clarity. | `config/page.tsx`, AppConfig client | Compliance/internal users can verify active provider and recent changes. | 3-5 days |
| W-06 | Internal Eval Environment | Build eval detail view with masked frames, transcript, generated note, source links, scoring rubric, and retention approval gating. | `eval/page.tsx`, eval APIs | Eval team can validate a session without clinician/pilot visibility. | 8-12 days |
| W-07 | Schedule | Build patient schedule model/API/UI: add patient, appointment time, visit type, clinician assignment, start session from schedule. | None found | Clinician can add patients to schedule and start encounter from schedule. | 10-15 days |
| W-08 | Templates | Build visit type templates and note templates CRUD; link visit types to note templates; add validation and preview. | `CustomTemplateModel`, built-in templates | User can create/update templates and bind visit types to note templates. | 10-15 days |
| W-09 | Profile | Build web profile/settings page for practice type, consultation types, templates, defaults, language, retention preferences. | Backend profile service, mobile profile UI | User can manage profile in portal and mobile picks up defaults. | 5-8 days |
| W-10 | Patient Chart Workspace | Build patient-centric workspace with staff, encounters, notes, edit/approve/validate actions, and audit trail. | None found | User can view all staff interactions and notes for a patient in one workspace. | 12-18 days |
| W-11 | Role-scoped Portal | Hide/allow routes by role and add route guards/client nav filtering. | Backend roles, sidebar | Clinician, compliance, eval, and admin see only allowed surfaces. | 4-6 days |
| W-12 | Web QA | Add Playwright coverage for role nav, note review, audit, masking, schedule, templates, profile, chart workspace. | Existing Next app | Critical portal workflows have regression coverage. | 6-10 days |

Web P1 subtotal: 19-28 engineer-weeks.

### P1 - Backend And Integration Work Needed By Web/Mobile

| ID | Area | Backlog item | Needed by | Estimate |
|---|---|---|---|---|
| B-01 | Patients | Add patient model with scoped identifiers, non-PHI display strategy, schedule linkage, and chart workspace relation. | Schedule, chart workspace | 5-8 days |
| B-02 | Schedule | Appointment/visit API with clinician assignment, visit type, status, and session creation link. | Web schedule, mobile dashboard optional | 5-8 days |
| B-03 | Templates | Complete custom template API, validation, versioning, and visit-type linkage. | Web templates, mobile post-encounter selector | 6-10 days |
| B-04 | Notes | Add note detail endpoint optimized for web review, source citation expansion, conflict resolution state, and export metadata. | Web note review, eval | 5-8 days |
| B-05 | Screen OCR | Add upload/process endpoints for screen frames and merge results into note versions with source IDs. | Mobile screen OCR | 5-8 days |
| B-06 | Stage 2 jobs | Move visual enrichment to a background job/work queue with retry, status, websocket updates, and SLA metrics. | Mobile and web note review | 8-12 days |
| B-07 | Audit | Standardize event schema and actor/session metadata across mobile, backend, and web. | Audit, masking report, compliance | 4-6 days |
| B-08 | Eval | Persist eval records, retention approvals, frame/transcript/note linkage, and access policy. | Internal eval environment | 5-8 days |
| B-09 | Export | Support on-device export audit without server-generated file; keep server export only for web portal if allowed. | Mobile export, web review | 3-5 days |

Backend/integration subtotal: 12-18 engineer-weeks. Some overlaps with web/mobile estimates if one engineer owns vertical slices.

## Scope Feature Status Matrix

### Mobile App

| Scope feature | Current repo status | Backlog status |
|---|---|---|
| Voice Enrollment | Partially built. UI and local embedding exist; dimension/integration mismatch remains. | M-01 |
| Continuous Capture | Partially built for iPhone/iPad audio/video and local screen capture; orchestration and Meta are incomplete. | M-02, M-03 |
| On-Device PHI Masking | Partially built but must fail-closed. | P0-01, P0-02, M-04 |
| Patient Consent | Backend and mobile flow mostly built; paper-consent metadata needs polish. | M-05 |
| Audio Transcription | Backend done for MVP path; mobile upload wired. Needs production failure behavior and SLA metrics. | P0-03, M-06 |
| Stage 1 Draft <30 sec | Built functionally; SLA instrumentation/retry not complete. | M-06 |
| Stage 2 Visual Enrichment <5 min | Backend path exists but is inline/best-effort; async job/status needed. | M-07, B-06 |
| Screen OCR | Backend service and mobile capture exist separately; end-to-end upload/merge missing. | M-08, B-05 |
| SOAP Note Generation | Built with 5 templates and source IDs; needs stricter validation and source coverage. | M-09, B-04 |
| Review & Approval | Mobile review exists; conflict resolution workflow incomplete. | M-10 |
| Export DOCX/plain text | UI exists; server round-trip and no plain text. | M-11, B-09 |
| Raw Data Purge | Backend/local pieces exist; end-to-end audited lifecycle incomplete. | P0-05, M-12 |

### Web Portal

| Scope feature | Current repo status | Backlog status |
|---|---|---|
| User Management | UI/API exist but API is mock/in-memory. | P0-06, W-01 |
| Audit Log Viewer | Built; needs schema/retention hardening. | W-02, B-07 |
| PHI Masking Report | Built UI/API; needs verified proof contract. | P0-02, W-03 |
| Note Review Interface | Not built for web. | W-04, B-04 |
| Provider Config Viewer | Mostly built read-only. | W-05 |
| Internal Eval Environment | Partial list/scoring; no linked session evidence view; scoring in-memory. | W-06, B-08 |
| Schedule | Not found. | W-07, B-02 |
| Templates | Backend model only; no complete API/UI. | W-08, B-03 |
| Profile | Backend/mobile exist; web page absent. | W-09 |
| Patient Chart Workspace | Not found. | W-10, B-01 |

## Recommended Delivery Plan

### Milestone 1 - Pilot-Safe Core (Weeks 1-3)

Goal: make the current mobile/backend flow safe enough for internal dry runs.

- Complete P0 privacy fixes.
- Add migrations.
- Disable demo fallback in non-dev.
- Add purge lifecycle.
- Add end-to-end smoke test.
- Persist real users/eval records or explicitly gate them out of pilot.

Exit criteria:

- No unmasked data leaves mobile under test failures.
- A fresh local environment can run migrations and smoke test.
- A session has complete audit evidence for consent, capture, masking, transcription, Stage 1, Stage 2, approval, export, and purge.

### Milestone 2 - Mobile MVP Completion (Weeks 3-8)

Goal: complete the clinician iPhone/iPad encounter loop.

- Integrate voice enrollment with speaker tagging.
- Complete simultaneous audio/video/screen capture orchestration.
- Add screen OCR upload and note merge.
- Make Stage 2 async and recoverable.
- Implement conflict resolution.
- Generate DOCX/plain text on-device.
- Verify iPad parity.
- Integrate Ray-Ban Meta if SDK is available; otherwise mark fallback pilot path.

Exit criteria:

- Clinician can run a complete encounter on iPhone/iPad fallback.
- Stage 1 returns within tracked SLA or fails with retry state.
- Stage 2 completes asynchronously and updates note state.
- Note can be approved only after conflicts are resolved.
- Export happens locally for mobile.

### Milestone 3 - Web Clinical Workflow (Weeks 5-12)

Goal: build the web features in the pasted scope.

- Real user management and role-scoped portal.
- Browser note review/edit/export.
- Internal eval evidence view.
- Schedule.
- Profile.
- Templates and visit type linkage.
- Patient chart workspace.
- Web Playwright coverage.

Exit criteria:

- Clinicians can manage schedule, templates/profile defaults, review notes, and inspect patient chart workspace.
- Compliance can inspect audit and masking reports.
- Eval team can review linked masked evidence and persist scores.
- Routes and navigation are role-scoped.

### Milestone 4 - Pilot Readiness Hardening (Weeks 12-16)

Goal: reduce operational risk before external clinic pilot.

- Run iPhone/iPad device testing and web E2E tests.
- Validate provider failover and config switch under 30 seconds.
- Load test expected clinic-day session volumes.
- Dry-run retention/purge reports.
- Document incident, privacy, and operator runbooks.
- Freeze scope and produce known-issues list for CREOQ/CLLC pilot.

## Key Risks

- Meta Wearables SDK access is an external dependency. Plan pilot fallback on iPhone/iPad unless partner approval is confirmed.
- Current masking failure behavior must be fixed before any real patient capture.
- Web scope includes full practice workflow objects (patients, schedule, templates, chart workspace) that are mostly absent today; this is larger than a dashboard polish pass.
- Lack of migrations means current backend schema is fragile across environments.
- Demo-mode behavior must be clearly isolated from pilot/production to avoid accidental fabricated clinical notes.
- End-to-end testing is currently the biggest confidence gap. Unit tests exist, but the integrated clinical path needs automated coverage.

## Estimate Assumptions

- One engineer-week equals roughly 4 focused implementation days plus review/testing overhead.
- Estimates include focused unit/integration tests for the changed feature, not full regulatory validation.
- Estimates do not include App Store review, formal security audit, clinical validation study, procurement, or Meta partner approval time.
- Estimates assume current backend, iOS, and web patterns remain in place.
- A smaller "clinic dry-run" milestone can be reached sooner if Schedule, Templates, Profile web page, and Patient Chart Workspace are explicitly deferred.
