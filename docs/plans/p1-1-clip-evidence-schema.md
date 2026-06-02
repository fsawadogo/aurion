# P1-1 — Clip Evidence Schema + Provider Interface

Plan reference: `/Users/fsawadogo/.claude/plans/dual-mode-visual-evidence.md`
(the full dual-mode visual evidence plan — frames + clips with runtime selection).

This PR is the foundation slice of Phase 1, additive only, with default
behavior byte-identical to today's pilot build.

## Why

Aurion's vision pipeline today extracts JPEG stills at a configurable FPS
and masks faces on-device. Static observations (wound assessment, patient
positioning, screen content) are well-served. Motion-heavy moments — ROM
exams, gait analysis, dressing-change technique — lose signal because three
1-fps stills only approximate the motion by luck. Gemini 2.5 Pro is the
only frontier model that natively understands video clips and gives back
descriptions like "patient demonstrated abduction to approximately 140°
then visibly winced and stopped."

The dual-mode architecture keeps frames as the default (proven, cheap,
low-bandwidth) and adds clips as a parallel path for motion triggers, routed
per-trigger-kind at runtime via AppConfig. No big-bang migration; every
existing frame call site keeps working.

## Scope of this PR (P1-1)

Backend, additive, zero behavior change at default.

- `modules/config/schema.py` — `VisualEvidenceMode` StrEnum (default
  `FRAMES_ONLY`), `ProvidersConfig.vision_clip`, new `PipelineConfig`
  fields (`visual_evidence_mode`, `clip_window_ms`,
  `clip_ring_buffer_seconds`, `clip_trigger_kinds`), and the
  `per_session_visual_evidence_mode_override` feature flag.
- `core/types.py` — new `MaskedClip` + `ClipMaskingMetadata` Pydantic
  models; additive `evidence_kind` (`"frame"` default) + optional
  `duration_ms` on `FrameCaption` so today's call sites stay schema-stable.
- `modules/providers/base.py` — extend `VisionProvider` ABC with
  `caption_clip` as an abstractmethod (subclasses MUST implement it).
- `modules/providers/vision/{openai,anthropic,gemini}.py` — each adds a
  stub `caption_clip` raising `NotImplementedError("clip captioning
  lands in P1-2")`. P1-2 ships the real implementations.
- `core/audit_events.py` — three new lifecycle members (`CLIP_UPLOADED`,
  `CLIP_MASKED`, `CLIP_DISCARDED`) + whitelist entries; lock test updated.
- `alembic/versions/2026_06_02_0023_clip_evidence.py` — creates the new
  `frames` SQL table (no such table exists today; frame metadata lives in
  S3 only). The table has `evidence_kind VARCHAR(8) NOT NULL DEFAULT
  'frame'` and `duration_ms INTEGER NULL` from day one, with an index on
  `(session_id, evidence_kind)` for the reviewer's filtered queries.
- `tests/unit/test_clip_evidence_schema.py` — coverage for every new
  schema surface (see Acceptance criteria below).

## Acceptance criteria

- [ ] AC-1: `VisualEvidenceMode` enum locks the three values
      (`frames_only`, `clips_only`, `hybrid`).
- [ ] AC-2: `PipelineConfig.visual_evidence_mode` defaults to
      `frames_only`; everyone else's default behavior is unchanged.
- [ ] AC-3: `ProvidersConfig.vision_clip` defaults to `gemini`
      (rationale: Gemini is the only native-video provider).
- [ ] AC-4: `PipelineConfig.clip_trigger_kinds` defaults to
      `["motion", "rom", "gait", "procedural"]`.
- [ ] AC-5: Every concrete `VisionProvider` subclass MUST implement
      `caption_clip` (compile-time enforcement via ABC; verified via a
      dynamic subclass check that proves `NotImplementedError` is raised).
- [ ] AC-6: `MaskedClip` and `ClipMaskingMetadata` validate the documented
      field set.
- [ ] AC-7: `FrameCaption.evidence_kind` defaults to `"frame"` so today's
      call sites stay byte-identical.
- [ ] AC-8: Three new audit event values match exact strings
      (`"clip_uploaded"`, `"clip_masked"`, `"clip_discarded"`).
- [ ] AC-9: Alembic migration `0023` applies cleanly against the local
      SQLite test DB and `downgrade -1` rolls back cleanly.

## Out of scope

- `caption_clip` real implementations — lands in P1-2 (Gemini native +
  OpenAI/Anthropic midpoint-still fallback).
- New `POST /api/v1/clips/{session_id}` endpoint — lands in P1-3.
- iOS ring buffer / clip extraction / masking — lands in P1-4..P1-6.
- Vision service dispatch (frame-vs-clip routing) — lands in P1-3.

## DRY / SOLID check

- **Existing helpers to reuse**: `VisionProviderKey` already covers
  every provider we need; `vision_clip` just adds a second slot using
  the same enum. `FrameCaption` stays the contract for both frames and
  clips (Liskov: every provider's output is interchangeable at the type
  boundary).
- **New helper introduced?**: No. `MaskedClip` and `ClipMaskingMetadata`
  are sibling types to `MaskedFrame`, not duplicates of it.
- **OCP**: new behavior extends the enum + ABC; no `if provider == ...`
  branches added.

## Security implications

- No PHI touched in this PR — schema/interface only.
- New audit events follow the existing whitelist pattern (no PHI in
  audit-row kwargs).
- The migration is purely additive; no data migration required.
