---
name: voice-enrollment-spec
description: >
  Load when working on iOS onboarding, voice enrollment, speaker separation,
  hardware requirements, or iPhone/iPad universal app. Contains full voice enrollment
  flow with screen-by-screen UI spec, all privacy rules, technical implementation
  with SpeechBrain/Apple SFSpeakerRecognition, speaker separation logic, device
  requirements table, and hardware specs for development and pilot. Auto-invoked
  when editing ios/Aurion/Onboarding/ or backend/app/modules/onboarding/.
user-invocable: true
---

# Aurion Voice Enrollment and Hardware Specification

## Voice Enrollment — Overview

**MVP scope. Voice only. Face enrollment deferred to v1.**

On first launch — after login and wearable setup, before the dashboard — physician goes through a one-time voice enrollment flow. Creates a voice embedding stored exclusively on-device. Used during sessions to separate physician speech from patient speech in the transcript.

### Why It Matters

Without enrollment: transcript is undifferentiated. Trigger classifier cannot distinguish physician observations from patient reports. Clinical statements ("range of motion is restricted") and patient reports ("it hurts when I move it") treated equally.

With enrollment: every transcript segment tagged `speaker: physician` or `speaker: other`. Physician-tagged segments weighted higher for visual trigger detection. Patient speech retained as context but does not drive frame extraction or note generation.

---

## Privacy Rules — Non-Negotiable

| Rule | Implementation |
|---|---|
| Raw voice recording deleted immediately | Deleted from memory immediately after embedding generation. Never written to disk, never uploaded. |
| Embedding stored on-device only | iOS Keychain under key `aurion.physician.voice_embedding`. Encrypted. Never transmitted to backend. |
| Biometric consent separate from app consent | Own screen, own legal text, must be reviewed by legal before pilot launch. |
| Skip always available | Physician can skip. System works without enrollment — no speaker separation, trigger classifier uses all segments. |
| Re-record and delete in Settings | Re-record overwrites Keychain entry. Delete removes entry, reverts to no-enrollment mode. Both audit logged. |
| Backend never receives voice data | Zero cloud footprint for biometric data. Audit log entry is `voice_enrollment_complete` with timestamp + device ID only — no embedding. |

---

## Onboarding Flow — iOS Onboarding/ Module

### Flow Sequence
First launch only: Login → Wearable Setup → Voice Enrollment → Dashboard

### Screen 1 — Explanation (shown before any recording prompt)

```
Heading:  "Help Aurion recognize your voice"

Body:     "Aurion uses a short voice sample to separate your observations
           from your patient's during visits.

           Your recording is processed on this device only and deleted
           immediately. Nothing is sent to our servers."

Buttons:  [Get started]     ← gold, primary
          [Skip for now]    ← muted, secondary
```

If physician taps "Skip for now" → proceed directly to Dashboard. Log `voice_enrollment_skipped` to audit trail.

### Screen 2 — Biometric Consent (shown only if "Get started" tapped)

Full biometric consent statement — legally reviewed before pilot. Physician must actively accept — no implicit consent. Tapping "I agree" logs `biometric_consent_confirmed` to audit trail. Back button returns to Screen 1 — skip always possible.

### Screen 3 — Recording Prompt

```
Instruction: "Read the following sentences aloud in your normal clinical voice:"

Sentences (rotate from pool — varied phoneme coverage):
  "Range of motion is restricted to approximately 90 degrees of flexion."
  "There is tenderness on palpation at the medial joint line."
  "The wound edges appear well approximated with no signs of infection."
  "I am reviewing the imaging now — there is no visible fracture displacement."
  "Grip strength is reduced at approximately 3 out of 5 on the right side."
  "The patient demonstrates antalgic gait favoring the left lower extremity."

UI:   Large gold record button — tap to start, tap to stop
      Visual audio waveform while recording
      "Re-record" option always visible
```

Target: 30–60 seconds of speech. Minimum: 3 sentences. If physician taps stop before 3 sentences, prompt to continue.

### Screen 4 — Processing and Confirmation

```
Processing: "Creating your voice profile..." + spinner (< 2 seconds on-device)

On success:
  Gold checkmark icon
  "Voice profile saved to this device."
  "You can update or delete your voice profile anytime in Settings."

Audit log: voice_enrollment_complete
  { clinician_id, device_id, timestamp }  ← no embedding data, no audio
```

Raw audio deleted from memory immediately after embedding generated — before Screen 4 renders.

---

## Technical Implementation — iOS

### Library Options (evaluate both in Phase 7)

**Option A — SpeechBrain Core ML**
- Model: `EncoderClassifier` (speaker verification)
- Convert to Core ML via `coremltools` before embedding in app
- Runs on-device via CoreML framework
- Output: 256-dimension embedding vector

**Option B — Apple SFSpeakerRecognition** (iOS 17+)
- Native Apple framework — no third-party dependency
- Simpler integration, Apple-managed updates
- Output: speaker embedding in opaque format

**Recommendation:** implement Option B first (simpler, native). Fall back to Option A if SFSpeakerRecognition accuracy is insufficient on clinical vocabulary.

### Enrollment Process

```swift
// 1. Record audio via AVAudioEngine
// 2. Pass buffer to speaker model → generate 256-dim embedding
// 3. Delete raw audio buffer from memory immediately
// 4. Store embedding in Keychain
let embeddingKey = "aurion.physician.voice_embedding"
let keychain = KeychainWrapper.standard
keychain.set(embeddingData, forKey: embeddingKey, withAccessibility: .whenUnlockedThisDeviceOnly)
// 5. Write audit event (no embedding data)
AuditLogger.log(.voiceEnrollmentComplete, deviceId: UIDevice.current.identifierForVendor)
```

### Session-Time Speaker Separation

```swift
// At session start — load embedding
guard let embeddingData = KeychainWrapper.standard.data(forKey: "aurion.physician.voice_embedding"),
      let embedding = SpeakerEmbedding(data: embeddingData) else {
  // No enrollment — proceed without speaker separation
  return
}

// Per transcript segment — compare against enrollment embedding
func tagSpeaker(segment: TranscriptSegment, enrollment: SpeakerEmbedding) -> String {
  let segmentEmbedding = speakerModel.embed(audio: segment.audioBuffer)
  let similarity = cosineSimilarity(segmentEmbedding, enrollment)
  return similarity > 0.85 ? "physician" : "other"
}
```

### Updated Transcript Segment Schema (enrolled sessions)

```json
{
  "id": "seg_001",
  "start_ms": 14200,
  "end_ms": 17800,
  "text": "There is tenderness on palpation at the medial joint line.",
  "speaker": "physician",
  "speaker_confidence": 0.94,
  "is_visual_trigger": true,
  "trigger_type": "active_physical_examination"
}
```

Non-enrolled sessions: `speaker` field omitted. Trigger classifier runs on all segments.

### Settings Screen Additions

- "Voice Profile" section: enrollment date, device name
- "Re-record voice profile" → runs enrollment flow, overwrites Keychain entry
  - Audit log: `voice_profile_updated`
- "Delete voice profile" → removes Keychain entry, reverts to no-enrollment mode
  - Audit log: `voice_profile_deleted`

---

## iPhone and iPad — Universal App

**Single SwiftUI codebase. One target. One binary. One App Store submission. Full feature parity.**

### Platform Requirements

| Device | Minimum | Recommended | On-device ML |
|---|---|---|---|
| iPhone | iPhone 13 (A15 Bionic), iOS 16 | iPhone 15 Pro (A17 Pro), iOS 17 | ✓ Full performance |
| iPad | iPad mini 6 (A15 Bionic), iPadOS 16 | iPad Pro M2+, iPadOS 17 | ✓ Full performance |
| iPad (soft minimum) | iPad Air 5 (M1), iPadOS 16 | — | ✓ Full performance |
| iPad (not recommended) | iPad 9th gen (A13), iPadOS 16 | — | ⚠ Masking pipeline slow |

A15 Bionic is the practical minimum for acceptable MediaPipe face detection latency and CoreML speaker embedding generation. A13 devices run the app but on-device ML degrades — not recommended for clinical use.

### Adaptive Layout

| Layout Element | iPhone | iPad |
|---|---|---|
| Capture screen | Full-screen minimal | Full-screen minimal |
| Note review | Scrollable section cards, single column | Two-column split view — section list left, content right |
| Conflict resolution | Stacked audio + visual | Side by side without scrolling |
| Dashboard | Session list | More sessions per screen |
| Onboarding/consent | Full width | Centred with max-width constraint |

Implementation: `NavigationSplitView` + `@Environment(\.horizontalSizeClass)`. **No separate iPad view files.** If a view is identical on both devices, it is not duplicated.

### iPad as Capture Device

When iPad is the capture device (propped on stand — fallback capture mode):
- Front or rear camera based on exam room setup
- Audio via iPad built-in microphone or connected external mic
- Screen capture runs on the iPad itself — no separate device needed
- BLE pairing with smart glasses works identically to iPhone

### iPad as Review Device

Common workflow: capture on iPhone (paired with glasses), review and approve notes on iPad at desk. App syncs session state via backend — physician logs into same account on both devices. Notes pending review appear on whichever device they open.

**One active capture session per account at a time.** If a session is active on iPhone, iPad shows it as active but cannot initiate a new one.

---

## Hardware Requirements

### Development

| Component | Minimum | Recommended |
|---|---|---|
| Backend dev machine | 16GB RAM, SSD, any OS | Apple M3 Pro 32GB |
| iOS/iPad dev machine | Mac, Xcode 15+, macOS Ventura | Mac M3 Pro, macOS Sonoma |
| Physical test device (iPhone) | iPhone 13 (A15 Bionic) | iPhone 15 Pro (A17 Pro) |
| Physical test device (iPad) | iPad mini 6 (A15) or iPad Air 5 (M1) | iPad Pro M2 or M3 |
| Local Whisper testing | Apple M1 16GB or NVIDIA RTX 3070 (8GB VRAM) | Apple M3 Pro 32GB or NVIDIA RTX 4070 (12GB VRAM) |

**iOS Simulator cannot test: AVFoundation capture, BLE pairing, on-device CoreML, or MediaPipe masking. Physical devices are mandatory for meaningful capture and masking pipeline testing.**

### Pilot Hardware — CREOQ/CLLC

| Item | Quantity | Notes |
|---|---|---|
| Ray-Ban Meta Smart Glasses Gen 2 | 1 per pilot physician (3–5 pairs) | ~$350 CAD each. Primary capture device. 4h battery. |
| Charging cases | 1 per pair | Full clinic day requires mid-day charge or spare pair. |
| Insta360 GO 3 body cameras | 2 units | ~$400 CAD. Backup capture device. Also useful for dev testing before glasses arrive. |
| iPhones (A15 minimum) | 1 per pilot physician | iPhone 13+. Physicians may use their own. |
| iPads (A15 minimum, optional) | 1–2 units | For note review at desk. iPad mini 6 or iPad Air 5 minimum. |
| Clinic WiFi | 5GHz, ≥ 10 Mbps upload per session | Reliable signal in exam rooms — not just hallways. Confirm before pilot launch. |

**Pre-pilot hardware checklist:**
- Confirm pilot physicians are on iPhone 13+ (or provide devices)
- Confirm clinic WiFi coverage in exam rooms — test with iperf or speedtest from exam room
- Charge all glasses pairs to 100% before each clinic day
- Establish mid-day charging protocol for 8+ hour clinic days
- Test BLE pairing in exam room before pilot begins — distance and interference matter

### AWS Cloud Infrastructure

| Service | MVP Config | Notes |
|---|---|---|
| Whisper ECS GPU instance | `g4dn.xlarge` (NVIDIA T4, 16GB VRAM) | ~$0.53/hr. Non-concurrent sessions — sufficient for pilot. |
| ECS Fargate (FastAPI) | Serverless | Auto-scales. Minimal cost at pilot scale. |
| RDS PostgreSQL | `db.t3.medium` | Encrypted, ca-central-1. |
| S3, DynamoDB, KMS, Cognito, AppConfig | Serverless | Negligible cost at pilot scale. |

**Post-pilot GPU upgrade:** If concurrent sessions become common, upgrade to `g5.xlarge` (NVIDIA A10G, 24GB, ~$1.01/hr) or evaluate AWS Inferentia2.

---

## What Is NOT Built for MVP

- **Face enrollment** — deferred to v1. Lower value in Clinic Mode (physician wears glasses — already their POV). Higher compliance complexity. Re-evaluate for Post-Op Mode.
- **Cloud voice verification** — all voice processing on-device. No voice data ever leaves iPhone or iPad.
- **Multi-physician device sharing** — one physician per device for MVP.
- **Automatic re-enrollment prompts** — physician manually re-records from Settings if needed.
