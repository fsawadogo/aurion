# Plan: P1-6 — CitationChip clip indicator + FullClipView (iOS reviewer)

Canonical plan: `~/.claude/plans/dual-mode-visual-evidence.md`
(section "iOS changes → Reviewer").

## Task
P1-6 — Add reviewer support for clip-kind visual citations: extend the
citation chip with a play-triangle indicator when the backing evidence is
a clip; present an `AVPlayer`-backed `FullClipView` on tap (parallels
`FullFrameView` for the frame path).

## Why
P1-1..P1-3 shipped the backend dual-mode pipeline; P1-4..P1-5 ship the
iOS capture/masking/upload side; P1-6 is the reviewer half. Without it,
a clip citation surfaces in the note as a generic chip with no signal
that the backing artifact is video — physicians have no way to tell the
two kinds apart, and no path to view the clip at all. This PR closes that
last gap so a clip citation reads "video clip", taps open the player,
and the existing frame path stays byte-identical.

## Approach
Additive UI changes on the reviewer surface, scoped to
`ios/Aurion/Aurion/NoteReview/`:

1. **`Network/APIClient.swift`** (single decode-side addition): extend
   `NoteClaimResponse` with three optional fields backed by safe
   defaults — `evidenceKind` (default `.frame`), `durationMs` (nil for
   frames), `clipURL` (nil until the note endpoint plumbs it through).
   `evidenceKind` is a small `String`-backed enum so we don't propagate
   raw wire strings through the UI.
2. **`NoteReview/CitationChip.swift`** (new): extract the inline
   per-source row from `NoteReviewView.sourcesPanel` into a reusable
   chip view. Adds a 10-pt `play.triangle.fill` overlay anchored bottom-
   trailing when `evidenceKind == .clip`. Navy-on-gold per the design
   system's safe-contrast pattern, accessibility-labelled "Video clip" /
   "Clip vidéo".
3. **`NoteReview/AurionVideoPlayer.swift`** (new): minimal
   `UIViewRepresentable` wrapping `AVPlayerLayer` + `AVPlayer`. Auto-play
   on first paint; loops on `.AVPlayerItemDidPlayToEndTime`. Observer
   cleaned up on disappear.
4. **`NoteReview/FullClipView.swift`** (new): photo-viewer-style chrome
   that mirrors `FullFrameView`'s aesthetic — black background, white
   monospaced timestamp toolbar, gold Close button. Hosts
   `AurionVideoPlayer` inside.
5. **Reviewer wiring** (`NoteReview/NoteReviewView.swift`): the existing
   `sourcesPanel` switches its hand-rolled HStack to `CitationChip`.
   Tapping a clip chip presents `FullClipView`; tapping a frame chip
   stays a no-op (matches today's behaviour — frame URLs are not yet
   surfaced in the note endpoint either, so there's nothing to open).
6. **Strings**: 3 new EN+FR pairs added to `Localizable.strings` for the
   accessibility label, viewer title, and the "clip not yet available"
   fallback copy.

## Acceptance criteria

- [ ] AC-1: `NoteClaimResponse` decodes a Stage 2 note payload with no
  `evidence_kind` field (legacy / Stage 1 — every existing fixture)
  without throwing; new field defaults to `.frame`. Verified by
  `CitationChipClipIndicatorTests.decode_legacyNoteClaim_defaultsToFrame`.
- [ ] AC-2: `CitationChip` with `evidenceKind == .clip` renders the play-
  triangle indicator and carries the localized accessibility label
  "Video clip". Verified by
  `CitationChipClipIndicatorTests.clipChip_hasPlayIndicator_andA11yLabel`.
- [ ] AC-3: `CitationChip` with `evidenceKind == .frame` does NOT render
  the indicator (no visual regression). Verified by
  `CitationChipClipIndicatorTests.frameChip_omitsPlayIndicator`.
- [ ] AC-4: `FullClipView` instantiates without crashing when given a
  valid local URL + duration + timestamp. Verified by
  `CitationChipClipIndicatorTests.fullClipView_buildsBody_withSampleURL`.
- [ ] AC-5: `AurionVideoPlayer` builds a `UIView` with a backing
  `AVPlayerLayer` whose `player` is non-nil after `makeUIView`. Verified
  by `CitationChipClipIndicatorTests.aurionVideoPlayer_attachesPlayer`.
- [ ] AC-6: Existing reviewer tests in `AurionTests.swift` pass without
  modification — no regression on frame-path rendering.
- [ ] AC-7: xcodebuild succeeds on iPhone 17 simulator.
- [ ] AC-8: xcodebuild succeeds on iPad Pro 11-inch (M4) simulator.

## DRY / SOLID check

- **Existing helpers reused**: `aurionFont`, `Color.aurionGold`,
  `Color.aurionNavy`, `Color.aurionTextSecondary`, `L()`/`Lplural()`
  localization, `AurionRadius`. The toolbar chrome (black background,
  white principal title, gold close button, `toolbarColorScheme(.dark)`)
  is duplicated between `FullFrameView` and `FullClipView` — two sites
  only, no third copy, extraction would be more noise than savings (per
  §6c "don't introduce a helper for two sites").
- **New helper introduced?**: `CitationChip` (third+ visual surface for
  per-claim source rendering once the sources panel uses it; the
  audit-log surface also renders chips elsewhere) and
  `AurionVideoPlayer` (only consumer is `FullClipView` today, but it's
  the natural SOLID-SRP split between "show the chrome" and "render
  video"). Both cross a clear boundary.
- **iOS UI tasks only — `mobile-ios-design` consulted**: y. Applied HIG
  photo-viewer pattern (dark background + monospaced timestamp + close
  button trailing) — same chrome as `FullFrameView`, only content
  differs (Liskov-clean swap from the reviewer's perspective).

## Out of scope

- Clip URL plumbing through the note endpoint. The chip and FullClipView
  components are wired and testable; the field will populate once the
  backend stage 2 merge emits citation `clip_url` in `GET /notes/full`.
  iOS surfaces a localized "clip not yet available" notice if a clip-
  kind chip is tapped without a URL.
- "Still extracted from clip" badge for `degraded_to_frame=true`
  citations. Mentioned in the canonical plan but ships in a later PR.
- Reviewer-side fetching / S3 signing of clip URLs. The expected wire
  shape is "URL is already in the citation payload" — the iOS side
  decodes it if present, period.
- Capture/Masking/Network changes — those are P1-5's scope.

## Test plan (executable)

1. `cd /Users/fsawadogo/aurion-lanes/ios-p1-6 && xcodebuild -project ios/Aurion/Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build`
   → BUILD SUCCEEDED.
2. `cd /Users/fsawadogo/aurion-lanes/ios-p1-6 && xcodebuild -project ios/Aurion/Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M4)' build`
   → BUILD SUCCEEDED.
3. `cd /Users/fsawadogo/aurion-lanes/ios-p1-6 && xcodebuild -project ios/Aurion/Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' test`
   → all AurionTests pass, including
   `CitationChipClipIndicatorTests` (5 cases).

## Security implications

- No new PHI surface: chips, accessibility labels, and viewer chrome
  carry no patient data. Timestamps are session-relative seconds, not
  wall-clock.
- No new audit events; the chip and viewer are read-only on the
  client.
- No new AI prompt; no descriptive-mode review needed.
- Clip URL is opaque to the chip — playback is via `AVPlayer` against
  the URL the backend supplied; iOS does not unwrap, decode, or persist
  it beyond the `FullClipView` lifecycle.
- Consent gate intact: this PR ships only reviewer-surface UI; no new
  capture/upload paths.
