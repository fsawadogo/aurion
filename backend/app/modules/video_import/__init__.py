"""Web-portal encounter-video import pipeline (VID-01…).

Processes a video uploaded through the web portal through the SAME backend
AI pipeline iOS uses (transcription → Stage 1 → vision Stage 2 → note),
producing a final note reviewable in the portal. The whole module ships
behind ``feature_flags.video_import_enabled`` (default False).

VID-01 (this slice) lands the foundation only: the ffmpeg audio-extraction
utility (``extraction``), job persistence helpers (``jobs``), and typed
errors (``errors``). The orchestrator, API endpoints, server-side frame
masking, and web UI land in later slices.
"""
