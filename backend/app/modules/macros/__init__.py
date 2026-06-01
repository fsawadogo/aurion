"""Per-physician macro / smart-phrase storage and lifecycle.

Macros are owner-scoped (`PhysicianMacroModel.owner_id`); the CRUD
surface enforces ownership at the service boundary and the audit
log captures lifecycle events without ever recording the macro
body itself.

Today macros are consumed only by the web portal's note-edit
expansion. iOS macro UI is a separate slice (#60 iOS-side).
"""
