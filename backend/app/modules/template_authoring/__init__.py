"""Conversational specialty-template builder.

Pairs an LLM (routed through the existing note_generation provider
registry) with the `Template` Pydantic schema so physicians can chat
their way to a custom note template — schema-valid by construction.

Wire-level entry point is `app/api/v1/me.py:/me/template-authoring/*`.
"""
