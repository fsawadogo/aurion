# Plan — VID-05

## Task
VID-05 — Clinician web upload UI for the encounter-video import (single
presigned PUT), reusing the existing note-review screen for the result.

## Why
Final slice: the human-facing surface for VID-01…04. A clinician uploads a
recorded encounter, watches it process, and reviews the produced note in the
existing `/portal/notes/[id]` screen. Matches the backend I shipped: a single
presigned PUT (not multipart) on the clinician-only `/me/video-imports` surface.

## Approach
- `lib/portal-api.ts` — add `createVideoImport`, `processVideoImport`,
  `getVideoImportStatus` (typed `fetchWithAuth` wrappers) + their types. The raw
  S3 PUT (no bearer) lives in the component via a small XHR helper with
  `upload.onprogress`.
- `components/portal/VideoImportClient.tsx` — phased UI (form → uploading →
  processing → done/error): drag-drop + file picker (mp4/mov/webm, ≤2 GB),
  **required consent attestation** checkbox (the import substitute for the live
  consent gate), metadata (specialty, encounter type [`doctor_patient` /
  `doctor_team_patient` — the two remaining after the `team_patient` removal],
  output language), an upload progress bar, and a processing stepper polling
  `getVideoImportStatus` (~4 s). On `completed` → `window.location` to
  `/portal/notes/{session_id}` (the existing review screen); on `failed` → error
  + retry.
- `app/portal/upload/page.tsx` — thin `"use client"` wrapper.
- `components/Sidebar.tsx` — nav entry `{ tKey: "uploadEncounter", href:
  "/portal/upload", icon: UploadCloud, roles: ["CLINICIAN"] }`.
- `messages/en.json` + `fr.json` — `Sidebar.nav.uploadEncounter` + a
  `VideoImport` namespace (EN + FR at parity).

Reuses: `fetchWithAuth` (bearer + silent refresh), the existing `Card`/`Button`
components + form utility classes, the `Specialties` i18n namespace, and the
existing `NoteReviewClient` for the result (origin-agnostic).

## Acceptance criteria
- [ ] AC-1: `tsc --noEmit` clean; `/portal/upload` builds as a static route.
- [ ] AC-2: the upload button is disabled until a valid file + consent checkbox + specialty are set; bad format / >2 GB show inline errors.
- [ ] AC-3: happy path drives create → PUT (progress) → process → poll → redirect to the note review screen.
- [ ] AC-4: EN + FR string parity for the new keys.

## Out of scope
Admin/eval upload surface, presigned **multipart**/resumable chunking, patient
identifier at create (set later via the existing identifier endpoint), the
"Uploaded" inbox badge, in-browser audio extraction. (Backend single-PUT +
clinician-only is what VID-02 exposed.)

## Test plan (executable)
1. `cd web && npx tsc --noEmit`
2. Manual: `/portal/upload` renders; validation gates; (with `video_import_enabled` on) end-to-end upload → review.

## Security implications
No PHI in query strings (consent + metadata in the JSON create body). The raw
S3 PUT carries no Aurion bearer (presign is the auth). The feature is inert
until the backend flag is enabled (every endpoint 404s while off). Consent
hard-gate honored via the required attestation checkbox → `CONSENT_ATTESTED`.
