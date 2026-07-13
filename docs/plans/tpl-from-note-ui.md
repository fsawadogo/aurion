# Plan — tpl-from-note-ui: "From a past encounter" seed in Create-with-AI (web)

## Task
Wire the `from-note` backend (#650) into the clinician web portal: a
flag-gated "From a past encounter" entry that turns one of the clinician's own
past notes into a template draft in the existing Create-with-AI chat.

## Why
The template-chat backend is complete but headless + DARK. This is the smallest
slice that makes the note→template feature reachable for Marie & Perry. Most of
the web already exists (tabbed Templates page, `AiBuilder` chat, upload-to-seed);
the only gaps were a client fn, client-side flag exposure, and the entry point.

## Approach (vertical slice)
- **Backend**: expose `template_authoring_chat_enabled` on `PortalFeatureFlagsResponse`
  + the `/me/feature-flags` handler (`me.py`), so the portal can gate the entry.
- **Web client**: `startTemplateAuthoringFromNote(sessionId)` in `portal-api.ts`;
  add the flag to `getPortalFeatureFlags`'s return type.
- **Web UI** (`templates/page.tsx`): a "From a past encounter" button (shown only
  when the flag is on) → a Modal picker over `listMySessions()` filtered to
  note-bearing states → on pick, mint an authoring session and `router.push` into
  the existing `/new?session=<id>` AI builder (same pattern as the upload flow).
- **i18n** (en/fr) + a vitest spec.

Reuses: the `AiBuilder`/`?session=` resume flow, `listMySessions`, `Modal`,
`LoadingSkeleton`, `PageHeader`, `humanizeError`, the `getPortalFeatureFlags`
gating pattern (mirrors the Sidebar's video-import gating).

## Acceptance criteria
- [ ] AC-1: `template_authoring_chat_enabled` is surfaced by `/me/feature-flags` and DARK by default — `test_portal_feature_flags.py`.
- [ ] AC-2: the "From a past encounter" button is hidden when the flag is off, shown when on — vitest.
- [ ] AC-3: the picker lists only note-bearing encounters (AWAITING_REVIEW+) and picking one calls `startTemplateAuthoringFromNote(sessionId)` — vitest.
- [ ] AC-4: whole web suite + `next build` (type-check) + backend suite stay green.

## Out of scope / follow-up
- Per-role / per-user flag targeting (org-level bool for now).
- The full tabbed Visit-Type → Context → Template restructure (already largely
  exists via `VisitTypesTab` + `VisitTypeContextsEditor`) — a later PR if the
  mockup's exact IA is wanted.
- In-composer "from a past encounter" chip inside the chat (this PR uses the
  templates-page button, matching the existing upload entry).

## Test plan (executable)
1. `cd backend && python -m pytest tests/unit/ -q` → all pass (portal-flag test + the SimpleNamespace fixture fix).
2. `cd web && npx vitest run` → all pass (Templates spec: flag gate + picker seed).
3. `cd web && npm run lint && npm run build` → clean (build is the type-check gate).

## Security implications
The picker shows the caller's own encounters (owner-scoped `listMySessions`);
`external_reference_id` is owner-only PHI already shown on the notes list. The
note→template extraction is the #650 PHI-safe path (note never persisted, audited,
structure-only). Feature is DARK by default (flag off → button hidden AND the
endpoint 403s). No new PHI in logs/errors.
