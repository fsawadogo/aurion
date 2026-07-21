# Plan — TE-4b

## Task

TE-4b — show that generation and regeneration are working, and stop the note's actions from reading a superseded note while it is being replaced.

## Why

Found by Uzziel on the first real prod upload, 2026-07-20. Two distinct gaps, one of which is a correctness bug rather than polish.

**1. A working import looks like a hung page.** The upload stepper's active stage is a **static** gold dot (`VideoImportClient.tsx:643-648`) — no motion of any kind. "Extracting audio" on a real encounter video takes minutes, and for that whole time the page is pixel-identical to a frozen one. Polling failure is *already* handled (`lib/poll.ts` — 5 consecutive errors → "lost contact" + a pointer to My Notes, from an earlier stuck-import fix), so this is not about errors. It is about never showing that work is in progress.

**2. Note actions read a note that is being replaced.** During regeneration the only feedback is a small grey caption (`NoteReviewClient.tsx:394-396`), and:

| control | disabled while regenerating? |
|---|---|
| `NoteSectionCard` (inline edit) | ✅ via `busy` |
| template picker / language | ✅ |
| **Print** | ❌ |
| **Export DOCX** | ❌ (`disabled` checks only `exporting` + `can_export`) |
| **Copy** | ❌ (no disabled at all) |

Meanwhile the note body renders the **old** note at full opacity, so nothing signals it is superseded. A clinician can copy, print or export mid-regeneration and get the version that is about to be thrown away. That is the bug; the rest is the missing signal that would have prevented it.

Satisfies backlog `Cohort 7 · TE-4b`.

## Approach

**One derived "the note is not stable right now" value, and one progress component.** The bug exists because "busy" is currently expressed three different ways in one file, and the three action buttons were simply not part of any of them.

1. **`noteBusy`** — a single derived boolean in `NoteReviewClient`:
   `regenerating || approving || session_state === "PROCESSING_STAGE2"`.
   That expression already exists verbatim as the `busy` prop passed to every `NoteSectionCard` (`:441`); it becomes the one source of truth and is applied to Print, Export and Copy too. Fixing the *class* (any control that reads the note) rather than the three instances.

2. **`components/ui/ProgressBanner.tsx`** — extract the presentation already established by `StageTwoProgressBanner` (spinning `RefreshCw`, `role="status"` + `aria-live="polite"`, a 1.5px track with a filling bar, `width: 10%` when no total is known). Supports **determinate** (Stage 2, which has frame counts) and **indeterminate** (regeneration, which is a single POST with no progress events).
   `StageTwoProgressBanner` is refactored onto it — presentation only, no logic change, asserted by its existing behaviour.

3. **Regeneration** renders `ProgressBanner` indeterminate above the note, and the note body gets `aria-busy` + reduced opacity so it reads as superseded rather than current.

4. **Upload stepper** — the active stage dot animates (`aurion-pulse`, already in the Tailwind config) and an elapsed timer appears, so a long stage is visibly *working*.

5. **`aurion-indeterminate`** keyframes added to `tailwind.config.ts`, matching the existing `aurion-*` animation naming.

**Not a WebSocket.** Regeneration is one request that returns when it is done; there is nothing to subscribe to. An indeterminate bar is the honest representation, and pretending to know a percentage would be worse than showing none.

## Acceptance criteria

- [ ] **AC-1:** while regenerating, Print / Export / Copy are all disabled — `tests/NoteReviewProgress.spec.tsx::blocks every action that reads the note`
- [ ] **AC-2:** the same holds during approval and `PROCESSING_STAGE2` (one derived value, not three) — `::blocks actions for every unstable state`
- [ ] **AC-3:** a progress banner appears while regenerating and disappears after — `::shows a progress banner while regenerating`
- [ ] **AC-4:** the note body is marked `aria-busy` while regenerating, so it is announced as stale — `::marks the note body busy`
- [ ] **AC-5:** the upload stepper's active stage animates and an elapsed time is shown — `tests/VideoImportProgress.spec.tsx::the active stage shows motion`
- [ ] **AC-6:** `StageTwoProgressBanner`'s rendered output is unchanged by the extraction — `::stage 2 banner still renders frames processed`
- [ ] **AC-7:** `npm run lint` clean, `npx vitest run` green, `npm run build` succeeds, `npx tsc --noEmit` adds no new error

## DRY / SOLID check

- **Existing reused:** `StageTwoProgressBanner`'s visual language (extracted, not re-invented), `Button`'s `loading`/`disabled` props, `aurion-pulse`, the `busy` prop `NoteSectionCard` already accepts.
- **New:** one presentational `ProgressBanner`; one derived `noteBusy`.
- **SRP:** `ProgressBanner` renders progress and knows nothing about sessions or WebSockets; `StageTwoProgressBanner` keeps the subscription logic.
- **iOS?** No. Web-only, zero backend change.

## Out of scope

- **Real progress events for regeneration** — would need the backend to emit them; indeterminate is honest today.
- **The ECS sizing / video-processing-off-the-API-container problem** that made the import slow enough to notice. Separate, infrastructure, and Uzziel's call.
- **Changing what regeneration does** — TE-1 owns the detail-level control on the same rail.

## Test plan (executable)

1. `cd web && npx vitest run tests/NoteReviewProgress.spec.tsx tests/VideoImportProgress.spec.tsx`
2. `cd web && npx vitest run` → full suite green
3. `cd web && npm run lint` → clean
4. `cd web && npm run build` → static export succeeds
5. `cd web && npx tsc --noEmit` → no new errors vs the pre-existing 13
6. Mutation-test each fix: revert it, confirm its test fails
7. `git diff --stat main...HEAD -- ios/ backend/` → empty

## Security implications

- **No new data exposure.** This slice only disables controls and adds progress chrome; no new endpoint, no new field, no change to what is fetched.
- **It removes a way to export the wrong document.** Printing or exporting a note mid-regeneration produced a superseded version with no indication — the closest thing here to a clinical-safety issue, and the reason this is not just polish.
- **No PHI in the new UI.** The banner shows counts and elapsed time only; no note or caption text.
- **a11y is part of the fix, not decoration.** `aria-busy` on the note body and `role="status"` / `aria-live="polite"` on the banner are what make "this note is being replaced" perceivable to a screen-reader user, who otherwise gets the same silent stale document.
