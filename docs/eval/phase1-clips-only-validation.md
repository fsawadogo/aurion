# Phase 1 dual-mode validation — clips_only test session

**Audience:** eval team (Faïcal + Dr. Marie or Dr. Perry).
**Goal:** capture one real ROM exam in `clips_only` mode and verify the dual-mode pipeline produces a clinically usable, descriptive-mode-clean note before authorizing the 20-session Phase 2 evaluation harness.
**Time budget:** ~30 minutes total — 5 min setup, 10 min recording, 5 min Stage 2 wait, 10 min review + verdict.
**Cost:** ~$0.50 in Gemini vision API spend (one session, ~30 trigger-extracted clips).

---

## Prerequisites

- iPhone running **TestFlight build 193** (Aurion · 1.0).
- A Cognito CLINICIAN account. Recommended: use the dedicated test account so this session doesn't pollute either of your real inboxes.
  ```
  Email:    clinician-test@aurionclinical.com
  Password: Aurion-Clinician-d1782b52!
  Pool:     ca-central-1_jWbQUgzbS  (aurion-dev)
  Role:     CLINICIAN
  ```
- Terminal with `curl` + `jq` + AWS CLI configured for `aurion-dev`.
- Test patient identifier — use a synthetic one like `ROM-EVAL-001`. **Do not use a real MRN** for this session.
- About 5 minutes of motion to record (recommend right shoulder abduction + external rotation + flexion).

---

## Step 1 — Get a JWT for the test account

The iOS app holds its own JWT after login, but we need one in the shell to POST the override session. Use Cognito to mint one:

```bash
export USERNAME="clinician-test@aurionclinical.com"
export PASSWORD="Aurion-Clinician-d1782b52!"
export USER_POOL_ID="ca-central-1_jWbQUgzbS"
export CLIENT_ID="$(aws cognito-idp list-user-pool-clients \
  --user-pool-id "$USER_POOL_ID" \
  --region ca-central-1 \
  --query 'UserPoolClients[0].ClientId' \
  --output text)"

export JWT=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id "$CLIENT_ID" \
  --auth-parameters USERNAME="$USERNAME",PASSWORD="$PASSWORD" \
  --region ca-central-1 \
  --query 'AuthenticationResult.IdToken' \
  --output text)

echo "${JWT:0:40}…"  # sanity check — should be a JWT header.payload.sig
```

Expected: a long base64-ish string printed (no error). If you get `NotAuthorizedException`, the password rotated — let Faïcal know.

---

## Step 2 — Create the override session

```bash
export API_BASE="https://api-dev.aurionclinical.com"

curl -sS -X POST "$API_BASE/api/v1/sessions" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
        "specialty": "orthopedic_surgery",
        "external_reference_id": "ROM-EVAL-001",
        "provider_overrides": {
          "visual_evidence_mode": "clips_only",
          "vision_clip": "gemini"
        }
      }' \
  | jq '.'
```

Expected response (201 Created):

```json
{
  "id": "<UUID>",
  "clinician_id": "<UUID>",
  "specialty": "orthopedic_surgery",
  "state": "IDLE",
  "encounter_type": "doctor_patient",
  "external_reference_id": "ROM-EVAL-001",
  "provider_overrides": {
    "visual_evidence_mode": "clips_only",
    "vision_clip": "gemini"
  },
  ...
}
```

✅ **Pass:** `provider_overrides.visual_evidence_mode == "clips_only"` round-trips on the response.
❌ **Fail:** 400 with `"per-session visual_evidence_mode override is disabled"` → the feature flag was flipped off; ping Faïcal.

Capture the `id` for later:

```bash
export SESSION_ID="<paste-the-id-from-above>"
```

---

## Step 3 — Confirm the audit event was written

```bash
curl -sS "$API_BASE/api/v1/me/audit?session_id=$SESSION_ID&event_type=visual_evidence_mode_override_set" \
  -H "Authorization: Bearer $JWT" \
  | jq '.items[] | {event_type, details}'
```

Expected:

```json
{
  "event_type": "visual_evidence_mode_override_set",
  "details": {
    "mode": "clips_only",
    "actor_id": "<UUID>",
    "actor_role": "CLINICIAN"
  }
}
```

✅ **Pass:** event present, `mode == "clips_only"`, no PHI in payload.
❌ **Fail:** empty `items` → audit emit path didn't fire; capture the response and ping Faïcal.

---

## Step 4 — Open the session in TestFlight

1. Sign into the Aurion iOS app on your iPhone as **clinician-test@aurionclinical.com** (same password as above).
2. The sessions inbox should show the session you just created — look for the `ROM-EVAL-001` identifier chip.
3. Tap it. The capture screen opens.

✅ **Pass:** the session appears in the inbox with the `ROM-EVAL-001` chip; tap opens the capture view.
❌ **Fail:** session missing → likely a token/role mismatch; verify the JWT in step 1 was for the same user you signed into the iOS app with.

---

## Step 5 — Record the ROM exam

Position the iPhone so the patient's right shoulder + upper torso is in frame. The face will be auto-masked on-device before any upload — you don't need to crop manually.

**Script (read aloud — these phrases prime the visual trigger classifier):**

> "We'll be looking at right shoulder range of motion."
>
> **(have the patient demonstrate active abduction)** — say "Let me see active abduction." Pause 5 seconds. "Now external rotation." Pause 5 seconds. "Now forward flexion." Pause 5 seconds.
>
> **(passive on physician's hand)** — "Now I'll move your arm through the range — relax. Abduction." Pause. "External rotation." Pause. "Flexion." Pause.
>
> "Patient demonstrated approximately {degrees} of abduction before the pain limit, with visible wincing at the endpoint."

The phrases like *"let me see"*, *"abduction"*, *"external rotation"*, *"flexion"*, *"demonstrated"* are the seeded visual trigger keywords — each one should fire a 7-second clip extraction around the timestamp.

**Total recording time:** ~3–5 minutes. Don't go longer than 10 minutes — Stage 2 cost scales with clip count.

Tap **Stop**. Confirm the pause/stop flow lands you on the review screen.

---

## Step 6 — Watch Stage 2 process

The review screen shows a **"Visual enrichment running"** banner with a counter: `Processing N of M clips…`. This is the Stage 2 progress WebSocket from P1-3.

✅ **Pass:** counter advances; banner clears within ~3 minutes for a 5-minute recording.
⚠ **Acceptable:** stays under 5 minutes (Stage 2 SLA budget per CLAUDE.md).
❌ **Fail:** counter stuck at 0 for > 60 seconds → backend Stage 2 dispatcher likely failed to route to Gemini. Pull logs from CloudWatch (`aurion-dev/api`) and grep for the session id's 8-char prefix.

---

## Step 7 — Verify chips render with play indicators

In the populated note, every section that was visually enriched should show citation chips below the section text. Each chip displays a single-letter source code:

- **T** — transcript anchor (audio segment)
- **V** — visual anchor (frame or clip)
- **S** — screen anchor (OCR'd EMR or lab content)
- **E** — physician edit

Per P1-6, **V chips backed by a clip-kind citation get a small play-triangle overlay** at the trailing-bottom of the chip. V chips backed by frames stay flat.

✅ **Pass:** at least 80% of the V chips on this session show the play-triangle overlay (we're in `clips_only` mode — every visual citation should be clip-kind).
❌ **Fail:** no play triangles on any V chips → the citation `evidence_kind` field isn't decoding. Inspect the network response via Charles or screenshot the chip + screenshot the request payload.

---

## Step 8 — Tap a clip chip; verify the AVPlayer opens

Tap a V chip with a play-triangle. The expected behavior (per P1-6 + P1-6-FU):

1. A full-screen `FullClipView` presents with a black background.
2. Title bar shows the timestamp (e.g. `0:42`).
3. **The AVPlayer auto-plays the masked clip**, looping on end.
4. Close button in the top-right (gold) dismisses.

✅ **Pass:** clip plays without an error sheet.
❌ **Fail:** "Clip not yet available" alert → the signed URL didn't reach the citation. Could mean S3 LIST returned empty (clips weren't uploaded) or the resolver hit an exception. Capture the screenshot + check the citation's JSON in the network response.

**Verify masking:** during playback, observe that the patient's face is blurred. If you see an unblurred face at any frame of the clip, **STOP and alert Faïcal** — this is a P0-01 masking failure and means the entire dual-mode pipeline ships with a privacy regression.

---

## Step 9 — Read each clip's description against the descriptive-mode rubric

For each clip-kind citation, tap it (or read the citation expansion text on the review screen). Look at the `visual_description` field.

**The descriptive-mode boundary (CLAUDE.md):**

| Pass rubric | Fail rubric |
|---|---|
| "Patient demonstrated active abduction reaching approximately 140 degrees, with visible wincing as motion stopped." | "Restricted abduction at 140 degrees is consistent with rotator cuff pathology." |
| "Right hand visible on the patient's lateral upper arm, applying gentle pressure." | "Manual muscle testing reveals weakness consistent with C5 radiculopathy." |
| "Patient's right arm visible at approximately 90 degrees of forward flexion, with the elbow held in extension." | "Range of motion is below normal; consider further imaging." |
| "Equipment visible — goniometer on the patient's right shoulder, reading approximately 145 degrees." | "Reduced range — likely adhesive capsulitis." |

For each clip:

- ✅ **Pass:** description names what is **observable** — body parts, motion, position, equipment, screen content.
- ❌ **Fail:** any phrase that diagnoses ("rotator cuff", "capsulitis"), interprets ("consistent with", "suggests"), recommends ("consider", "should"), or grades ("normal", "abnormal", "reduced").

**Verdict criteria:**

- **All clips pass** → Phase 2 evaluation harness has clinical cover; commit to the 20-session run.
- **1–2 clips fail** → the prompt is good but the model is occasionally drifting on motion observations. Tighten the descriptive-mode system prompt in `backend/app/modules/providers/vision/gemini.py:VISION_SYSTEM_PROMPT` before Phase 2.
- **≥3 clips fail** → the prompt isn't strong enough to hold Gemini to descriptive mode in motion contexts. Iterate on the prompt + ship a corrective PR before Phase 2.

Record findings:

```
Session: <SESSION_ID>
Clips total: ___
Clips passing descriptive-mode: ___
Clips failing — sample text:
  1. "..."
  2. "..."
Verdict: GO | TIGHTEN-PROMPT | BLOCK
```

---

## Step 10 — Latency + cost sanity check

After approval, pull the pilot_metrics row for this session:

```bash
curl -sS "$API_BASE/api/v1/me/audit?session_id=$SESSION_ID" \
  -H "Authorization: Bearer $JWT" \
  | jq '[.items[] | select(.event_type=="stage2_complete" or .event_type=="stage1_delivered") | {event_type, event_timestamp}]'
```

Compute Stage 2 latency = `stage2_complete` ts − `stage1_delivered` ts (in seconds).

| Metric | Target | Actual |
|---|---|---|
| Stage 1 latency | < 30 s | _____ |
| Stage 2 latency | < 5 min | _____ |
| Clips processed | (record) | _____ |
| Clips discarded (low confidence) | (record %) | _____ |

### ⚠ Provider-fallback sanity check

Before computing the cost above, scan the citations for `degraded_to_frame`. If **every** clip citation has `degraded_to_frame=true`, your `vision_clip=gemini` provider failed and the fallback chain extracted midpoint stills instead — you were testing OpenAI or Anthropic's *frame* description path in a `clips_only` session, not Gemini's native video understanding. Don't draw conclusions from that run — confirm Gemini credentials + quota and re-record.

If only a small fraction (say <20%) of clips show `degraded_to_frame=true`, the primary worked for most of the session and you can still draw conclusions — note the affected citation IDs in the report.

For vision API cost, check the CloudWatch logs for `aurion-dev/api`:

```bash
aws logs filter-log-events \
  --log-group-name '/ecs/aurion-dev/api' \
  --filter-pattern "provider_used=gemini caption_clip" \
  --start-time $(date -v-1H +%s)000 \
  --region ca-central-1 \
  | jq -r '.events[].message' | head -50
```

Each log line carries the provider's token usage. Sum input + output tokens × Gemini's per-token rates ($1.25/MT input, $5/MT output) for the cost.

---

## What to send back

When you're done, reply to the eval-team Slack thread (or email Faïcal directly) with:

1. The session UUID
2. The verdict from step 9 (GO / TIGHTEN-PROMPT / BLOCK)
3. The latency + cost numbers from step 10
4. Any clip URLs that surfaced an unblurred face (P0-01 escalation)
5. Optional: 2–3 representative `visual_description` strings — best, worst, average — so future eval runs have grounded examples

If the verdict is **GO**, Phase 2 (20-session evaluation harness, all three vision providers) gets greenlit and Faïcal scopes the next PR.
