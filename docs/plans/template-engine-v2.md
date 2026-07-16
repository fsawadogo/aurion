# Template Engine v2 — Heidi-class authoring on Aurion's grounded pipeline

**Goal.** Give clinicians a template engine with the authoring ergonomics of
Heidi Health's (rich per-section guidance, style control, verbatim boilerplate,
live example preview, generate-from-description) while keeping — and
showcasing — Aurion's structural advantage: every generated statement is a
claim with code-enforced provenance. Heidi's template *is* the prompt and its
grounding is prompt-discipline only; ours stays a **contract the pipeline
enforces**.

**Competitive source.** Live teardown of Heidi's engine 2026-07-15 (memory:
`reference_heidi_template_engine.md`). Their DSL = 4 primitives: plain-text
headings, `[placeholders]` (what), `(instructions)` (how + omission), and
`"verbatim"` quotes. ~80% of their stock template text is per-placeholder
"only include if explicitly mentioned … otherwise leave blank" — hallucination
control we already get from the claims schema, `status: not_captured`, and the
runtime validators. **We adopt their expressiveness, not their noise.**

**Decisions (from Faïçal, 2026-07-15).**
- Feasibility approved; build in loop-sized slices with **backend/web parity
  in each phase** (a backend field nobody can author or see doesn't count as
  shipped).
- **Sequencing:** backlog **Cohort 7**, queued behind Cohort 6 — Template
  Functional Loop (same-day weekly directive: finish template selection +
  output formatting before new features). This plan is the continuation of
  Cohort 6's "Développer moteur modèles". It complements — and must not
  duplicate — loop-2 (Library SOAP seed) and loop-4 (change-template picker):
  TPL-V2-5's picker upgrades layer ON TOP of loop-4's picker, and the v2
  schema must load the loop-2 seeded SOAP row unchanged.
- Grounding is non-negotiable: no template field may authorize inference.
  Grounded Synthesis stays governed solely by `grounded_synthesis_enabled` +
  its sign-off — template directives are style/structure-scoped only.
- Marketplace/community and PDF-form templates: **explicitly deferred**
  (post-pilot; org shared templates cover team sharing today).

## Architecture mapping (Heidi primitive → Aurion)

| Heidi | Aurion v2 |
|---|---|
| Plain-text heading | `Template.sections[].id/title` (exists) |
| `[placeholder]` | NEW `sections[].content_slots[]` — `{id, label, capture}` sub-section guidance ("Symptom characteristics" → "duration, timing, location, quality, severity") |
| `(instruction)` | NEW `sections[].style` + template-level `global_style[]` — bounded, sanitized directives (narrative vs bullets, ordering, tone) |
| `"verbatim"` | NEW `verbatim_blocks[]` — fixed text emitted as claims with `source_type: "template"`, `source_id: "tpl_{key}_{block_id}"` — *better* than Heidi: boilerplate carries auditable provenance |
| per-placeholder omission rules | NOT ported — enforced in code already (`not_captured`, no fabrication, validators) |
| chat editing + versioning | exists (template-authoring chat, custom_templates versioning) |
| upload-example / from-encounter seeding | exists (`/me/custom-templates/upload`, `/me/template-authoring/from-note`) |
| live Example tab vs sample transcript | NEW — TPL-V2-4 |
| "Search or generate anything" picker | NEW (thin) — TPL-V2-5 |
| Auto template per session | partially exists (visit-type ladder, `resolve_context_template_key`) — TPL-V2-5 exposes it as a suggestion |

## Safety model (defense in depth, all slices)

1. **Save-time sanitizer** (TPL-V2-0): style directives validated against an
   allowlist grammar + banlist screen (reject "diagnose", "suggest",
   "infer", "recommend treatment", prompt-injection markers). Applies to
   authoring chat finalize, direct API create/update, and upload extraction.
2. **Render-time scoping** (TPL-V2-2): v2 fields are injected into
   `build_stage1_user_prompt` inside a fenced "STYLE & STRUCTURE" block that
   the system prompt explicitly subordinates to the grounding rules.
3. **Runtime validators unchanged**: uncited content is blocked regardless of
   template text. A hostile template can degrade style, never grounding.
4. **Flag**: `template_engine_v2_enabled` (AppConfig + admin API mirror +
   Terraform validator + portal Feature Flags "Chat tools"-style group entry).
   OFF → Stage 1 prompt byte-identical to today.

## Slices (loop-sized; each states its backend AND web deliverable)

### TPL-V2-0 · Schema v2 + sanitizer (backend) — 2d
- `core/types.py Template`: additive `sections[].content_slots[]`
  (`{id, label, capture}`, snake_case ids, caps: ≤10 slots/section, ≤200 chars
  each), `sections[].style: Optional[str]` (≤240 chars), `global_style:
  list[str]` (≤5 × 240), `verbatim_blocks[]` (`{id, section_id, text}`,
  ≤5 × 500 chars).
- Sanitizer module `modules/custom_templates/sanitize.py` — banlist + length
  caps + section_id referential checks; wired into `create_for_owner`,
  update, finalize_authoring, upload extraction. Violations → 422 with the
  offending directive named.
- Existing templates validate unchanged (all new fields default empty).
- Tests: schema round-trip, caps, sanitizer accept/reject table, legacy JSON
  templates load.
- **Web parity in this slice:** none required (dark data) — parity lands in
  TPL-V2-3; this is the only backend-only slice and it is a dependency root.

### TPL-V2-1 · `source_type: "template"` provenance (backend + web + iOS chip) — 2d
- `NoteClaim.source_type` literal += `"template"`; `source_id` convention
  `tpl_{template_key}_{block_id}`; validators + citation-expansion
  (`/detail`) return the template display name + block text as the anchor.
- Note assembly: verbatim blocks injected as claims at section end during
  Stage 1 assembly (code, not LLM — the LLM never sees them as content to
  rewrite). Excluded from completeness scoring.
- **Web:** NoteSectionCard + citation popover render a "Template" chip
  (like the measurement chip precedent) — EN+FR.
- **iOS (small):** render unknown/new source chip gracefully; explicit
  "Template" label. Ship with next bundled TestFlight (no dedicated build).
- Tests: schema, assembly injection, `/detail` expansion, chip snapshot.
- Depends on TPL-V2-0.

### TPL-V2-2 · Prompt rendering behind flag + eval gate (backend) — 3d
- `template_engine_v2_enabled` flag: schema + admin mirror + `infrastructure/
  appconfig.tf` validator + portal Feature Flags page toggle + `/me/feature-flags`
  (that's the flag's own backend/web parity).
- `build_stage1_user_prompt`: render content_slots as per-section capture
  guidance, style directives in the fenced STYLE & STRUCTURE block. OFF →
  byte-identical output (assert in test, `specialty_style_in_prompt_enabled`
  precedent).
- Interplay: composes with specialty style guidance (template directives take
  precedence within the fence; both subordinate to grounding rules).
- **Eval gate:** run the GS-9-style harness (baseline vs v2-on) over the
  grounded example transcripts before any dev flip; receipt committed to
  `docs/sign-off/`.
- Tests: prompt-builder golden tests on/off, precedence, token-length cap.
- Depends on TPL-V2-0.

### TPL-V2-3 · Authoring editor parity (web + backend prompt update) — 3d
- **Backend:** template-authoring chat system prompt learns v2 fields (emit
  slots/style/verbatim in drafts; sanitizer errors fed back as correction
  re-prompts — existing retry loop). From-note + upload seeds may propose
  content_slots from structure.
- **Web (`/portal/templates/new` + `[id]` editor):**
  - Draft preview card renders sections → slots → style → verbatim blocks.
  - NEW read-only **"Structure" text view**: Heidi-style plain-text render
    (headings / `[slot label]` / `(style)` / `"verbatim"`) with Copy — chat
    remains the only edit surface (no free-text round-trip parsing).
  - EN+FR strings.
- Tests: chat draft with v2 fields validates + persists; structure render
  snapshot; sanitizer rejection surfaces in chat as correction, not 500.
- Depends on TPL-V2-0 (schema); TPL-V2-2 not required (authoring works dark).

### TPL-V2-4 · Live example preview (backend + web) — 3d
- **Backend:** `POST /me/template-authoring/{id}/preview` — sandboxed Stage 1
  render of the CURRENT DRAFT against a bundled synthetic transcript
  (`note_gen/templates/*.grounded.examples.json` corpus; `?specialty=` picks
  the transcript). No session row, no note version, no audit-note events; one
  `TEMPLATE_PREVIEW_GENERATED` audit event (template id only, no content).
  Rate-limit 6/min/user; provider via registry (honors overrides);
  `user_prompt_testing_enabled` sandbox precedent.
- **Web:** "Example" tab next to the draft preview — renders the preview note
  (sections/claims, citations pointing at the synthetic transcript),
  specialty transcript switcher, regenerate button, "synthetic encounter —
  not patient data" banner. EN+FR.
- Tests: sandbox produces no session/note rows; preview honors v2 fields when
  flag ON and structural-only when OFF; rate limit.
- Depends on TPL-V2-2 (renders through the same prompt path) + TPL-V2-3 (UI).

### TPL-V2-5 · Picker upgrades: generate-from-description + Auto suggestion (backend + web) — 2d
- **Backend:** `GET /me/sessions/{id}/template-suggestion` — exposes the
  existing `resolve_context_template_key` ladder result + specialty floor as
  an explainable suggestion (`{template_key/custom_id, reason}`); no new
  resolution logic.
- **Web:** template picker (wherever the portal picks templates — video
  import, visit types tab) gets (a) "Generate from description…" entry that
  opens the authoring chat pre-seeded with the typed phrase (reuses
  `startTemplateAuthoring` + first message), (b) "Suggested" row showing the
  server suggestion with its reason. EN+FR.
- Tests: suggestion endpoint ladder cases; picker renders suggestion; seeded
  chat opens with phrase as first user turn.
- Depends on TPL-V2-3.

## Explicitly deferred (do NOT pick up)
- Community/marketplace layer (adoption counts, public sharing) — post-pilot.
- PDF-form template type / form auto-fill — post-pilot.
- Free-text structure editing with round-trip parsing — chat is the edit
  surface by design.
- Any template directive that loosens grounding — forbidden, not deferred.

## Status: ⛔ PLANNING ONLY — implementation not authorized

Faïçal (2026-07-15): plan approved for the backlog, **"don't implement yet."**
No TPL-V2 slice may start — regardless of lane availability or upstream
cohorts completing — until he flips the Cohort 7 hold in
`.claude/state/backlog.md`.

## Rollout
1. TPL-V2-0 → TPL-V2-1 → TPL-V2-2 merge dark; eval receipt.
2. TPL-V2-3/4/5 merge (authoring UX works while generation flag is dark —
   drafts persist v2 fields, preview requires flag ON in dev only).
3. Flip `template_engine_v2_enabled` in dev via Admin → Feature Flags after
   the eval receipt is green; pilot physicians validate on their own
   templates; keep OFF for prod-equivalent settings until note-quality
   review.

## Success criteria
- A clinician can, portal-only: describe or seed a template → refine slots/
  style/verbatim in chat → watch a live example rebuild against a synthetic
  transcript → save → select it (or accept the suggestion) for a session.
- With the flag ON, Stage 1 notes honor slots/style/verbatim; every claim
  still carries a valid `source_id` (template claims included); citation
  traceability metric stays ≥ 95%.
- With the flag OFF, Stage 1 prompts and outputs are byte-identical to today.
- Sanitizer blocks the red-team directive table (committed with TPL-V2-0
  tests) at save time.
