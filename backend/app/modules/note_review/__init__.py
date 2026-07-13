"""Conversational "fix this note" assistant (note-review chat).

A physician sends a plain-language request ("shorten the HPI", "add that she's
allergic to sulfa") while reviewing a generated note; an LLM emits structured
edit ops which are applied to the note and saved as a new immutable version.
Grounding is preserved: an added claim is cited to a real transcript segment
when the content is in the transcript, otherwise recorded as a physician edit —
a citation is never fabricated.
"""
