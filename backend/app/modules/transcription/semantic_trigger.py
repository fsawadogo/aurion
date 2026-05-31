"""Semantic trigger classification via embeddings (Tier 2 / item F).

Layered on top of the keyword classifier in ``trigger_classifier.py``:

  1. keyword_classify(segment) — fast, free, explainable
  2. if no match → semantic_classify(segment) — embedding cosine
     similarity vs trigger-category prose descriptions

Catches paraphrases the keyword list misses ("can you bend your knee"
→ ``active_physical_examination``, "let's look at your imaging" →
``live_imaging_review``). All embeddings come from OpenAI's
``text-embedding-3-small`` (1536-dim, ~$0.02/1M tokens — effectively
free at pilot scale). One batched call per session over the segments
the keywords missed, not per segment.

Off by default. Opt in via ``AURION_SEMANTIC_TRIGGER_ENABLED=1`` so the
pilot can A/B against the keyword-only baseline before flipping it on
permanently. Failures (no API key, HTTP error, empty response) log a
warning and return no semantic matches — system falls back to today's
keyword-only behaviour.
"""

from __future__ import annotations

import logging
import math
import os

import httpx

logger = logging.getLogger("aurion.transcription.semantic_trigger")

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_EMBED_MODEL = "text-embedding-3-small"
_EMBED_ENDPOINT = "https://api.openai.com/v1/embeddings"
_THRESHOLD = float(os.getenv("AURION_SEMANTIC_TRIGGER_THRESHOLD", "0.45"))


def is_enabled() -> bool:
    return os.getenv("AURION_SEMANTIC_TRIGGER_ENABLED", "0") == "1"


# Prose descriptions of each trigger category — embedded once + cached
# in process memory. Tuned for semantic match: prefer "the physician is
# doing X" phrasing so the embedding captures the activity, not just
# the body part or modality.
TRIGGER_DESCRIPTIONS: dict[str, str] = {
    "live_imaging_review": (
        "The physician is describing what they see on an imaging study —"
        " an X-ray, MRI, CT scan, ultrasound, EKG strip, or other"
        " radiology / monitor view they are looking at right now."
    ),
    "active_physical_examination": (
        "The physician is performing a physical exam — testing range of"
        " motion, palpating tissue, percussing, doing special tests,"
        " checking strength, sensation, or reflexes on the patient."
    ),
    "wound_tissue_assessment": (
        "The physician is examining a wound or tissue surface, describing"
        " edges, drainage, dimensions, color, granulation, perfusion,"
        " or flap viability."
    ),
}


# Module-level cache for the (category → embedding) map. Populated on
# first call; reused for the lifetime of the process.
_category_embeddings: dict[str, list[float]] | None = None


async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Call OpenAI embeddings on a batch. Returns vectors in input order.
    Raises on HTTP error so callers can swallow at the right layer."""
    if not texts:
        return []
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _EMBED_ENDPOINT,
            headers={
                "Authorization": f"Bearer {_OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": _EMBED_MODEL, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
    return [item["embedding"] for item in data["data"]]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity. No numpy dependency.
    Returns 0.0 if either vector is zero-magnitude."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _ensure_category_embeddings() -> dict[str, list[float]] | None:
    """Embed the TRIGGER_DESCRIPTIONS once and cache. Returns the cache
    or None if embedding the categories failed."""
    global _category_embeddings
    if _category_embeddings is not None:
        return _category_embeddings
    try:
        categories = list(TRIGGER_DESCRIPTIONS.keys())
        descs = [TRIGGER_DESCRIPTIONS[c] for c in categories]
        vectors = await _embed_batch(descs)
        _category_embeddings = dict(zip(categories, vectors))
        logger.info("Cached %d trigger-category embeddings", len(categories))
        return _category_embeddings
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning(
            "Failed to embed trigger categories — semantic classifier "
            "will no-op for this process",
            exc_info=True,
        )
        return None


def _clear_cache_for_tests() -> None:
    """Test helper — drop cached category embeddings."""
    global _category_embeddings
    _category_embeddings = None


async def classify_unmatched_segments(
    unmatched: list[tuple[str, str]],
) -> dict[str, str]:
    """Given segments the keyword classifier missed, return a
    ``{segment_id: trigger_type}`` map for those above the similarity
    threshold.

    Args:
        unmatched: list of ``(segment_id, text)`` for segments that
            keywords did not flag.

    Returns ``{}`` if disabled, no API key, embedding failure, or
    nothing crossed the threshold.
    """
    if not unmatched:
        return {}
    if not is_enabled():
        return {}
    if not _OPENAI_API_KEY:
        logger.info(
            "semantic_trigger: enabled but OPENAI_API_KEY missing — no-op"
        )
        return {}

    category_embeddings = await _ensure_category_embeddings()
    if category_embeddings is None:
        return {}

    try:
        texts = [text for _, text in unmatched]
        segment_vectors = await _embed_batch(texts)
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning(
            "semantic_trigger: segment embedding call failed — no-op",
            exc_info=True,
        )
        return {}

    decisions: dict[str, str] = {}
    for (segment_id, _text), vec in zip(unmatched, segment_vectors):
        best_category: str | None = None
        best_score = 0.0
        for category, cat_vec in category_embeddings.items():
            score = _cosine_similarity(vec, cat_vec)
            if score > best_score:
                best_category = category
                best_score = score
        if best_category and best_score >= _THRESHOLD:
            decisions[segment_id] = best_category
            logger.debug(
                "semantic_trigger: seg=%s → %s (score=%.3f)",
                segment_id, best_category, best_score,
            )

    if decisions:
        logger.info(
            "semantic_trigger: matched %d of %d unmatched segments "
            "(threshold=%.2f)",
            len(decisions), len(unmatched), _THRESHOLD,
        )
    return decisions
