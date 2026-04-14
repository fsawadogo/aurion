# Aurion Clinical AI — Privacy Impact Assessment (Quebec Law 25)

**Document Version:** 1.0
**Date:** 2026-04-11
**Privacy Officer:** Faical Sawadogo, Co-Founder & CTO
**Organization:** Aurion Clinical AI Inc.
**Applicable Legislation:** Quebec Act Respecting the Protection of Personal Information in the Private Sector (Law 25), PIPEDA

---

## 1. Purpose

Aurion Clinical AI is a wearable multimodal AI physician assistant that captures clinical encounters through audio, video, and screen streams, and generates structured, citation-anchored SOAP clinical notes. The system operates exclusively in Descriptive Mode — it documents what was observed and said, without interpretation, inference, or diagnosis.

This Privacy Impact Assessment (PIA) evaluates the personal information practices of the Aurion Clinical AI MVP, identifies privacy risks, and documents the safeguards implemented to protect the personal information of physicians and patients in compliance with Quebec Law 25.

The pilot deployment is at CREOQ/CLLC with 3-5 clinicians in Clinic Mode only.

---

## 2. Data Types Collected

| Data Type | Description | Contains PI | Contains Health Info | Retention |
|---|---|---|---|---|
| Audio recordings | Physician-patient encounter audio | Yes (voices) | Yes (clinical discussion) | < 1 hour (deleted after transcription) |
| Video frames | Frames extracted at clinically relevant moments | Yes (before masking) | Yes (physical findings) | < 24 hours (deleted after processing) |
| Screen captures | EMR screenshots, lab results, imaging viewers | Yes (before redaction) | Yes (lab values, imaging) | < 24 hours (deleted after processing) |
| Voice embeddings | 256-dimension mathematical representation of physician voice | Yes (biometric) | No | Until physician deletes (device-only) |
| Transcripts | Timestamped text of clinical encounter | Indirect (clinical context) | Yes (clinical observations) | 7 years or account deletion |
| Clinical notes | Structured SOAP notes generated from transcripts and visual data | Indirect (clinical context) | Yes (documented findings) | 7 years or account deletion |
| Session metadata | Session state, timestamps, specialty, provider used | Minimal (clinician ID) | No | 7 years or account deletion |
| Audit logs | Immutable record of all system events | Minimal (clinician ID) | No | 7 years (pseudonymized on account deletion) |
| Pilot metrics | Quantitative performance measurements per session | No (aggregated) | No | Until analysis complete |
| Account information | Clinician name, email, role, Cognito identity | Yes | No | Until account deletion |

---

## 3. Data Flow

### 3.1 Capture Phase (On-Device)

1. Patient consent is confirmed and recorded in the audit log before any data capture begins. The record button is hard-blocked until consent is confirmed.
2. Audio is captured via the iPhone/iPad microphone or paired Ray-Ban Meta Smart Glasses.
3. Video frames are captured from the wearable camera or device camera.
4. Screen captures are taken when the physician views EMR/lab/imaging screens.
5. On-device PHI masking runs before any data leaves the device:
   - MediaPipe face detection masks all faces in video frames.
   - Apple Vision OCR identifies and redacts patient names, MRN, DOB, and health card numbers in screen captures.
6. Masking status is confirmed in the audit log before any upload proceeds.

### 3.2 Upload Phase (Device to Cloud)

7. Masked video frames and redacted screen captures are uploaded to S3 (ca-central-1) with KMS encryption.
8. Audio is uploaded to a separate S3 bucket with a < 1 hour TTL.
9. All uploads use TLS 1.2+ in transit.

### 3.3 Processing Phase (Cloud)

10. Audio is transcribed by the active transcription provider (Whisper self-hosted on ECS, or AssemblyAI).
11. Transcripts undergo PHI audit via AWS Comprehend Medical — flagged entities are logged.
12. Raw audio is deleted from S3 immediately after successful transcription.
13. The note generation provider (OpenAI, Anthropic, or Google Gemini) generates a Stage 1 SOAP note from the transcript.
14. The trigger classifier identifies visually relevant moments. The vision provider captions masked frames.
15. Screen captures are processed via AWS Textract OCR — no vision model is used.
16. Stage 2 merges visual and screen data into the note with citation anchors.

### 3.4 Review Phase

17. The physician reviews the generated note on the iOS app.
18. Visual conflicts (CONFLICTS status) require mandatory physician resolution before approval.
19. Every edit creates a new immutable note version.

### 3.5 Export and Purge Phase

20. The approved note is exported as DOCX (generated on-device).
21. Remaining temporary data (frames, screen captures) is purged from S3.
22. Purge confirmation is written to the audit log.

### 3.6 Voice Enrollment (One-Time, On-Device Only)

23. Physician records a voice sample during onboarding.
24. A voice embedding is generated on-device using CoreML.
25. The raw audio recording is deleted immediately after embedding generation.
26. The embedding is stored in the iOS Keychain (encrypted, device-local).
27. The embedding never leaves the device and is never transmitted to the backend.

---

## 4. Recipients of Personal Information

| Recipient | Data Received | Purpose | Legal Basis |
|---|---|---|---|
| Treating clinician | Full clinical notes, transcripts | Clinical documentation | Consent (patient), employment (clinician) |
| Internal eval team | Masked transcripts, masked frames, generated notes | Quality assurance | Legitimate interest |
| Compliance officer | Audit logs, masking reports (no raw clinical data) | Regulatory compliance | Legal obligation |
| OpenAI (US) | Transcripts, masked frame images (via API) | AI note generation and vision captioning | DPA, SCCs for cross-border transfer |
| Anthropic (US) | Transcripts, masked frame images (via API) | AI note generation and vision captioning | DPA, SCCs for cross-border transfer |
| Google (US) | Transcripts, masked frame images (via API) | AI note generation and vision captioning | DPA, SCCs for cross-border transfer |
| AssemblyAI (US) | Audio recordings (via API) | Transcription | DPA, SCCs for cross-border transfer |
| AWS (ca-central-1) | Encrypted data at rest | Cloud infrastructure | DPA, data residency in Canada |

---

## 5. Retention Periods

| Data Type | Retention Period | Deletion Method |
|---|---|---|
| Raw audio recordings | < 1 hour | S3 lifecycle auto-TTL + Lambda confirmation |
| Video frames | < 24 hours | S3 lifecycle auto-TTL |
| Screen captures | < 24 hours | S3 lifecycle auto-TTL |
| Evaluation frames | Until evaluation complete + deletion request | Manual purge with audit confirmation |
| Session metadata | 7 years or account deletion request | PostgreSQL cascade delete |
| Clinical notes (all versions) | 7 years or account deletion request | PostgreSQL cascade delete |
| Audit logs | 7 years minimum | Pseudonymized on account deletion, never deleted |
| Voice embeddings | Until physician deletes | iOS Keychain entry removal |
| Pilot metrics | Until analysis complete | PostgreSQL delete, pseudonymized on account deletion |

---

## 6. Risk Assessment

### 6.1 Unauthorized Access to Clinical Data

- **Likelihood:** Low
- **Impact:** High
- **Mitigation:** JWT authentication via AWS Cognito, role-based access control (CLINICIAN, EVAL_TEAM, COMPLIANCE_OFFICER, ADMIN), all API endpoints require authentication, clinicians can only access their own sessions, S3 buckets are not publicly accessible, KMS encryption at rest.

### 6.2 Data Breach During Transit

- **Likelihood:** Low
- **Impact:** High
- **Mitigation:** TLS 1.2+ for all API communication, S3 uploads over HTTPS, WebSocket connections secured via WSS, no unencrypted data channels.

### 6.3 AI Provider Data Exposure

- **Likelihood:** Low-Medium
- **Impact:** Medium
- **Mitigation:** Data Processing Agreements (DPAs) with all AI providers, Standard Contractual Clauses (SCCs) for cross-border transfers, on-device PHI masking before any data reaches AI providers, PHI audit via AWS Comprehend Medical on transcripts, AI providers contractually prohibited from training on Aurion data.

### 6.4 AI Hallucination — Fabricated Clinical Content

- **Likelihood:** Medium
- **Impact:** Medium
- **Mitigation:** Descriptive Mode constraint enforced in every AI prompt, mandatory physician review before note approval, citation anchoring traces every claim to a source, completeness scoring flags incomplete sections, CONFLICTS status requires mandatory resolution.

### 6.5 PHI Leakage in Logs or Error Messages

- **Likelihood:** Low
- **Impact:** High
- **Mitigation:** Structured JSON logging with PHI-free policy enforced at code level, automated PHI scanning hooks on every Python file write, audit log records session IDs and event types only (no clinical content), error responses return generic messages without patient data.

### 6.6 Incomplete Data Deletion on Account Deletion

- **Likelihood:** Low
- **Impact:** Medium
- **Mitigation:** Account deletion endpoint performs cascade deletion across PostgreSQL (sessions, note versions, pilot metrics), S3 (audio and frame objects), and writes confirmation to audit log. Audit logs are pseudonymized but retained for regulatory compliance. Deletion results are returned to the user for verification.

### 6.7 Voice Biometric Data Compromise

- **Likelihood:** Very Low
- **Impact:** High
- **Mitigation:** Voice embeddings stored exclusively in iOS Keychain (hardware-encrypted), raw voice recordings deleted immediately after embedding generation, voice data never transmitted to the backend, biometric consent is separate from app consent with explicit acceptance required, physician can delete voice profile at any time from Settings.

### 6.8 Unauthorized Re-identification from Pseudonymized Data

- **Likelihood:** Very Low
- **Impact:** Medium
- **Mitigation:** Audit logs contain only session IDs and event types (no clinical content), pilot metrics contain no PHI, pseudonymization on account deletion replaces clinician identifiers, access to audit logs restricted to COMPLIANCE_OFFICER and ADMIN roles.

---

## 7. Safeguards

### 7.1 Encryption

- **At rest:** AWS KMS encryption for all S3 buckets and RDS PostgreSQL. iOS Keychain uses hardware-backed encryption for voice embeddings.
- **In transit:** TLS 1.2+ for all API calls, S3 uploads, and WebSocket connections.

### 7.2 On-Device PHI Masking

- MediaPipe face detection runs on every video frame before upload.
- Apple Vision OCR identifies and redacts patient identifiers on screen captures before upload.
- Masking status is confirmed in the audit log. No frame is processed by an AI provider without confirmed masking.

### 7.3 Audit Logging

- Every system event is recorded in an append-only DynamoDB audit log.
- No update or delete operations are permitted on the audit log.
- Events include: consent, masking status, session state transitions, AI provider calls (provider name and session ID only — no PHI), configuration changes, data purge confirmations.

### 7.4 Consent Enforcement

- Patient consent must be confirmed before any data capture begins. The record button is physically disabled until consent is recorded.
- Voice enrollment requires separate biometric consent with explicit acceptance.
- All consent events are recorded in the immutable audit log with timestamps.

### 7.5 Role-Based Access Control

| Role | Access |
|---|---|
| CLINICIAN | Own sessions, notes, and data only |
| EVAL_TEAM | Masked transcripts, masked frames, generated notes for quality review |
| COMPLIANCE_OFFICER | Audit logs, masking reports — no raw clinical data |
| ADMIN | Full system access, user management, configuration |

### 7.6 Data Minimization

- Raw audio deleted within 1 hour of transcription.
- Video frames deleted within 24 hours of processing.
- Screen captures deleted within 24 hours of processing.
- Voice embeddings stored on-device only — never transmitted to backend.
- AI provider calls include only the minimum data required for the specific task.

### 7.7 Automated Compliance Checks

- PHI scanning hooks run on every Python file write during development.
- AWS Comprehend Medical audits transcripts for residual PHI.
- CloudWatch alarms monitor masking pipeline failures, consent block failures, and provider fallbacks.

---

## 8. Cross-Border Data Transfers

### 8.1 Data Storage

All persistent data storage is in AWS ca-central-1 (Montreal). This includes S3 buckets, RDS PostgreSQL, DynamoDB audit logs, and Cognito user pools.

### 8.2 AI Provider Processing

Audio, transcript, and masked frame data is transmitted to US-based AI providers (OpenAI, Anthropic, Google, AssemblyAI) for processing. This constitutes a cross-border transfer under Quebec Law 25.

**Safeguards for cross-border transfers:**
- Data Processing Agreements (DPAs) executed with each AI provider.
- Standard Contractual Clauses (SCCs) where applicable.
- AI providers contractually prohibited from using Aurion data for model training.
- On-device PHI masking ensures patient-identifiable information is removed before data reaches any AI provider.
- Audio is transmitted for transcription only and deleted from S3 within 1 hour.
- Masked frames contain no patient-identifiable faces or text.

### 8.3 Adequacy Assessment

The Commission d'acces a l'information (CAI) has not issued adequacy determinations for US-based AI providers. The contractual safeguards (DPAs, SCCs, training prohibitions) and technical safeguards (PHI masking, data minimization, short retention) provide equivalent protection as required by Law 25 Section 17.

---

## 9. Privacy Officer

**Name:** Faical Sawadogo
**Title:** Co-Founder & CTO
**Organization:** Aurion Clinical AI Inc.
**Responsibilities:**
- Oversight of this Privacy Impact Assessment
- Receiving and responding to data access and deletion requests
- Notification to the CAI in case of a confidentiality incident
- Annual review and update of this PIA
- Ensuring all team members are trained on privacy obligations

---

## 10. Review Schedule

This PIA will be reviewed and updated:
- Before any significant change to data collection, processing, or storage practices
- Before expanding beyond the pilot deployment
- After any confidentiality incident
- At minimum, annually from the date of initial assessment

---

*Last updated: 2026-04-11*
