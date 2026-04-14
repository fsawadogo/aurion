# Aurion Clinical AI — Data Breach Incident Response Plan

**Document Version:** 1.0
**Date:** 2026-04-11
**Privacy Officer:** Faical Sawadogo, Co-Founder & CTO
**Applicable Legislation:** Quebec Act Respecting the Protection of Personal Information in the Private Sector (Law 25), PIPEDA

---

## 1. Scope

This plan covers all confidentiality incidents involving personal information processed by Aurion Clinical AI, including but not limited to:

- Unauthorized access to clinical notes, transcripts, or session data
- Unauthorized access to audio recordings, video frames, or screen captures
- Compromise of voice biometric embeddings
- Exposure of personal information through AI provider data breaches
- Unauthorized disclosure of clinician account information
- System compromise affecting data integrity or availability
- PHI leakage in logs, error messages, or API responses

This plan applies to all environments: production, staging, and development (when real data is present).

---

## 2. Definitions

**Confidentiality incident (Law 25, Section 3.5):** Access to, use of, or disclosure of personal information that is not authorized by law, or the loss of personal information or any other breach of the protection of such information.

**Personal information:** Any information that relates to a natural person and allows that person to be identified, directly or indirectly. In the Aurion context, this includes clinician account data, clinical notes, transcripts, audio/video recordings, voice biometric embeddings, and any data that could identify a patient through clinical context.

**Serious incident:** A confidentiality incident that presents a risk of serious injury to the persons concerned. Factors include the sensitivity of the information (health information, biometric data), the anticipated consequences of its use (identity theft, discrimination, health risk), and the likelihood of injurious use.

---

## 3. Detection

### 3.1 Automated Detection

| Detection Method | What It Monitors | Alert Mechanism |
|---|---|---|
| CloudWatch alarms | Masking pipeline failures, consent block failures, provider fallback triggers, unusual API error rates | CloudWatch Alarm to SNS to engineering on-call |
| Audit log anomaly monitoring | Failed authentication attempts, unauthorized role access attempts, unusual data access patterns | Automated scan of DynamoDB audit log entries |
| S3 access logging | Unexpected access to audio, frames, or eval buckets | CloudTrail alerts on non-application access |
| AWS GuardDuty | Account compromise, unusual API calls, credential exfiltration | GuardDuty findings to SNS |
| PHI scan hooks | PHI appearing in application logs or error messages | Development-time detection during code review |

### 3.2 Manual Detection

| Source | How to Report |
|---|---|
| Engineering team | Direct report to Privacy Officer via Slack #security channel or email |
| Clinician report | Report through the app support channel or directly to clinic administration |
| AI provider notification | Monitored via DPA incident notification clauses |
| Third-party security researcher | Responsible disclosure via security@aurionclinical.com |
| Compliance officer audit | Identified during routine audit log review |

---

## 4. Classification

All incidents are classified into severity levels upon initial assessment. Classification determines the urgency of response and notification requirements.

### Severity Level 1 — Critical

**Criteria:** Confirmed unauthorized access to or exfiltration of health information, clinical notes, audio recordings, video frames, or voice biometric data. Large-scale breach affecting multiple clinicians or patients.

**Response time:** Immediate (within 1 hour of detection).

**Notification:** CAI within 72 hours. Affected individuals without undue delay. CREOQ/CLLC administration immediately.

**Examples:**
- Database breach exposing clinical notes or transcripts
- S3 bucket misconfiguration exposing audio recordings or video frames
- Compromise of voice biometric embeddings
- AI provider breach affecting Aurion data

### Severity Level 2 — High

**Criteria:** Unauthorized access to personal information with limited scope (single clinician, limited data). PHI leakage in logs or error messages that reached an external system. Failure of masking pipeline resulting in unmasked data being uploaded.

**Response time:** Within 4 hours of detection.

**Notification:** CAI within 72 hours if risk of serious injury exists. Affected individuals as warranted. CREOQ/CLLC administration within 24 hours.

**Examples:**
- Single clinician's session data accessed by unauthorized role
- Masking pipeline failure resulting in unmasked frame upload to S3
- PHI detected in application logs that were shipped to a logging service
- Consent enforcement bypass (data captured without confirmed consent)

### Severity Level 3 — Low

**Criteria:** Near-miss or contained incident with no confirmed exposure. Vulnerability discovered before exploitation. Internal policy violation with no data exposure.

**Response time:** Within 24 hours of detection.

**Notification:** Internal documentation only. No external notification required unless investigation reveals escalation.

**Examples:**
- Failed attempt to access unauthorized data (blocked by RBAC)
- S3 bucket policy temporarily misconfigured but no access occurred
- Development environment PHI scan caught PHI in a log statement before deployment

---

## 5. Notification Requirements — Quebec Law 25

### 5.1 Commission d'acces a l'information (CAI)

**When:** Within 72 hours of becoming aware of a confidentiality incident that presents a risk of serious injury.

**Method:** Written notification via the CAI's prescribed form.

**Content required:**
- Description of the personal information concerned
- A brief description of the circumstances of the incident
- The date or time period during which the incident occurred, or if unknown, an approximation
- The number of persons concerned, or if unknown, an approximation
- A description of the measures taken or planned to reduce the risk of injury
- Contact information for the person responsible for the protection of personal information

### 5.2 Affected Individuals

**When:** Without undue delay after becoming aware of a confidentiality incident that presents a risk of serious injury.

**Method:** Written notification (email to clinicians, written notice to patients through the clinic).

**Content required:**
- Description of the personal information concerned
- A brief description of the circumstances of the incident
- The date or time period during which the incident occurred
- A description of the measures taken or planned to reduce the risk of injury
- Contact information for the person responsible for the protection of personal information

### 5.3 Notification Decision Matrix

| Data Type Exposed | Scope | Severity | CAI Notification | Individual Notification |
|---|---|---|---|---|
| Clinical notes or transcripts | Any | Level 1 | Required (72h) | Required (without undue delay) |
| Audio recordings | Any | Level 1 | Required (72h) | Required (without undue delay) |
| Video frames (unmasked) | Any | Level 1 | Required (72h) | Required (without undue delay) |
| Voice biometric data | Any | Level 1 | Required (72h) | Required (without undue delay) |
| Clinician account data only | Single user | Level 2 | Required if risk of serious injury | As warranted |
| Session metadata only | Limited | Level 2 | Assess risk | As warranted |
| Masked frames or redacted screens | Any | Level 2 | Assess risk (masking may reduce injury risk) | As warranted |
| Audit log data (pseudonymized) | Any | Level 3 | Not required | Not required |
| Pilot metrics (no PHI) | Any | Level 3 | Not required | Not required |

---

## 6. Response Team

| Role | Person | Responsibilities |
|---|---|---|
| Privacy Officer (Incident Lead) | Faical Sawadogo, CTO | Overall incident coordination, CAI notification, communication with affected individuals, final classification decision |
| Legal Counsel | TBD (retain before pilot launch) | Review notification obligations, draft CAI submission, advise on liability, review public communications |
| Engineering Lead | TBD (assign from engineering team) | Technical containment, forensic analysis, root cause investigation, remediation implementation |
| Clinical Liaison | Dr. Perry Gdalevitch / Dr. Marie Gdalevitch | Communication with clinic administration, patient notification coordination, clinical impact assessment |

---

## 7. Response Steps

### Step 1 — Contain (Immediate)

- Identify the attack vector or source of the incident.
- Isolate affected systems (revoke credentials, disable compromised accounts, block network access).
- If S3 data is exposed: restrict bucket policies immediately, rotate KMS keys if warranted.
- If an AI provider is compromised: disable the provider in AppConfig (takes effect in < 30 seconds), switch to alternate provider.
- If masking has failed: halt all frame uploads, quarantine unmasked data.
- Preserve forensic evidence: snapshot logs, audit trail, CloudTrail records before any remediation.

### Step 2 — Assess (Within 4 Hours)

- Determine the scope: what data was exposed, how many individuals affected, time window of exposure.
- Classify the incident severity (Level 1, 2, or 3).
- Query the DynamoDB audit log for all events related to affected sessions.
- Review CloudTrail for unauthorized API access patterns.
- Review S3 access logs for unauthorized object access.
- Document findings in the incident record.

### Step 3 — Notify (Per Classification)

- **Level 1:** Notify CAI within 72 hours using prescribed form. Notify affected individuals without undue delay. Notify CREOQ/CLLC administration immediately.
- **Level 2:** Assess whether risk of serious injury exists. Notify CAI and individuals as warranted. Notify CREOQ/CLLC within 24 hours.
- **Level 3:** Internal documentation only. Monitor for escalation.

### Step 4 — Remediate

- Fix the root cause (patch vulnerability, correct misconfiguration, update access policies).
- If data was exposed: assess whether exposed data can be recalled or contained.
- If PHI was in logs: purge affected log entries, rotate any exposed credentials.
- Update AppConfig, IAM policies, or bucket policies as needed.
- Deploy fixes through standard CI/CD pipeline with expedited review.

### Step 5 — Verify

- Confirm the root cause is resolved.
- Run automated tests to verify the fix.
- Review audit log to confirm no further unauthorized access after remediation.
- Re-run PHI scan, masking verification, and consent enforcement tests.

### Step 6 — Close and Document

- Complete the incident record in the breach register (see Section 9).
- Brief the response team on resolution.
- Schedule post-incident review within 5 business days.

---

## 8. Post-Incident Review

Every Level 1 and Level 2 incident requires a post-incident review within 5 business days of closure.

**Review agenda:**
1. **Timeline reconstruction** — detailed chronological account of detection, containment, assessment, notification, and remediation.
2. **Root cause analysis** — what failed, why it failed, and what conditions allowed it to occur.
3. **Detection effectiveness** — how was the incident detected, could it have been detected earlier, what monitoring gaps exist.
4. **Response effectiveness** — were response times met, were notification obligations fulfilled, were containment measures sufficient.
5. **Preventive measures** — specific technical and procedural changes to prevent recurrence.
6. **Policy updates** — amendments to this plan, the Privacy Impact Assessment, or the Data Retention Policy if warranted.

**Deliverable:** Written post-incident review report, retained in the breach register.

---

## 9. Breach Register

Quebec Law 25 (Section 3.8) requires maintaining a register of confidentiality incidents. Aurion maintains this register with the following fields for each incident:

| Field | Description |
|---|---|
| Incident ID | Unique identifier |
| Date detected | When the incident was first detected |
| Date contained | When the incident was contained |
| Date closed | When remediation was verified complete |
| Severity level | Level 1, 2, or 3 |
| Description | Brief description of the incident |
| Data types affected | Which categories of personal information were involved |
| Number of individuals affected | Count or estimate |
| Root cause | Summary of root cause analysis |
| CAI notified | Yes/No, date if yes |
| Individuals notified | Yes/No, date if yes, method used |
| Remediation summary | What was done to fix and prevent recurrence |
| Post-incident review date | Date of the review meeting |

The breach register is maintained by the Privacy Officer and retained for a minimum of 5 years from the date of the incident, as required by Law 25.

---

## 10. Training and Awareness

- All team members with access to Aurion systems must be briefed on this plan before the pilot launch.
- The Privacy Officer will conduct an annual review of this plan with the response team.
- New team members must review this plan as part of onboarding.

---

## 11. Plan Review

This plan will be reviewed and updated:
- After every Level 1 or Level 2 incident
- Before any significant change to system architecture or data processing
- Before expanding beyond the pilot deployment
- At minimum, annually from the date of initial publication

---

*Last updated: 2026-04-11*
