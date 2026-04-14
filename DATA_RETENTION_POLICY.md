# Aurion Clinical AI — Data Retention Policy

**Document Version:** 1.0
**Date:** 2026-04-11
**Privacy Officer:** Faical Sawadogo, Co-Founder & CTO
**Applicable Legislation:** Quebec Act Respecting the Protection of Personal Information in the Private Sector (Law 25), PIPEDA

---

## 1. Purpose

This policy defines the retention periods, storage locations, deletion methods, and legal bases for all data types collected and processed by Aurion Clinical AI. It ensures compliance with Quebec Law 25 requirements for data minimization and the right to erasure.

---

## 2. Retention Schedule

| Data Type | Retention Period | Storage Location | Deletion Method | Legal Basis |
|---|---|---|---|---|
| Raw audio recordings | < 1 hour after transcription | S3 `aurion-audio` bucket (ca-central-1, KMS-encrypted) | S3 lifecycle auto-TTL with Lambda confirmation logged to audit trail | Data minimization — audio is an intermediate processing artifact, not a record |
| Video frames (masked) | < 24 hours after processing | S3 `aurion-frames` bucket (ca-central-1, KMS-encrypted) | S3 lifecycle auto-TTL | Data minimization — frames are intermediate processing artifacts |
| Screen captures (redacted) | < 24 hours after processing | S3 `aurion-frames` bucket (ca-central-1, KMS-encrypted) | S3 lifecycle auto-TTL | Data minimization — screen data is extracted and injected into notes |
| Evaluation frames (masked) | Until evaluation complete + deletion request | S3 `aurion-eval` bucket (ca-central-1, KMS-encrypted, access-controlled) | Manual purge with audit log confirmation | Legitimate interest — quality assurance during pilot |
| Session metadata | 7 years from session creation, or upon account deletion request | PostgreSQL RDS (ca-central-1, KMS-encrypted) | PostgreSQL cascade delete; confirmed in audit log | Clinical documentation retention requirements |
| Clinical notes (all versions) | 7 years from note creation, or upon account deletion request | PostgreSQL RDS (ca-central-1, KMS-encrypted) | PostgreSQL cascade delete; confirmed in audit log | Clinical documentation retention requirements; immutable versioning ensures traceability |
| Audit logs | 7 years minimum; pseudonymized upon account deletion | DynamoDB (ca-central-1) | Never deleted — pseudonymized on account deletion by appending `account_deleted` event | Legal obligation — regulatory audit trail; Law 25 incident investigation capability |
| Voice embeddings | Until physician explicitly deletes from device Settings | iOS Keychain (device-local, hardware-encrypted) | Keychain entry removal initiated by physician; `voice_enrollment_deleted` audit event logged | Consent — separate biometric consent required; physician controls deletion |
| Pilot metrics | Until post-pilot analysis is complete; pseudonymized upon account deletion | PostgreSQL RDS (ca-central-1, KMS-encrypted) | PostgreSQL delete; pseudonymized on account deletion | Legitimate interest — model evaluation and quality improvement |
| Account information (Cognito) | Until account deletion request | AWS Cognito (ca-central-1) | Cognito user pool deletion | Contractual — required for authentication and authorization |

---

## 3. Deletion Triggers

### 3.1 Automatic Deletion (System-Enforced)

| Trigger | Data Affected | Mechanism |
|---|---|---|
| Successful transcription | Raw audio recording | S3 lifecycle TTL (< 1 hour) + Lambda cleanup confirmation |
| Note export and approval | Masked video frames, redacted screen captures | S3 lifecycle TTL (< 24 hours) |
| Voice embedding generation | Raw voice recording | Immediate in-memory deletion on device; never persisted to storage |

### 3.2 User-Initiated Deletion

| Trigger | Data Affected | Mechanism |
|---|---|---|
| `DELETE /api/v1/privacy/my-account` | Sessions, note versions, pilot metrics, S3 objects | Cascade delete across PostgreSQL and S3; audit log pseudonymized |
| Voice profile deletion (iOS Settings) | Voice embedding in Keychain | iOS Keychain entry removal; `voice_enrollment_deleted` audit event |

### 3.3 Administrative Deletion

| Trigger | Data Affected | Mechanism |
|---|---|---|
| Evaluation frame purge request | Evaluation bucket objects | Manual purge via admin API with audit confirmation |
| Account deactivation by admin | User access revoked; data retained per schedule | Cognito user disabled; data retained until deletion request or retention expiry |

---

## 4. Retention Justification

### 4.1 Seven-Year Retention for Clinical Data

Session metadata, clinical notes, and audit logs are retained for 7 years based on:
- Quebec professional regulatory requirements for clinical documentation
- Institutional policies at CREOQ/CLLC for medical record retention
- Statute of limitations for medical malpractice claims in Quebec

### 4.2 Short Retention for Raw Capture Data

Raw audio (< 1 hour) and video/screen frames (< 24 hours) are retained only for the minimum time required for processing. These are intermediate artifacts — the clinical note is the record of the encounter, not the raw capture data.

### 4.3 Indefinite Retention for Audit Logs

Audit logs are retained indefinitely (minimum 7 years) because:
- They are required for regulatory compliance investigations
- They provide the only evidence of consent, masking, and data lifecycle events
- They contain no PHI — only session IDs, event types, and timestamps
- They are pseudonymized upon account deletion to remove clinician identity linkage

---

## 5. Data Subject Rights — Quebec Law 25

### 5.1 Right of Access

Clinicians can access all their personal data via `GET /api/v1/privacy/my-data`. This returns account information, sessions, note versions, pilot metrics, consent history, and voice enrollment status.

### 5.2 Right to Portability

Clinicians can export all their personal data in machine-readable JSON format via `GET /api/v1/privacy/export?format=json`.

### 5.3 Right to Erasure

Clinicians can request full account deletion via `DELETE /api/v1/privacy/my-account`. This deletes all sessions, note versions, pilot metrics, and S3 objects. Audit logs are pseudonymized but retained per regulatory requirements.

### 5.4 Right to Withdraw Consent

- Patient consent can be withdrawn at any time during a session (session transitions to terminal state).
- Biometric consent (voice enrollment) can be revoked at any time via iOS Settings, which deletes the voice embedding.
- Consent withdrawal is recorded in the immutable audit log.

---

## 6. Compliance Verification

| Verification Method | Frequency | Responsible Party |
|---|---|---|
| S3 lifecycle policy audit | Monthly | Engineering |
| Audit log completeness check (purge confirmations) | Per session | Automated |
| Retention period review | Annually | Privacy Officer |
| Account deletion end-to-end test | Quarterly | Engineering |
| Voice embedding isolation verification (network audit) | Quarterly | Engineering |

---

## 7. Policy Review

This policy will be reviewed and updated:
- Before any change to data collection or storage practices
- Before expanding beyond the pilot deployment
- After any confidentiality incident involving data retention
- At minimum, annually from the date of initial publication

---

*Last updated: 2026-04-11*
