# Plan — bug-282

## Task
#282 — Crash-orphaned raw-audio WAVs accumulate forever in `Application Support/AudioUploadStaging/<sessionId>.wav`, and discarding a session never purges its local staged WAV. Raw clinical audio outliving its session is a retention/privacy violation.

## Why
`SessionManager.clearRecordedAudioFile()` deletes the staged WAV via the **in-memory** `recordedAudioFileURL`. A crash (e.g. the pre-#273 upload crash that hit 6 sessions on 2026-06-06) loses that reference, orphaning the on-disk file permanently. The existing foreground sweep (`LocalDataPurger.purgeStaleArtifacts`, AurionApp:178) only sweeps the OS **temp dir** — it never looks at `AudioUploadStaging/` (Application Support). And `SessionsInboxView.discard` deletes the session server-side but leaves the local WAV. MVP rule (CLAUDE.md): raw audio deleted after transcription, deletion auditable.

## Approach
1. **Single source of the staging path** — extract `enum AudioUploadStaging { static var directory; static func fileURL(sessionId:) }` (currently hardcoded in `SessionManager`). DRY: `SessionManager` + `LocalDataPurger` share it.
2. **Foreground orphan sweep** — extend `LocalDataPurger.purgeStaleArtifacts()` to also sweep `AudioUploadStaging.directory` for files older than `staleThreshold` (24h). The active upload's WAV is short-lived (deleted on success/teardown), so anything >24h old there is definitively orphaned. Refactor the dir-walk into a reusable internal `sweep(directory:maxAge:filter:)` (used by both the temp-dir and staging sweeps).
3. **Discard purges immediately** — `LocalDataPurger.purgeStagedAudio(sessionId:)` deletes `AudioUploadStaging/<id>.wav` and audits; called from `SessionsInboxView.discard` after a successful `discardSession` (don't wait 24h for an explicit discard).

Files: new `ios/Aurion/Aurion/Session/AudioUploadStaging.swift`, `Session/SessionManager.swift`, `Session/LocalDataPurger.swift`, `Session/SessionsInboxView.swift`, new `AurionTests/StagingPurgeTests.swift`.

## Acceptance criteria
- [ ] AC-1: `AudioUploadStaging.fileURL(sessionId: "abc")` ends with `AudioUploadStaging/abc.wav` under Application Support — `StagingPurgeTests.fileURLPath`.
- [ ] AC-2: `sweep(directory:maxAge:filter:)` deletes a file older than `maxAge` and keeps a fresh one — `StagingPurgeTests.sweepDeletesOldKeepsFresh` (run against a temp dir).
- [ ] AC-3: `sweep(maxAge: nil, …)` deletes all matching files regardless of age — `StagingPurgeTests.sweepNilAgeDeletesAll`.
- [ ] AC-4: `purgeStagedAudio(sessionId:)` removes an existing staged WAV and returns true; returns false when none exists — `StagingPurgeTests.purgeStagedAudioRemovesFile`.
- [ ] AC-5: app builds iPhone 17 + iPad Pro 11" (M4) — CI.

## DRY / SOLID check
- **Existing helpers to reuse**: `LocalDataPurger.staleThreshold`, `AuditLogger.log(event: .localDataPurged …)`, the existing dir-walk pattern in `sweepTempFiles` (now generalized). `recordedAudioFileURL`/`clearRecordedAudioFile` stay for the happy path.
- **New helper introduced?**: `AudioUploadStaging` (extracts the path that was hardcoded in `SessionManager` — single source of truth, used by 2 modules) and `sweep(directory:maxAge:filter:)` (generalizes the existing private `sweepTempFiles`, 2nd consumer). Both justified.
- **iOS UI only — mobile-ios-design**: n/a (no UI).

## Out of scope
- Server-reconciling each staged WAV (resume vs delete) — the time-based sweep is sufficient since staging holds only the short-lived active upload; the OfflineUploadQueue owns its own `OfflineUploads/` dir + manifest and is unaffected.
- Excluding the staging dir from iCloud backup (OfflineUploadQueue's concern, per existing comment).

## Test plan (executable)
1. `xcodebuild test -scheme Aurion -destination 'iPhone 17' -only-testing:AurionTests/StagingPurgeTests` → green.
2. CI build matrix.

## Security implications
PRIVACY-positive — closes a raw-audio retention gap. Deletions are audited via `AuditLogger.localDataPurged` (no PHI in the payload: session id + counts/reason only). No new network/secret/AI path. Sweep filter is scoped to `.wav` files in the Aurion-owned staging dir so nothing else is touched.
