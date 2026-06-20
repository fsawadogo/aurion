# Plan — VID-09

## Task
Expose session `import_source` in the API + a clinician-readable
`GET /me/feature-flags` (backend support for VID-10 web polish).

## Why
The "Uploaded" inbox badge needs the session origin in the response; the
nav-item-gating needs a non-admin way to read `video_import_enabled`.

## Approach
- `sessions.py`: add `import_source` to `SessionResponse` + `_to_response`.
- `me.py`: `GET /me/feature-flags` → `{video_import_enabled}` (any auth role;
  read-only; distinct from the ADMIN-only `/admin/feature-flags` writer).

## Acceptance criteria
- [ ] `_to_response` surfaces `import_source` ("video_upload" / None) — unit-tested.
- [ ] `/me/feature-flags` returns the live `video_import_enabled` flag — unit-tested.

## Out of scope
Web consumption (VID-10), multipart (VID-11).

## Test plan
1. `python3 -m pytest tests/unit/test_video_import_session_origin.py -q`
2. `python3 -m pytest tests/unit -q`

## Security implications
`import_source` is not PHI. `/me/feature-flags` exposes only a non-sensitive
boolean subset, read-only.
