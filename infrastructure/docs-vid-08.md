# VID-08 — video-imports S3 bucket (infra)

Provisions the dedicated `aurion-video-imports-{env}-{acct}` bucket for the
encounter-video import feature (VID-01..07). Raw uploaded videos land here
transiently (presigned browser PUT) and are purged in-band after extraction.

- SSE-KMS (aws_kms_key.main), versioning disabled, all public access blocked,
  EnforceSSL bucket policy, S3 access logging — same posture as the frames bucket.
- Short backstop lifecycle TTL (`var.video_import_retention_days`, default 1 day)
  + abort-incomplete-multipart after 1 day (for VID-10).
- CORS scoped to `https://${var.web_portal_subdomain}` (PUT/GET, expose ETag).
- ECS task role granted RW; `S3_VIDEO_IMPORTS_BUCKET` injected into the task env
  (consumed by app/core/s3.py::VIDEO_IMPORTS_BUCKET).

Apply is intentionally left to the infra pipeline (provisions real resources).
`terraform fmt` clean + `terraform validate` passing.
