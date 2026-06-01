"""Live note preview (#64) — streaming draft snapshots during recording.

Lets the physician watch the note assemble in near-real-time while
still in the room with the patient.

This is NOT the canonical Stage 1 pipeline. Previews are best-effort,
clearly labeled DRAFT in the API response, and ignored by the
recording-stop Stage 1 generation. The preview path has its own
provider call so a hung preview never blocks the canonical pipeline.
"""
