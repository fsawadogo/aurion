# Plan — VID-10

## Task
Web polish: admin/eval upload route, flag-gated nav, "Uploaded" inbox badge.

## Approach
- `VideoImportClient`: `surface` prop ("clinician" | "admin") selects the API
  set (/me vs /admin) + the post-redirect (/portal/notes vs /sessions).
- `app/portal/admin/upload/page.tsx`: renders `<VideoImportClient surface="admin" />`.
- `lib/portal-api.ts`: `getPortalFeatureFlags()`. `lib/api.ts`: admin
  create/process/status wrappers.
- `Sidebar.tsx`: admin upload nav entry (EVAL_TEAM, ADMIN); both upload entries
  hidden until `/me/feature-flags` reports `video_import_enabled` (default-hidden
  while loading).
- `notes/page.tsx`: "Uploaded" badge when `import_source === "video_upload"`.
- `types/index.ts`: `Session.import_source`. i18n: `Sidebar.nav.evalUpload`,
  `NotesList.uploaded` (EN + FR).

## Acceptance criteria
- [ ] `tsc --noEmit` clean.
- [ ] Upload nav entries hidden unless the flag is on.
- [ ] Admin route posts to /admin/video-imports + redirects to /sessions.
- [ ] Uploaded badge renders for import sessions.

## Out of scope
Multipart (VID-11), admin on-behalf selector.

## Test plan
1. `npx tsc --noEmit`
