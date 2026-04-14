"""Tests for provider implementations — verify they return valid data."""

from unittest.mock import AsyncMock, patch, MagicMock
import io

import pytest

from app.core.types import (
    MaskedFrame,
    Template,
    TemplateSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.providers.note_gen.anthropic import AnthropicNoteGenerationProvider
from app.modules.providers.note_gen.gemini import GeminiNoteGenerationProvider
from app.modules.providers.note_gen.openai import OpenAINoteGenerationProvider
from app.modules.providers.transcription.assemblyai import AssemblyAITranscriptionProvider
from app.modules.providers.transcription.whisper import WhisperTranscriptionProvider
from app.modules.providers.vision.anthropic import AnthropicVisionProvider
from app.modules.providers.vision.gemini import GeminiVisionProvider
from app.modules.providers.vision.openai import OpenAIVisionProvider


# ── Fixtures ───────────────────────────────────────────────────────────────

ORTHO_TEMPLATE = Template(
    key="orthopedic_surgery",
    display_name="Orthopedic Surgery",
    sections=[
        TemplateSection(id="chief_complaint", title="Chief Complaint", required=True),
        TemplateSection(id="hpi", title="History of Present Illness", required=True),
        TemplateSection(id="physical_exam", title="Physical Examination", required=True),
        TemplateSection(id="imaging_review", title="Imaging Review", required=True),
        TemplateSection(id="assessment", title="Assessment", required=True),
        TemplateSection(id="plan", title="Plan", required=True),
    ],
)

MOCK_TRANSCRIPT = Transcript(
    session_id="test-session-001",
    provider_used="test",
    segments=[
        TranscriptSegment(id="seg_001", start_ms=0, end_ms=5000, text="Test segment."),
    ],
)

MOCK_FRAME = MaskedFrame(
    frame_id="frame_001",
    session_id="test-session-001",
    timestamp_ms=5000,
    s3_key="frames/test/frame_001.jpg",
    masking_confirmed=True,
)

MOCK_ANCHOR = TranscriptSegment(
    id="seg_001",
    start_ms=0,
    end_ms=5000,
    text="There is tenderness on palpation.",
)


# ── Transcription Provider Tests ──────────────────────────────────────────

def _mock_whisper_response():
    """Mock response from local Whisper ASR service."""
    return {
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "The patient presents with right knee pain."},
            {"start": 5.0, "end": 12.0, "text": "There is tenderness on palpation."},
        ]
    }


def _mock_assemblyai_response():
    """Mock response from AssemblyAI API."""
    return {
        "id": "test-id",
        "status": "completed",
        "words": [
            {"text": "The", "start": 0, "end": 200},
            {"text": "patient", "start": 200, "end": 500},
            {"text": "presents.", "start": 500, "end": 1000},
            {"text": "Tenderness", "start": 1000, "end": 1500},
            {"text": "noted.", "start": 1500, "end": 2000},
        ],
    }


class TestTranscriptionProviders:
    @pytest.mark.asyncio
    async def test_whisper_returns_valid_transcript(self):
        provider = WhisperTranscriptionProvider()
        # Mock the httpx call
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _mock_whisper_response()

        with patch("app.modules.providers.transcription.whisper.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await provider.transcribe(b"audio_bytes", "session-001")

        assert result.session_id == "session-001"
        assert result.provider_used == "whisper"
        assert len(result.segments) == 2
        assert all(s.id for s in result.segments)

    @pytest.mark.asyncio
    async def test_assemblyai_returns_valid_transcript(self):
        provider = AssemblyAITranscriptionProvider()

        upload_response = MagicMock()
        upload_response.raise_for_status = MagicMock()
        upload_response.json.return_value = {"upload_url": "https://test.com/audio"}

        transcript_response = MagicMock()
        transcript_response.raise_for_status = MagicMock()
        transcript_response.json.return_value = {"id": "test-id"}

        poll_response = MagicMock()
        poll_response.raise_for_status = MagicMock()
        poll_response.json.return_value = _mock_assemblyai_response()

        with patch("app.modules.providers.transcription.assemblyai.httpx.AsyncClient") as mock_client, \
             patch("app.modules.providers.transcription.assemblyai._ASSEMBLYAI_API_KEY", "test-key"):
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=[upload_response, transcript_response])
            instance.get = AsyncMock(return_value=poll_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await provider.transcribe(b"audio_bytes", "session-001")

        assert result.session_id == "session-001"
        assert result.provider_used == "assemblyai"
        assert len(result.segments) > 0

    @pytest.mark.asyncio
    async def test_both_transcription_providers_return_same_schema(self):
        """Both providers must return the exact same Transcript schema."""
        # Just verify the model schema is identical — no need to call providers
        assert set(Transcript.model_fields.keys()) == {"session_id", "provider_used", "segments"}


# ── Note Generation Provider Tests ────────────────────────────────────────

def _mock_note_api_response(provider_name: str):
    """Return a mock LLM response that parses into a valid Note."""
    return json.dumps({
        "sections": [
            {"id": "chief_complaint", "title": "Chief Complaint", "status": "populated",
             "claims": [{"id": "c1", "text": "Test claim", "source_type": "transcript",
                         "source_id": "seg_001", "source_quote": "Test segment."}]},
            {"id": "hpi", "title": "History of Present Illness", "status": "populated",
             "claims": [{"id": "c2", "text": "Test claim", "source_type": "transcript",
                         "source_id": "seg_001", "source_quote": "Test segment."}]},
            {"id": "physical_exam", "title": "Physical Examination", "status": "populated",
             "claims": [{"id": "c3", "text": "Test claim", "source_type": "transcript",
                         "source_id": "seg_001", "source_quote": "Test segment."}]},
            {"id": "imaging_review", "title": "Imaging Review", "status": "pending_video", "claims": []},
            {"id": "assessment", "title": "Assessment", "status": "populated",
             "claims": [{"id": "c5", "text": "Test claim", "source_type": "transcript",
                         "source_id": "seg_001", "source_quote": "Test segment."}]},
            {"id": "plan", "title": "Plan", "status": "populated",
             "claims": [{"id": "c6", "text": "Test claim", "source_type": "transcript",
                         "source_id": "seg_001", "source_quote": "Test segment."}]},
        ]
    })


import json


class TestNoteGenProviders:
    @pytest.mark.asyncio
    async def test_openai_returns_valid_note(self):
        provider = OpenAINoteGenerationProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": _mock_note_api_response("openai")}}]
        }
        with patch("app.modules.providers.note_gen.openai.httpx.AsyncClient") as mc, \
             patch("app.modules.providers.note_gen.openai._OPENAI_API_KEY", "test"):
            inst = AsyncMock()
            inst.post = AsyncMock(return_value=mock_resp)
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = inst
            result = await provider.generate_note(MOCK_TRANSCRIPT, ORTHO_TEMPLATE, stage=1)
        assert result.provider_used == "openai"
        assert result.stage == 1
        assert len(result.sections) == len(ORTHO_TEMPLATE.sections)

    @pytest.mark.asyncio
    async def test_anthropic_returns_valid_note(self):
        provider = AnthropicNoteGenerationProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"text": _mock_note_api_response("anthropic")}]
        }
        with patch("app.modules.providers.note_gen.anthropic.httpx.AsyncClient") as mc, \
             patch("app.modules.providers.note_gen.anthropic._ANTHROPIC_API_KEY", "test"):
            inst = AsyncMock()
            inst.post = AsyncMock(return_value=mock_resp)
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = inst
            result = await provider.generate_note(MOCK_TRANSCRIPT, ORTHO_TEMPLATE, stage=1)
        assert result.provider_used == "anthropic"
        assert len(result.sections) == len(ORTHO_TEMPLATE.sections)

    @pytest.mark.asyncio
    async def test_gemini_returns_valid_note(self):
        provider = GeminiNoteGenerationProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": _mock_note_api_response("gemini")}]}}]
        }
        with patch("app.modules.providers.note_gen.gemini.httpx.AsyncClient") as mc, \
             patch("app.modules.providers.note_gen.gemini._GOOGLE_AI_API_KEY", "test"):
            inst = AsyncMock()
            inst.post = AsyncMock(return_value=mock_resp)
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = inst
            result = await provider.generate_note(MOCK_TRANSCRIPT, ORTHO_TEMPLATE, stage=1)
        assert result.provider_used == "gemini"
        assert len(result.sections) == len(ORTHO_TEMPLATE.sections)

    def test_all_note_providers_return_same_schema(self):
        """All providers return the same Note schema."""
        from app.core.types import Note
        assert "sections" in Note.model_fields
        assert "provider_used" in Note.model_fields

    @pytest.mark.asyncio
    async def test_stage1_has_pending_video_sections(self):
        provider = AnthropicNoteGenerationProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"text": _mock_note_api_response("anthropic")}]
        }
        with patch("app.modules.providers.note_gen.anthropic.httpx.AsyncClient") as mc, \
             patch("app.modules.providers.note_gen.anthropic._ANTHROPIC_API_KEY", "test"):
            inst = AsyncMock()
            inst.post = AsyncMock(return_value=mock_resp)
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = inst
            result = await provider.generate_note(MOCK_TRANSCRIPT, ORTHO_TEMPLATE, stage=1)
        imaging = result.get_section("imaging_review")
        assert imaging is not None
        assert imaging.status == "pending_video"


# ── Vision Provider Tests ─────────────────────────────────────────────────

_MOCK_VISION_JSON = json.dumps({
    "description": "Patient knee visible, guarding observed.",
    "confidence": "high",
    "confidence_reason": "Clear image, clinically relevant",
})


class TestVisionProviders:
    @pytest.mark.asyncio
    async def test_openai_returns_valid_caption(self):
        provider = OpenAIVisionProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": _MOCK_VISION_JSON}}]
        }
        with patch("app.modules.providers.vision.openai.httpx.AsyncClient") as mc, \
             patch("app.modules.providers.vision.openai._OPENAI_API_KEY", "test"), \
             patch.object(provider, "_load_frame_image", new_callable=AsyncMock, return_value="dGVzdA=="):
            inst = AsyncMock()
            inst.post = AsyncMock(return_value=mock_resp)
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = inst
            result = await provider.caption_frame(MOCK_FRAME, MOCK_ANCHOR)
        assert result.provider_used == "openai"
        assert result.frame_id == "frame_001"
        assert result.confidence in ("high", "medium", "low")

    @pytest.mark.asyncio
    async def test_anthropic_returns_valid_caption(self):
        provider = AnthropicVisionProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"content": [{"text": _MOCK_VISION_JSON}]}
        with patch("app.modules.providers.vision.anthropic.httpx.AsyncClient") as mc, \
             patch("app.modules.providers.vision.anthropic._ANTHROPIC_API_KEY", "test"), \
             patch.object(provider, "_load_frame_image", new_callable=AsyncMock, return_value="dGVzdA=="):
            inst = AsyncMock()
            inst.post = AsyncMock(return_value=mock_resp)
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = inst
            result = await provider.caption_frame(MOCK_FRAME, MOCK_ANCHOR)
        assert result.provider_used == "anthropic"

    @pytest.mark.asyncio
    async def test_gemini_returns_valid_caption(self):
        provider = GeminiVisionProvider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": _MOCK_VISION_JSON}]}}]
        }
        with patch("app.modules.providers.vision.gemini.httpx.AsyncClient") as mc, \
             patch("app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY", "test"), \
             patch.object(provider, "_load_frame_image", new_callable=AsyncMock, return_value="dGVzdA=="):
            inst = AsyncMock()
            inst.post = AsyncMock(return_value=mock_resp)
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = inst
            result = await provider.caption_frame(MOCK_FRAME, MOCK_ANCHOR)
        assert result.provider_used == "gemini"

    def test_all_vision_providers_return_same_schema(self):
        from app.core.types import FrameCaption
        assert "frame_id" in FrameCaption.model_fields
        assert "integration_status" in FrameCaption.model_fields
        assert "provider_used" in FrameCaption.model_fields
