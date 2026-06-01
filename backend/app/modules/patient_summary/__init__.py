"""Plain-language after-visit summary derived from an approved note.

LLM call is routed through the provider registry's note_generation
provider via `generate_text` (added to the base abstract in PR #152).
The system prompt is strictly descriptive — patient-facing summaries
must never introduce diagnostic conclusions beyond what the source
note already records.

Today this is read by the web portal review screen; iOS consumption
is a separate slice.
"""
