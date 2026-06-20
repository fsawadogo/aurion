# Plan — VID-11 (final)

## Task
Presigned S3 multipart / resumable upload (backend endpoints + web engine).

## Why
Last deferred item. A single PUT is fragile for large videos (no resume, dies
on a flaky connection near the end). Multipart uploads one presigned part at a
time against the same job s3_key; the single-PUT path stays the small-file
default.

## Approach
- Backend `api/v1/video_import.py`: `multipart/start` (open S3 multipart for the
  job key, server-chosen 32 MB parts, presign each), `multipart/{n}/presign`
  (re-mint), `multipart/complete` (sorted parts), `multipart/abort`. Clinician
  `/me` surface; admin keeps single-PUT.
- Web `VideoImportClient` + `portal-api.ts`: above a 100 MB threshold the
  clinician surface slices the file, PUTs each part (XHR, collects the
  CORS-exposed ETag), then completes; aborts the S3 upload on any part failure.

## Acceptance criteria
- [ ] `start_multipart` computes ceil(size/part_size) parts + opens the S3 upload (unit-tested).
- [ ] complete sorts parts ascending + calls S3; abort calls S3 (unit-tested).
- [ ] `tsc` clean; full web vitest suite green.

## Out of scope
Admin multipart surface, cross-reload resume, parallel part uploads.

## Test plan
1. `python3 -m pytest tests/unit/test_video_import_multipart.py -q`
2. `cd web && CI=true npx vitest run`

## Security implications
Parts go browser→S3 with no Aurion bearer (presign is the auth); CORS is scoped
to the portal origin (VID-08) and exposes only ETag. Abort + the bucket's
abort-incomplete-multipart lifecycle prevent orphaned parts. Still dark behind
`video_import_enabled`.
