# ps-fu5 — feature-flag the clinician AI Prompts page to note-gen only

Clinicians should be able to see **only the Note-generation prompt** on
`/portal/prompts`, hiding vision / extraction / preview — behind a flag.

## The flag

`feature_flags.clinician_prompts_note_only` (AppConfig). **Ships dark**
(`False` = all categories, current behaviour). When `True`, the clinician AI
Prompts list is narrowed to the `note` category. **Support roles**
(ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER) always see the full catalog for
transparency, regardless of the flag.

It's a **display scope** only — it never changes what any prompt resolves to,
and it does not gate the per-physician PATCH/DELETE (those operate on a specific
`prompt_id` and stay open; the flag reduces UI noise, it is not access control).

## Changes (backend only)

- `schema.py`: `clinician_prompts_note_only: bool = False` on `FeatureFlagsConfig`.
- `feature_flags.py`: mirror field on `FeatureFlagsResponse` + `_build_response`
  (the `test_response_mirrors_config_field_for_field` lock requires it).
- `infrastructure/appconfig.tf`: add to the `feature_flags` validator (NOT
  `required`); the drift-guard test requires it. **Needs `terraform apply`.**
- `me_prompts.py`: `_visible_prompts(role)` filters the registry to `note` for a
  CLINICIAN when the flag is on; `list_my_prompts` uses it (and only resolves
  publications for the visible prompts).
- **No web change** — the page already renders `null` for empty categories
  (`prompts/page.tsx:225`), so a note-only response shows just the note section.

## Deploy order
Apply the Terraform validator together with (or before) the backend deploy: the
new backend emits `clinician_prompts_note_only` in the feature_flags dump on any
save, and the old validator (`additionalProperties:false`) would reject it. The
flag ships dark, so nothing changes for clinicians until it's flipped.

## Verify
- `ruff`; `_visible_prompts` unit (clinician note-only / clinician full / support
  full); drift-guard + mirror-lock auto-cover the plumbing; full unit + prompt
  integration green.
- `/simplify` → `/code-review` → PR (stacked on #534).
