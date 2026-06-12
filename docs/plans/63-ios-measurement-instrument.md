# Plan — #63 iOS measurement instrument scaffold

Fourth #63 slice, first on iOS. The backend chain (#432 schema/audit, #433
persistence+ingest, #434 note-injection, #435 client-config flag) is merged
and dark. This adds the on-device AR instrument that captures a measurement
and POSTs the confirmed citation, which the backend injects into the note.

**Ships dark**: the launch is gated on
`RemoteConfig.shared.featureFlags.measurementEnabled` (default false). The new
files compile into the target but the instrument is unreachable until ADMIN
flips the AppConfig flag *and* a launch entry is wired (see Handoff).

## Scope (this slice)

- `Network/APIClient.swift` (additive): `submitMeasurement(sessionId:_:)` POST
  + `listMeasurements(sessionId:)` GET + `MeasurementResponse` Codable
  (mirrors the backend schema). `RemoteConfig`/`ClientFeatureFlagsResponse`
  gain `measurementEnabled` (decodeIfPresent → false).
- `Measurement/MeasurementModels.swift`: `MeasurementKind` / `Method` /
  `Confidence` enums, `MeasurementResult` (captured-but-unconfirmed),
  `MeasurementCitationPayload` (the exact POST body; `masking_status =
  not_applicable` — numbers only, no frame leaves the device; never asserts
  certified).
- `Measurement/ARMeasurementController.swift`: ObservableObject ARKit session
  — LiDAR-preferred `ARWorldTrackingConfiguration`, tap-to-place distance
  (wound L/W) and 3-point goniometer (ROM angle); confidence from LiDAR +
  tracking state.
- `Measurement/ARMeasurementView.swift`: `ARSCNView` host + capture overlay
  (reticle, live readout, reset/capture, fixed "approximate, not certified"
  disclaimer) + `ConfidencePill`.
- `Measurement/MeasurementConfirmCard.swift`: mandatory physician confirm,
  ±nudge the value, fixed disclaimer.
- `Measurement/MeasurementInstrumentView.swift`: kind picker → capture →
  confirm → submit; error/loading states.
- `NoteReview/CitationChip.swift`: "M" badge + accessibility for the injected
  `source_type="measurement"` claim.
- `Resources/{en,fr}.lproj`: 35 `measurement.*` keys + `citation.sourceType.
  measurement`, at parity.
- `AurionTests/MeasurementModelsTests.swift`: pure value-type + payload tests.

## Out of scope / Handoff (needs the device + your call)

- **Launch wiring** is intentionally not added to an existing screen — the
  *when/where* is a product + camera-contention decision (ARKit needs the
  camera; don't run it over the live capture's `AVCaptureSession`). Present
  from a camera-free surface, e.g.:
  ```swift
  if RemoteConfig.shared.featureFlags.measurementEnabled {
      Button(L("measurement.title")) { showMeasure = true }
  }
  .fullScreenCover(isPresented: $showMeasure) {
      MeasurementInstrumentView(sessionId: session.id,
          onSubmitted: { _ in /* refresh note */ }, onClose: { showMeasure = false })
  }
  ```
- **On-device tuning**: raycast accuracy, the tracking→confidence mapping, and
  LiDAR mesh raycast (vs. estimated-plane) are the calibration surface — tune
  against the accuracy-characterization study (design §5) before patient use.
- **Masked thumbnail upload**: the backend has no thumbnail column yet; this
  slice uploads numbers only. A thumbnail is a future backend+iOS slice.
- **Edit/suppress post-injection** (`MEASUREMENT_EDITED/_SUPPRESSED`).

## Non-negotiables honoured

- Descriptive mode: readout/claim is "≈ value (method, physician-confirmed)";
  no interpretation. The disclaimer is a fixed, non-themeable safety surface
  (amber/semantic colors, not accent-driven).
- No frame bytes leave the device (`masking_status = not_applicable`).
- `.aurionFont` everywhere (Dynamic Type); `ViewThatFits` on the action bars
  for AX sizes. Theme tokens throughout. EN+FR at parity.
- Secrets/JWT via the existing `APIClient.addAuth` (Keychain). No provider
  keys on device.

## Verify

- iOS CI `build` compiles the target (validates the new files).
- `AurionTests/MeasurementModelsTests` (kind↔unit, display, payload schema,
  EN/FR disclaimer resolves).
- Manual on-device: device required (not in CI).
