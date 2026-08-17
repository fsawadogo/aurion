"""Fusion B — parallel-then-merge multimodal note assembly.

The pipeline's default is "Fusion A" (transcript-as-context): Stage 1 writes the
note from audio, Stage 2 captions the video and merges visual CLAIMS into that
same note (``vision.service.merge_visual_citations``). The video never produces
a note of its own — it only annotates the audio note.

"Fusion B" (this module) is the alternative the roadmap asks us to compare: an
INDEPENDENT note is generated from the video, an independent note from the
audio, and the two whole notes are merged section-by-section with modality
weighting (visual for the exam/procedure/imaging sections; audio for
history/discussion/plan) and conflicts surfaced rather than silently resolved.

The video note reuses the existing note-gen engine: the frame/clip captions are
turned into a pseudo-transcript (one segment per caption, the visual
description as its text) and run through ``provider.generate_note`` with a
visual-documentation system prompt. No new provider method, no image path
through note-gen — the note-gen engine stays transcript-shaped and modality
lives here.

This module is READ-ONLY with respect to the chart: it builds Note objects and
returns them; it never calls ``create_note_version``. The Grounded Lab uses it
to show Fusion A vs Fusion B side by side so the founders can pick one before
committing (``feature_flags.parallel_fusion_enabled`` gates any future live
use, not this comparison).
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.types import (
    Note,
    NoteSection,
    Template,
    Transcript,
    TranscriptSegment,
)
from app.modules.config.provider_registry import get_registry
from app.modules.vision.service import VisualEvidenceItem, caption_visual_evidence

logger = logging.getLogger("aurion.note_gen.fusion")

# System prompt for the INDEPENDENT video note. The input is a pseudo-transcript
# of timestamped visual observations; the model documents only what those
# observations support and leaves conversation-derived sections empty. Same
# descriptive-vs-grounded boundary as the rest of the pipeline — this prompt
# does not loosen grounding; the captions it reads were already produced under
# the (descriptive or grounded) vision prompt.
VIDEO_NOTE_SYSTEM_PROMPT = (
    "You are a clinical documentation assistant writing the note from VISUAL "
    "observations of an encounter. Your input is a time-ordered list of things "
    "seen on video during the exam — not a conversation. "
    "Document only the sections the visual record supports: the physical "
    "examination, any procedure performed, wound appearance, and what is shown "
    "on imaging or monitor screens. For sections that depend on what was SAID "
    "(chief complaint, history of present illness, assessment, plan, "
    'disposition), leave them empty with status "not_captured" — the video '
    "cannot establish them. Never infer history or a plan from the images. "
    "Report only what the observations directly support; do not invent findings "
    "or measurements the record does not contain."
)

# Section ids the physical/visual record documents better than the conversation.
# On these, the merged note prefers the VIDEO note's content; on all others it
# prefers the AUDIO note. Keyed to the specialty templates' section ids
# (orthopedic/plastic/msk/emergency/general — see CLAUDE.md).
_VISUAL_WEIGHTED_SECTIONS: frozenset[str] = frozenset(
    {
        "physical_exam",
        "imaging_review",
        "wound_assessment",
        "functional_assessment",
        "procedure",
        "procedural",
    }
)


def _pseudo_transcript_from_captions(
    session_id: str, captions: list
) -> tuple[Transcript, dict[str, str]]:
    """Turn frame/clip captions into a pseudo-transcript for the note engine.

    Each non-empty caption becomes one segment whose text is the visual
    description and whose timing is the caption timestamp, so the note-gen
    engine reads the visual record as its source material. Ordered by time.

    Also returns ``{pseudo_segment_id: evidence_id}`` so the caller can
    re-anchor the resulting claims to the REAL frame or clip they came from
    (VIS-08). Returned rather than rebuilt by the caller because it has to
    agree exactly with the sort-and-skip-empties logic above — recomputing it
    separately is how the two silently drift apart.
    """
    segments: list[TranscriptSegment] = []
    anchors: dict[str, str] = {}
    for i, cap in enumerate(sorted(captions, key=lambda c: c.timestamp_ms)):
        desc = (cap.visual_description or "").strip()
        if not desc:
            continue
        pseudo_id = f"vseg_{i:03d}"
        segments.append(
            TranscriptSegment(
                id=pseudo_id,
                start_ms=cap.timestamp_ms,
                end_ms=cap.timestamp_ms + (cap.duration_ms or 0),
                text=desc,
            )
        )
        anchors[pseudo_id] = cap.frame_id
    return (
        Transcript(
            session_id=session_id, provider_used="vision", segments=segments
        ),
        anchors,
    )


async def generate_video_note(
    session_id: str,
    evidence: list[VisualEvidenceItem],
    template: Optional[Template],
    *,
    grounded: bool,
    output_language: str = "en",
    provider_override: Optional[str] = None,
    captions: Optional[list] = None,
) -> Optional[Note]:
    """Generate an INDEPENDENT note from the video evidence alone.

    Captions the evidence (descriptive or grounded per ``grounded``), turns the
    captions into a pseudo-transcript, and runs it through the note-gen engine
    with the visual-documentation prompt. Returns ``None`` when the evidence
    yields no usable captions (nothing visible), so the caller can fall back to
    the audio note. READ-ONLY: never persists a note version.

    ``captions`` — when the caller has ALREADY captioned the evidence (e.g. the
    modality-compare endpoint, which needs the same captions for its "merged"
    note), pass them in to avoid captioning the media twice. This matters under
    the vision provider's rate limit: a second caption pass would double the
    429 pressure. ``None`` (the default) captions here as before.
    """
    if captions is None:
        captions = await caption_visual_evidence(
            evidence=evidence,
            trigger_segments=[],
            anchor_segments=[],
            template=template,
            note=None,
            grounded=grounded,
        )
    captions = [c for c in captions if c.confidence != "low"]
    pseudo, frame_anchors = _pseudo_transcript_from_captions(session_id, captions)
    if not pseudo.segments:
        logger.info(
            "Fusion B: no usable visual captions for session=%s — no video note",
            str(session_id)[:8],
        )
        return None

    if template is None:
        return None

    registry = get_registry()
    provider = (
        registry.get_note_provider(override=provider_override)
        if provider_override
        else registry.get_note_provider_with_fallback()
    )
    note = await provider.generate_note(
        pseudo,
        template,
        stage=1,
        output_language=output_language,
        system_prompt=VIDEO_NOTE_SYSTEM_PROMPT,
    )
    note.session_id = str(session_id)
    # Re-tag the video note's claims as visual-sourced: the note engine labels
    # them source_type="transcript" (it can't know its input was a pseudo-
    # transcript), but every claim here rests on a visual observation.
    #
    # VIS-08 — and re-anchor them to the REAL evidence. The note engine cites
    # the pseudo-segment it read (`vseg_003`), which does not exist: it is an
    # artefact of this function. A claim citing it is untraceable — tap-to-
    # source has nothing to open, and `citation_traceability_rate` counts it as
    # valid when it is not. That matters most under Grounded Synthesis, where a
    # synthesized statement is only permitted BECAUSE it cites its sources
    # (CLAUDE.md); citing a fabricated id is precisely what that gate exists to
    # prevent.
    #
    # A citation we cannot map is a claim resting on nothing, so it is DROPPED
    # rather than shipped with a dangling anchor — the descriptive-mode-safe
    # direction. In practice this only fires if the model invents a segment id.
    unmapped = 0
    for section in note.sections:
        kept = []
        for claim in section.claims:
            if claim.source_type == "transcript":
                claim.source_type = "visual"
            anchor = frame_anchors.get(claim.source_id)
            if anchor is None:
                unmapped += 1
                continue
            claim.source_id = anchor
            claim.source_quote = f"[{anchor}]"
            # Grounded claims rest on several anchors; every one must resolve.
            resolved = []
            unresolved_additional = False
            for extra in claim.additional_sources:
                mapped = frame_anchors.get(extra.source_id)
                if mapped is None:
                    unmapped += 1
                    unresolved_additional = True
                    break
                extra.source_id = mapped
                extra.source_quote = f"[{mapped}]"
                resolved.append(extra)
            if unresolved_additional:
                # The model declared every extra anchor as support for this
                # claim. If any one is untraceable, reject the entire claim
                # rather than shipping a conclusion with partial grounding.
                continue
            claim.additional_sources = resolved
            kept.append(claim)
        section.claims = kept
        if not section.claims and section.status == "populated":
            # Don't leave a section claiming to be populated with nothing in it.
            section.status = "not_captured"
    if unmapped:
        logger.warning(
            "Video note: dropped %d citation(s) that resolved to no evidence "
            "(session=%s)",
            unmapped, str(session_id)[:8],
        )
    return note


def _section_is_populated(section: Optional[NoteSection]) -> bool:
    return section is not None and len(section.claims) > 0


def merge_parallel_notes(
    audio_note: Note,
    video_note: Optional[Note],
    template: Optional[Template] = None,
) -> Note:
    """Merge an audio note and a video note section-by-section (Fusion B).

    Modality weighting: on the visual-weighted sections (exam / imaging / wound
    / functional / procedure) the video note's content wins when it has any;
    every other section takes the audio note. When BOTH notes populate a
    visual-weighted section, the audio claims are kept alongside the video ones
    and flagged as a conflict for the physician to resolve (surface, don't
    silently drop) — mirroring the roadmap's "default to visual for the exam,
    let the physician choose".

    Returns a NEW merged Note (does not mutate the inputs). When there is no
    video note, returns the audio note unchanged (Fusion B degrades to audio).
    """
    if video_note is None:
        return audio_note.model_copy(deep=True)

    video_by_id = {s.id: s for s in video_note.sections}
    merged_sections: list[NoteSection] = []

    for a_sec in audio_note.sections:
        v_sec = video_by_id.get(a_sec.id)
        visual_weighted = a_sec.id in _VISUAL_WEIGHTED_SECTIONS

        if visual_weighted and _section_is_populated(v_sec):
            # Video wins the section. If audio ALSO documented it, keep the
            # audio claims as flagged conflicts so the physician can choose.
            assert v_sec is not None
            claims = [c.model_copy(deep=True) for c in v_sec.claims]
            if _section_is_populated(a_sec):
                for c in a_sec.claims:
                    conflict = c.model_copy(deep=True)
                    conflict.id = f"conflict_audio_{conflict.id}"
                    conflict.text = (
                        "CONFLICT (audio): " + conflict.text
                    )
                    claims.append(conflict)
            merged_sections.append(
                NoteSection(
                    id=a_sec.id, title=a_sec.title, status="populated", claims=claims
                )
            )
        else:
            # Audio wins (audio-weighted section, or video had nothing here).
            merged_sections.append(a_sec.model_copy(deep=True))

    # Visual-weighted sections that exist ONLY in the video note (not in the
    # audio template projection) — append them so nothing the video found is lost.
    audio_ids = {s.id for s in audio_note.sections}
    for v_sec in video_note.sections:
        if v_sec.id not in audio_ids and _section_is_populated(v_sec):
            merged_sections.append(v_sec.model_copy(deep=True))

    return Note(
        session_id=audio_note.session_id,
        stage=2,
        version=audio_note.version,
        provider_used=f"fusion_b({audio_note.provider_used}+{video_note.provider_used})",
        specialty=audio_note.specialty,
        completeness_score=audio_note.completeness_score,
        sections=merged_sections,
    )


def note_has_conflicts(note: Note) -> bool:
    """True if the merged note carries any surfaced audio/visual conflict."""
    return any(
        claim.id.startswith("conflict_")
        for section in note.sections
        for claim in section.claims
    )
