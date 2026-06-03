"""Per-provider per-model rates for vision spend estimation.

Rates are in USD-per-million-tokens (USD/MT). The single calculator
``estimate_cost_usd_micros`` converts a (provider, model, input_tokens,
output_tokens) tuple to an integer USD-micros value (1 USD = 1_000_000
micros) — integers all the way through so Phase 2 aggregations don't
drift on float arithmetic.

Last updated: 2026-06-03. Source: provider public pricing pages.
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

logger = logging.getLogger("aurion.vision.cost_rates")

# {provider: {model: {"input": USD/MT, "output": USD/MT}}}
#
# Lower-case the model id at lookup time — providers sometimes ship
# capitalised names ("Claude-Sonnet-4-6") but the rate table is the
# canonical normalised form.
VISION_RATES_USD_PER_MT: dict[str, dict[str, dict[str, float]]] = {
    "gemini": {
        "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-2.5-flash": {"input": 0.10, "output": 0.40},
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
            "vision cost_rates: unknown provider=%s (model=%s) — returning 0",
            provider_key,
            model_key,
        )
        return 0
    rates = provider_rates.get(model_key)
    if rates is None:
        logger.info(
            "vision cost_rates: unknown model=%s for provider=%s — returning 0",
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
