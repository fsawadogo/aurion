# Plan — #63 measurement persistence slice (backend)

Second #63 slice. Phase A (#432) landed the schema/config/audit foundation
(`MeasurementCitation`, `MeasurementConfig`, `measurement_enabled` flag,
`MEASUREMENT_*` audit events). This slice gives those types a home: a table,
an idempotent repository, and the clinician-facing ingest/list endpoint that
the iOS AR instrument will POST to once it exists.

Ships **dark** — `feature_flags.measurement_enabled` defaults False, so the
endpoint 403s in every environment until a deliberate AppConfig flip.

## Scope

- `core/models.py` — `MeasurementCitationModel` (`measurement_citations`,
  unique on `(session_id, measurement_id)`, `session_id` indexed).
- `alembic/0040` — create the table. Chains from 0039, single head.
- `modules/measurement/repository.py` — `persist` (idempotent on
  session+measurement_id, forces `certified_measurement=False`),
  `get_by_measurement_id`, `list_for_session`.
- `api/v1/me_measurements.py` — `POST/GET /me/sessions/{id}/measurements`,
  owner-scoped, gated by `measurement_enabled` + allowed-methods +
  confidence floor; audits `MEASUREMENT_GENERATED` (+ `REVIEWED` when
  physician-confirmed) with PHI-free kwargs only.
- `modules/session/service.py` — add the model to `_SESSION_CHILD_MODELS`
  so a measurement row is hard-deleted with its session (derived PHI,
  design §6.2).
- `.gitignore` — ignore the local `ResendAPIKey.txt` secret hand-off file
  (defensive; folded in from the Resend thread).

## Out of scope

- **Note-injection** — routing a confirmed measurement into the note as a
  `NoteClaim(source_type="measurement")` (kind→section map). Next slice.
- **iOS AR instrument** — tap-to-place wound endpoints + AR goniometer +
  NoteReview confirm card. Needs a device.
- **Accuracy-characterization study (N≥30) + legal export-label review** —
  gates any *patient* use; not a code slice.

## Non-negotiables honoured

- Numeric `value` is derived PHI → never logged, never an audit kwarg.
- `certified_measurement` forced False in the repo regardless of input
  ("approximate, not certified" is structural, design §6).
- Audit append-only; owner-scoped reads; secrets untouched.
- Descriptive mode: this slice stores numbers + provenance only, no
  interpretation, no trends, no AI call.

## Test plan

`python3 -m pytest tests/unit/ -q` · `ruff check` · `alembic heads` (single).
New: `tests/unit/test_measurement_persistence.py` — gating (403/422/400/404),
idempotent re-POST (no double audit/commit), audit event ordering + PHI
guard, repo idempotency + forced-uncertified, erasure wiring.
