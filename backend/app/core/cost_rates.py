"""Per-provider per-model rates for vision spend estimation.

Rates are in USD-per-million-tokens (USD/MT). The single calculator
``estimate_cost_usd_micros`` converts a (provider, model, input_tokens,
output_tokens) tuple to an integer USD-micros value (1 USD = 1_000_000
micros) — integers all the way through so Phase 2 aggregations don't
drift on float arithmetic.

Last updated: 2026-06-15 (added gemini-3.1-pro-preview, #438).
Source: provider public pricing pages.
- Gemini:    https://ai.google.dev/pricing
- OpenAI:    https://openai.com/api/pricing/
- Anthropic: https://www.anthropic.com/pricing

Phase 2 cost will be approximate regardless — we just need not-zero so
the eval team can compare providers quantitatively. When pricing
changes, edit this table; the column type (integer USD micros) does
not change, and existing rows stay valid.

This is the single rate-lookup site (DRY). Future note-gen /
transcription spend estimation should import from here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aurion.cost_rates")

# {provider: {model: {"input": USD/MT, "output": USD/MT}}}
#
# Lower-case the model id at lookup time — providers sometimes ship
# capitalised names ("Claude-Sonnet-4-6") but the rate table is the
# canonical normalised form.
VISION_RATES_USD_PER_MT: dict[str, dict[str, dict[str, float]]] = {
    "gemini": {
        "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-2.5-flash": {"input": 0.10, "output": 0.40},
        # gemini-3.1-pro-preview (#438). Standard tier, prompts <=200k tokens
        # (Aurion transcripts + clips sit well under 200k, so the lower tier
        # applies; the >200k tier is 4.00/18.00). USD/MT. Keep the 2.5-pro row
        # for in-flight sessions + the <30s config rollback.
        "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    },
    "openai": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
    },
    "anthropic": {
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    },
}

# 1 USD = 1_000_000 micros. Integer scaling factor — used in the spend
# calculator and re-used by anything else that converts USD → micros.
USD_MICROS_PER_DOLLAR = 1_000_000

# Per-million scaling factor for the rate table.
TOKENS_PER_MT = 1_000_000


def estimate_cost_usd_micros(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> int:
    """Return estimated cost in USD micros (1 USD = 1_000_000 micros).

    Returns 0 if provider/model is unknown — logs INFO so the eval team
    can see the gap in Sentry-tagged INFO logs without the call site
    crashing. Phase 2 cost is approximate regardless; the contract is
    "never break the metric for an unknown rate".

    Negative token counts are clamped to 0 (defensive — providers
    occasionally return -1 on partial failures).

    No PHI on this code path — provider, model, and token counts are
    all numeric or controlled-vocabulary strings.
    """
    if input_tokens < 0:
        input_tokens = 0
    if output_tokens < 0:
        output_tokens = 0

    provider_key = (provider or "").lower()
    model_key = (model or "").lower()

    provider_rates = VISION_RATES_USD_PER_MT.get(provider_key)
    if provider_rates is None:
        logger.info(
            "cost_rates: unknown provider=%s (model=%s) — returning 0",
            provider_key,
            model_key,
        )
        return 0
    rates = provider_rates.get(model_key)
    if rates is None:
        logger.info(
            "cost_rates: unknown model=%s for provider=%s — returning 0",
            model_key,
            provider_key,
        )
        return 0

    # USD = (tokens × USD/MT) / TOKENS_PER_MT
    # USD micros = USD × USD_MICROS_PER_DOLLAR
    # Combine into a single integer-final expression to avoid float
    # drift across many small clips.
    input_micros = int(
        (input_tokens * rates["input"] * USD_MICROS_PER_DOLLAR)
        / TOKENS_PER_MT
    )
    output_micros = int(
        (output_tokens * rates["output"] * USD_MICROS_PER_DOLLAR)
        / TOKENS_PER_MT
    )
    return input_micros + output_micros


# ── Audio-duration pricing (transcription, #73/OV-2) ─────────────────────────
#
# Transcription is priced per audio-hour, not per token. Approximate, like
# the token table. Last updated: 2026-06-11. Source: provider pricing pages
# (AssemblyAI universal tier). Whisper is self-hosted on our own compute —
# $0 marginal API cost by definition (infra cost lives in the ECS bill).
AUDIO_RATES_USD_PER_HOUR: dict[str, float] = {
    "assemblyai": 0.12,
    "whisper": 0.0,
}


def estimate_audio_cost_usd_micros(provider: str, audio_seconds: float) -> int:
    """Estimated transcription cost in USD micros for a clip of
    ``audio_seconds``. Unknown provider or non-positive duration → 0 with
    an INFO log (same fail-soft contract as the token estimator)."""
    if audio_seconds <= 0:
        return 0
    rate = AUDIO_RATES_USD_PER_HOUR.get(provider.lower())
    if rate is None:
        logger.info("no audio rate for provider=%s — cost recorded as 0", provider)
        return 0
    return int(round(rate * (audio_seconds / 3600.0) * USD_MICROS_PER_DOLLAR))
