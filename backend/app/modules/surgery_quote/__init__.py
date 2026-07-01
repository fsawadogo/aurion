"""Surgery quote add-on (note-Options phase 3).

Generates a patient-facing surgical cost quote from an approved note. The
LLM extracts ONLY the procedures the note records as discussed / planned —
grounded, descriptive-mode: it never invents a procedure and never fabricates
a price (Aurion has no fee schedule). The physician fills the fees and edits
line items, then exports the quote as a document to hand the patient.

The LLM call routes through the provider registry's note_generation provider
via ``generate_text`` (same abstraction as patient_summary). Ownership is
enforced by the route layer (``get_owned_session_or_404``), not here.
"""
