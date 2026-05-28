# AssemblyAI Transcription — Law 25 / DPA Assessment & Go-Live Gate

**Status:** ⛔ NOT cleared for real patient audio. Dev/test audio only.
**Owner:** CTO (Faïçal Sawadogo) · **Reviewer:** Compliance Officer
**Created:** 2026-05-28 · **Related:** [`PRIVACY_IMPACT_ASSESSMENT.md`](PRIVACY_IMPACT_ASSESSMENT.md), [`DATA_RETENTION_POLICY.md`](DATA_RETENTION_POLICY.md)

---

## 1. Why this exists

Aurion's transcription provider is runtime-switchable via AppConfig
(`providers.transcription` → `whisper` | `assemblyai`). For the dev
environment we switched to **AssemblyAI** because the self-hosted Whisper
service was unavailable (see infra PRs #38/#39).

AssemblyAI is a **US-based** cloud vendor. Routing physician–patient
**audio** (which contains health information and identifiable voices) to it
is a **cross-border transfer of personal information** under Quebec's
**Law 25** and **PIPEDA**. The PIA already names this transfer and its
intended legal basis ("DPA, SCCs"), but that basis is currently **assumed,
not executed**. This document is the checklist that must be **complete and
signed off before any real patient audio is transcribed by AssemblyAI**.

The compliance-clean alternative requires **no transfer at all**: keep
`providers.transcription = whisper` (self-hosted in `ca-central-1`). That is
the default for production unless this gate is cleared.

## 2. Data that would leave Canada

| Item | Sent to AssemblyAI? | Notes |
|---|---|---|
| Raw encounter audio (WAV) | **Yes** | Contains voices (biometric) + spoken clinical info |
| Transcript text | No | Returned by AssemblyAI; stored in our DB (ca-central-1) |
| Patient identifiers | Only if spoken aloud in audio | No structured PHI fields are sent |
| Video frames / screen captures | No | Different pipeline; not part of transcription |

Audio is deleted from our S3 within ~1 hour of transcription
(`DATA_RETENTION_POLICY.md`), but **AssemblyAI's** retention is governed by
*their* contract, not ours — hence the checklist below.

## 3. Go-live checklist (all must be ✅ before real patient audio)

### Contractual
- [ ] **Signed DPA** with AssemblyAI covering health information as a processor.
- [ ] **SCCs / transfer mechanism** for Canada→US personal-information transfer.
- [ ] **No-training clause** — AssemblyAI contractually prohibited from training models on Aurion data.
- [ ] **Sub-processor list** obtained and reviewed; onward-transfer terms acceptable.
- [ ] **Breach-notification** obligations + timelines defined in the DPA.

### Technical / configuration
- [ ] **Zero-retention / no-storage** mode enabled on the AssemblyAI account (audio + transcripts deleted immediately after processing), and verified in writing.
- [ ] **Data region** confirmed — use a Canadian/region-pinned endpoint if AssemblyAI offers one; otherwise document the US transfer explicitly.
- [ ] **Security posture** reviewed — SOC 2 Type II and (if available) HIPAA BAA on file.
- [ ] **API key** scoped + stored only in Secrets Manager (already the case: `ASSEMBLYAI_API_KEY`).
- [ ] **TLS in transit** confirmed (AssemblyAI API is HTTPS — verify no plaintext path).

### Law 25 process
- [ ] **PIA updated** — promote the AssemblyAI row from "assumed" to "executed" with the signed-DPA reference and date.
- [ ] **Patient transparency / consent language** reviewed by counsel — does the existing consent flow adequately disclose cross-border transfer for transcription?
- [ ] **Data-residency risk** formally accepted (or rejected) by the privacy lead, in writing.
- [ ] **Record of the cross-border transfer** added to the Law 25 register.

### Engineering guardrail
- [ ] A guard prevents `providers.transcription = assemblyai` in the **prod** AppConfig until this gate is signed off (today prod defaults to `whisper`; do not flip without this doc complete). Consider a CI check that fails if prod tfvars/AppConfig sets `assemblyai` while this doc's status is not "cleared".

## 4. Decision matrix

| | AssemblyAI (cloud) | Self-hosted Whisper (ca-central-1) |
|---|---|---|
| Cross-border transfer | **Yes** (US) — needs DPA/SCCs/PIA | **No** — audio stays in Canada |
| Law 25 burden | High (transfer assessment, consent) | Low (no transfer) |
| Quality (EN) | Excellent | Very good (large-v3) |
| Quality (FR — Quebec) | Verify on real clinic audio | Strong (large-v3 multilingual) |
| Cost | ~$0.12–0.37/hr audio, no ops | EC2/GPU running cost + ops |
| Ops burden | None (managed) | Own uptime, scaling, service discovery |
| Latency / reliability | Consistent, managed | Depends on our hardware |

## 5. Recommendation

- **Dev / product validation:** AssemblyAI is fine — use **synthetic/test audio only**, no real patient recordings, while we validate the product and compare FR/EN transcription quality.
- **Production / real patients:** default to **self-hosted Whisper in `ca-central-1`** (no transfer) **unless** every box in §3 is checked and signed off. The provider abstraction makes this a per-environment AppConfig setting — no code change.
- Keep both providers wired (done) so the switch is operational either way.

## 6. Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| CTO | Faïçal Sawadogo | ☐ pending | |
| Compliance Officer | | ☐ pending | |
| Legal / Privacy counsel | | ☐ pending | |

> Until this table is signed and §3 is complete, **prod transcription stays on Whisper**.
