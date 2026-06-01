"""CRUD service for physician-owned custom note templates.

Today these rows are consumed only by the web portal's templates UI.
A follow-up PR will extend `note_gen/service.py:load_templates()` to
merge custom rows with the file-based built-ins so they can actually
drive note generation.
"""
