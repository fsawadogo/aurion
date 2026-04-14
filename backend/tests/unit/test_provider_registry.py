"""Tests for provider registry — verifies correct provider resolved from config."""

import os
from unittest.mock import patch

import pytest

from app.core.types import ProviderError
from app.modules.config.provider_registry import ProviderRegistry
from app.modules.config.schema import AppConfigSchema
from app.modules.providers.note_gen.anthropic import AnthropicNoteGenerationProvider
from app.modules.providers.note_gen.gemini import GeminiNoteGenerationProvider
from app.modules.providers.note_gen.openai import OpenAINoteGenerationProvider
from app.modules.providers.transcription.assemblyai import AssemblyAITranscriptionProvider
from app.modules.providers.transcription.whisper import WhisperTranscriptionProvider
from app.modules.providers.vision.anthropic import AnthropicVisionProvider
from app.modules.providers.vision.gemini import GeminiVisionProvider
from app.modules.providers.vision.openai import OpenAIVisionProvider


def _mock_config(**overrides) -> AppConfigSchema:
    providers = {
        "transcription": "whisper",
        "note_generation": "anthropic",
        "vision": "openai",
    }
    providers.update(overrides)
    return AppConfigSchema.model_validate({"providers": providers})


class TestTranscriptionRegistry:
    def test_whisper_default(self):
        registry = ProviderRegistry()
        with patch("app.modules.config.provider_registry.get_config", return_value=_mock_config()):
            provider = registry.get_transcription_provider()
        assert isinstance(provider, WhisperTranscriptionProvider)

    def test_assemblyai(self):
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(transcription="assemblyai"),
        ):
            provider = registry.get_transcription_provider()
        assert isinstance(provider, AssemblyAITranscriptionProvider)

    def test_override(self):
        registry = ProviderRegistry()
        with patch("app.modules.config.provider_registry.get_config", return_value=_mock_config()):
            provider = registry.get_transcription_provider(override="assemblyai")
        assert isinstance(provider, AssemblyAITranscriptionProvider)


class TestNoteGenRegistry:
    def test_anthropic_default(self):
        registry = ProviderRegistry()
        with patch("app.modules.config.provider_registry.get_config", return_value=_mock_config()):
            provider = registry.get_note_provider()
        assert isinstance(provider, AnthropicNoteGenerationProvider)

    def test_openai(self):
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(note_generation="openai"),
        ):
            provider = registry.get_note_provider()
        assert isinstance(provider, OpenAINoteGenerationProvider)

    def test_gemini(self):
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(note_generation="gemini"),
        ):
            provider = registry.get_note_provider()
        assert isinstance(provider, GeminiNoteGenerationProvider)

    def test_override(self):
        registry = ProviderRegistry()
        with patch("app.modules.config.provider_registry.get_config", return_value=_mock_config()):
            provider = registry.get_note_provider(override="openai")
        assert isinstance(provider, OpenAINoteGenerationProvider)


class TestVisionRegistry:
    def test_openai_default(self):
        registry = ProviderRegistry()
        with patch("app.modules.config.provider_registry.get_config", return_value=_mock_config()):
            provider = registry.get_vision_provider()
        assert isinstance(provider, OpenAIVisionProvider)

    def test_anthropic(self):
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(vision="anthropic"),
        ):
            provider = registry.get_vision_provider()
        assert isinstance(provider, AnthropicVisionProvider)

    def test_gemini(self):
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(vision="gemini"),
        ):
            provider = registry.get_vision_provider()
        assert isinstance(provider, GeminiVisionProvider)


class TestFallback:
    def test_note_fallback_returns_provider(self):
        registry = ProviderRegistry()
        with patch("app.modules.config.provider_registry.get_config", return_value=_mock_config()):
            provider = registry.get_note_provider_with_fallback()
        assert isinstance(provider, AnthropicNoteGenerationProvider)

    def test_vision_fallback_returns_provider(self):
        registry = ProviderRegistry()
        with patch("app.modules.config.provider_registry.get_config", return_value=_mock_config()):
            provider = registry.get_vision_provider_with_fallback()
        assert isinstance(provider, OpenAIVisionProvider)
