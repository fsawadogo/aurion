"""Per-specialty few-shot examples for Stage 1 prompts (Tier 2 / item E).

The base prompt teaches the model the *rules* (descriptive mode, source
traceability, schema). Few-shot examples teach it the *style* — how to
attribute statements, where the section boundaries fall, how to phrase
descriptive observations, when to mark a section pending_video vs
not_captured. One good worked example usually beats three more rule
sentences.

Examples live alongside templates as ``{key}.examples.json``. Each file
contains 1-3 transcript → note pairs that already conform to all the
rules the model is being asked to follow. Loader is cached on first
access; missing files silently degrade to no examples (the model still
gets the rules + style guidance).

Shape of an examples file:
    {
      "examples": [
        {
          "description": "short title shown to the model",
          "transcript": [
            {"id": "seg_001", "start_ms": 0, "end_ms": 1000, "text": "..."}
          ],
          "note": {
            "sections": [
              {"id": "chief_complaint", "status": "populated",
               "claims": [{"id": "claim_001", "text": "...",
                           "source_type": "transcript", "source_id": "seg_001",
                           "source_quote": "..."}]}
            ]
          }
        }
      ]
    }

NEVER ship examples that contain interpretive ("consistent with…") or
diagnostic ("suggests…") language — they would teach the model to do
the same.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("aurion.note_gen.few_shot")

_EXAMPLES_DIR = Path(__file__).parent / "templates"
_cache: dict[str, list[dict]] = {}


def get_few_shot_examples(specialty_key: str) -> list[dict]:
    """Return cached examples for ``specialty_key``. Empty list if no
    examples file exists or the file is malformed (logged, never raises).
    """
    if specialty_key in _cache:
        return _cache[specialty_key]

    path = _EXAMPLES_DIR / f"{specialty_key}.examples.json"
    if not path.exists():
        _cache[specialty_key] = []
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        examples = raw.get("examples", [])
        if not isinstance(examples, list):
            raise ValueError("'examples' must be a list")
        _cache[specialty_key] = examples
        logger.info(
            "Loaded %d few-shot example(s) for specialty=%s",
            len(examples), specialty_key,
        )
        return examples
    except Exception as exc:  # noqa: BLE001 — defensive against operator-authored JSON
        logger.error(
            "Failed to load few-shot examples for %s: %s — proceeding without",
            specialty_key, exc,
        )
        _cache[specialty_key] = []
        return []


def render_examples_block(examples: list[dict]) -> str:
    """Render examples as a prompt-ready string. Returns "" when empty.

    Format chosen so the model can read it left-to-right:
        EXAMPLE 1 ({description}):
        TRANSCRIPT:
        [seg_001] (0ms-4500ms): Hi, what brings you in today?
        ...
        IDEAL NOTE:
        { "sections": [...] }
    """
    if not examples:
        return ""

    blocks: list[str] = ["WORKED EXAMPLES — follow this shape + attribution style:"]
    for i, example in enumerate(examples, start=1):
        desc = example.get("description", "")
        transcript = example.get("transcript", [])
        note = example.get("note", {})

        header = f"\nEXAMPLE {i}"
        if desc:
            header += f" ({desc})"
        blocks.append(header + ":")

        if transcript:
            blocks.append("TRANSCRIPT:")
            for seg in transcript:
                blocks.append(
                    f"  [{seg.get('id', '')}] ({seg.get('start_ms', 0)}ms"
                    f"–{seg.get('end_ms', 0)}ms): {seg.get('text', '')}"
                )

        if note:
            blocks.append("IDEAL NOTE:")
            blocks.append(json.dumps(note, indent=2))

    blocks.append("")  # trailing newline before the real transcript starts
    return "\n".join(blocks) + "\n"


def _clear_cache() -> None:
    """For tests — reset the loader cache."""
    _cache.clear()
