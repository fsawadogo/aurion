# Aurion Autonomous Loop — Backlog

Canonical task list. The driver loop reads top-to-bottom and works the
topmost Active item matching its lane. Format per line:

    - [ ] {ID} {one-line description} — {effort}d — lane: {backend|ios} — {dependencies}

When a task moves through states, the loop edits this file in place:
Active → In flight → Done (or → Blocked on triple failure).

Last seeded: 2026-05-14. Last updated: 2026-07-17 (seeded **Cohort 7 — Template Engine** as the new CURRENT PRIORITY; demoted Cohort 6 to NEXT). Prior: 2026-07-15 (added Cohort 6 — Template Functional Loop; demoted Cohort 5 per the 2026-07-15 weekly). Prior: 2026-07-01 (added Cohort 5 — Grounded AI Scribe: #620–#625; see memory/grounded-scribe-gap-map.md). Prior: 2026-05-30 (seeded 17 backend issues from GitHub per CTO's "implement all backend" directive).

**Seeding provenance for Cohort 7 (recorded, not silent).** The 2026-07-15 note said Template Engine v2 was a PLAN ONLY — *"NOT queued per Faïçal 'just the doc for now'; do not seed it as a cohort without his go."* **Superseded 2026-07-17 by Uzziel** (CPO, co-owner of *"Développer moteur template"*): Faïçal is not implementing the v2 doc himself and asked Uzziel to drive the template system. Cohort 7 below is the **generation core** — a different, narrower scope than `docs/plans/template-engine-v2.md`, which covers authoring ergonomics and still follows.

## Active

### Cohort 7 — Template Engine · generation core (CURRENT PRIORITY) — Uzziel, 2026-07-17
The template becomes what turns **transcript AND frames** into the note. Marie, 2026-07-15: notes are *"trop verbeuse… encombré de détails non pertinents, tels que **des descriptions physiques**."* Uzziel's framing: frames must be an **INPUT the template shapes**, not a description pasted in — those are the same problem, because the "descriptions physiques" cluttering the note ARE the raw frame captions.

Traced 2026-07-17: the template already drives the transcript half (`sections[].description` injected verbatim, `providers/note_gen/shared.py:205-216`) but **never reaches the frames half** — `caption_visual_evidence` is template-blind and `merge_visual_citations` pastes `caption.visual_description` verbatim (`vision/service.py:882`) into a hardcoded section list. No verbosity knob exists (`shared.py:259` is hardcoded + test-locked). Full plan: `docs/plans/` (approved 2026-07-17).

Grounded fusion of frame+transcript into one multi-cited claim is **designed-for, not built** — machinery exists but is dark behind `grounded_synthesis_enabled` pending GS-9. TE-3/TE-4 must keep the frame-contribution step as the SINGLE place the visual claim is constructed so a later flag flip needs no rearchitecture.

- [x] TE-1 · Detail level — backend MERGED 2026-07-20 (PR #672, incl. the brief-keeps-pertinent-negatives review fix); template-authoring control in the web editor; iOS note-Options rail = TE-1b MERGED 2026-07-27 (#695). Still open: the per-SESSION Brief/Standard/Detailed rail on the web note screen (#662 design) → loop-4b. Was: verbosity under template/session control — the direct fix for "trop verbeuse".
- [x] TE-2 · `resolve_session_template` — the template Stage 2 will use — MERGED 2026-07-20 (PR #663). Public resolver composing `stored_template_pin` + `_resolve_stage1_template`. **Scope adjusted mid-build:** ruff flagged the Stage-2 wiring as dead code (assigned-never-used + a discarded DB query), so the boundary moved — TE-2 ships the resolver, **TE-3 wires it at the point of use** (original AC-5 moved to TE-3). Independent review found a reachable bug: `regenerate_note` rebuilt notes under a new template without re-pinning the session, so the note-review template switcher (#662) left the pin stale — fixed at the root. First task to pass the §9d stack-boots gate.
- [x] TE-3 · Template-aware frame capture (**the root fix**) — MERGED 2026-07-20 (PR #664). The target section's title + guidance now aim the caption prompt; composed at one site, no provider interface change. Ships dark behind the new `template_engine_enabled`. **Three review rounds, and rounds 2 and 3 each found the previous fix insufficient** — round 2 caught the raw `title` and the forgeable fence; round 3 caught that *the fix's own `section.id` fallback* was interpolated raw (the same unverified "it's a code identifier" assumption, one layer down), that zero-width chars and non-ASCII dashes defeated both regexes, that the mode-aware screen let grounded mode unlock diagnosis on the one path with no downstream backstop (→ new `validate_vision_guidance`), and that template resolution was fail-CLOSED. `api/v1/vision.py` had zero coverage and two ACs named tests that never existed. All 11 fixes mutation-tested. **Lesson worth keeping: a fix commit needs its own independent review — mine was wrong twice.**
- [x] TE-3b · Portal toggle for `template_engine_enabled` — MERGED 2026-07-20 (PR #665). The engine is now flippable from Admin → Feature Flags; **leave it OFF** until an eval receipt shows notes improve (not meaningful until TE-4). Kept the page's `FLAG_GROUPS` hardcoded ON PURPOSE — it is an allowlist of flags safe to flip from a web form, not an incomplete render; going generic would surface pipeline gates as innocuous switches and break `prompt_studio_roles` (a list). Added a drift guard: every `FLAG_GROUPS` key must resolve in en AND fr, plus a both-locale DOM scan, because a missing key does not crash — next-intl renders the key path. **Two traps worth remembering:** (1) Next.js forbids extra named exports from a page file, so `FLAG_GROUPS` had to move to its own module — `lint` and `vitest` both passed, only `npm run build` caught it; (2) `next lint`/`next build` do NOT type-check `tests/`, so a spec can add a `tsc --noEmit` error with CI still green.
- [x] TE-4 · Template-formatted frame merge — MERGED 2026-07-20 (PR #666). Routing now matches the template's `visual_trigger_keywords` against the ANCHOR'S TRANSCRIPT TEXT; claim text is built (image-meta opener stripped) at one site, `_build_visual_claim` (the D3 requirement). The recorded tier divergence is closed — routing runs against the pristine note before any mutation, and capture-time prediction passes the same args. **Review returned THREE blockers and two were DESIGN errors, worth remembering:** (a) I read "section HAS visual_trigger_keywords" as "section receives images" — they are SPOKEN PHRASES, and my version filed wound photos under `past_medical_history` / `vital_signs` / `developmental_history` in half the built-in templates; (b) my "drop no-finding captions" regex was an unanchored search that DELETED real findings from charts ("Bone is not visible at the base of the ulcer", "The left knee is not visible; the right knee shows a 4cm effusion") — a negative finding is real documentation. The right mechanism already existed: low-confidence captions are dropped pre-merge, so TE-3's prompt now asks for low confidence. **No content-based deletion path exists anywhere in the merge, and a test enforces that — do not reintroduce one.** Also: `stripped[0].upper()` turned `mg/dL` into `Mg/dL` (magnesium).
- [x] TE-4b · Generation + regeneration progress feedback — MERGED 2026-07-20 (PR #667). Upload stepper active-stage now pulses + elapsed clock; regeneration shows a ProgressBanner + dims the note (aria-busy). **The correctness half:** derived `noteBusy` once and gated every control that reads the note — review caught that I'd missed the PRIMARY "Copy to EHR" in the ActionRail (my test's `/^Copy$/i` anchor excluded it by construction), so a clinician could copy an about-to-be-discarded note. CI also flaked on a synchronous `getByRole` for the lang button (fixed → `findByRole`).
- [x] TE-4c · Note-review landscape layout (Heidi-style) — MERGED 2026-07-20 (PR #668). Killed `max-w-[720px]` + the 300px `ActionRail`; note is full-width. Sign-off moved to the toolbar right end as `SignOffControl` (approved→green "Signed · ready/exported" badge, carrying the identical noteBusy+conflict+Stage guards). "Copy to EHR" removed, single toolbar Copy survives. Review caught I'd turned the export-state + copy-hint into hover-only `title` tooltips — dead on the iPad pilot — so the badge shows state as visible text now.
- [x] TE-4d · Upload flow: visit-context → template (like iOS) — MERGED 2026-07-20 (PR #670). Backend reuses `resolve_context_template_key` (iOS-safe, empty ios/ diff); web takes specialty from profile (no picker) + visit-type/context pickers; direct template stays as override. Review APPROVE, no HIGH/MEDIUM. Was: 2d — 2d — lane: web+backend — depends on TE-4c — the web upload flow sends only `specialty`+`encounter_type`+direct `custom_template_id` and NEVER calls `resolve_context_template_key`, so it bypasses the clinician/org visit-type→template mapping that iOS uses. Add a visit-context picker to the upload form (sends `consultation_type`+`context_id`), add `context_id` to `CreateVideoImportRequest`, and have `create_import_session` call the SAME `resolve_context_template_key` iOS's `/sessions` route calls. **iOS-safe by construction: separate endpoint, REUSE the shared resolver (never modify its signature/behaviour).** Keep the direct template picker as an override (Uzziel: "keep both"). Backend `CreateVideoImportRequest` already accepts `consultation_type`/`encounter_context` — only `context_id` + the resolver call are missing. Uzziel 2026-07-20.
- [x] TE-4e · Specialty templates → profile default, out of the picker dropdowns — MERGED 2026-07-28 (PR #696: note-review "Change template" + per-context editor; TE-4g PR #699 finished the clinician Visit-Types dropdown). Backend still honours stored built-in pins (chip task_90a5d9aa). Was: 1-2d — lane: web(+backend?) — the note-review "Change template" dropdown (and the visit-type context editor) list all 8 built-in specialty templates via `BUILT_IN_TEMPLATE_KEYS`; Uzziel 2026-07-20: "specialty templates should be associated to default profile, not part of a drop down." The clinician's specialty already lives in `PhysicianProfile.primary_specialty` (models.py:248). Replace the flat 8-specialty list with a single "my specialty default" option + "My templates" (custom). SCOPE LOCKED (Uzziel 2026-07-20): profile-default wins EVERYWHERE, no forcing a specialty on upload — specialty is a profile property (`primary_specialty`), period. TE-4d folds in "upload specialty comes from profile, remove the picker". TE-4e = remove the 8-specialty flat list from the note-review "Change template" dropdown + `VisitTypeContextsEditor`; offer "my specialty default" + custom only.
- [x] WAF-BACKOFF · Stage-2 poll backoff — MERGED 2026-07-20 (PR #669). Root cause: `useStageTwoProgress` polled on a fixed 4s interval that ignored errors, so once the WAF tripped it kept the rate window full and the origin never recovered. Now exp backoff (4→60s cap) + give-up after 6 failures; mutation-tested. Dev WAF-limit bump still infra/Uzziel. Was: web — a failing poll/refetch retries fast enough to trip the per-IP WAF limit (2000/5min), then the whole origin 403s (all paths, no CORS header) — Uzziel hit this repeatedly 2026-07-20 (console screenshots show 2000+ errors). Add exponential backoff + a cap to the note-detail/session refetch and any tight poll. Root cause of the "stuck"/CORS-looking failures. Separate: dev WAF limit bump (`waf_rate_limit_per_5min` in dev.tfvars) is infra, Uzziel's call.

- [x] TE-4f · Templates → Visit Types tab: embed the rich per-context accordion — MERGED 2026-07-20 (2b9f651: accordion embedded with unified draft + one Save). Was: 1-2d — lane: web — Uzziel 2026-07-20: the Templates "Visit Types" tab is the FLAT one-default-per-visit-type surface; the RICH collapsible context editor (`VisitTypeContextsEditor`) is only in My Profile. Bring the accordion into the Templates tab too (KEEP the Profile copy — both edit `contexts_per_visit_type` via updateMyProfile, stay in sync). Keep the admin org-default tier. "like how marie wanted."
- [ ] TE-4h · One surface for visit-type templates — IN FLIGHT 2026-07-29 (lane-web/te-4h-visit-types-one-surface) — default template moves inside each accordion panel (editor learns `is_default`); flat clinician list + doubled headings + phantom-row defect removed; admin org list untouched. Approved mockup; TE-4g follow-up.
- [ ] TE-5 · Template-bound output shape — 3d — lane: backend — no blockers — build the tool-schema section enum from `template.sections`
- [ ] TE-5b · iOS export S/O/A/P grouping accepts template section ids — 1d — lane: ios — depends on TE-5 — `NoteDocumentBuilder.swift:272-276` hardcodes section ids; hand to Faïçal
- [ ] TE-6 · Mobile wiring contract for Faïçal (docs) — 1d — lane: backend — depends on TE-1..TE-5 — absorbs loop-5

### Cohort 6 — Template Functional Loop (NEXT — demoted 2026-07-17 behind Cohort 7) — set by the 2026-07-15 weekly; owner Uzziel
Faïçal, 2026-07-15: *"se concentrer sur l'achèvement de la boucle opérationnelle actuelle, à savoir la sélection de modèles et le formatage de sortie, avant d'introduire de nouvelles fonctionnalités"* — ~2 weeks, so the pilot can use it in clinical practice. Uzziel's assigned items: *"Corriger interface notes: regrouper les notes dans une seule zone de texte"*, *"Développer moteur modèles"*, *"Localiser modèle SOAP"*.

**This is the FIRST HALF of Cohort 5's own goal chain** (create template → map to visit type → pick → record → *then* a polished grounded note), not a competitor to it. Cohort 5 stays next; its note-CONTENT work (verbosity, grounded voice, medico-legal capture) is explicitly deferred until the loop closes, because real pilot usage of the loop is what produces the markup that work needs.

Mobile constraint: every capability lands server-side behind client-agnostic REST so Faïçal wires iOS afterwards with no server change. Prefer mechanisms needing zero client key lists — a seeded `is_shared` Library row resolves to iOS through the existing org visit-type map; a new built-in template key would need 5 web + 3 iOS files (incl. the Siri `AppEnum`).

- [x] loop-0 · Fix local DB SSL allowlist — MERGED 2026-07-17 (PR #659). Parses the host exactly (SQLAlchemy make_url) vs one more substring; also closed a latent over-match that dropped TLS on a remote host starting with "localhost". Prod TLS byte-identical. Unblocks the §9d "stack boots" gate.
- [ ] loop-1b · Close the same loss hole on `append-recording` — 2d — lane: **ios (Faïçal)** — ROUTED 2026-07-17 (Uzziel: do NOT touch iOS now; hand to Faïçal, fold into loop-5). iOS-only surface (`ResumeRecordingSheet.swift`); web has no append button; dark in prod (`note_options_enabled` off). Safe add path (Ask Aurion / assistNote) edits in place, unaffected.
- [ ] loop-2 · Seed the Library with SOAP — IN FLIGHT 2026-07-29 (lane-backend/loop-2-seed-library) — starter_library/soap.json ("SOAP — Universal", 4 required S/O/A/P sections from Marie's gold-note structure, no content committed) + idempotent seed_library.py (service-validated upsert, is_shared=True, admin owner). Post-merge operator step: run the seed against dev (or admin-UI the same JSON). Was: 2d — lane: backend — closes "Localiser modèle SOAP".
- [ ] loop-3 · Canonical note→text renderer + GET /notes/{id}/text (approved-only gate, NOTE_EXPORTED origin=clipboard) — 2d — lane: backend — no blockers — 8 renderers / 5 formats exist today; promote emr/fhir.py render_note_plain_text. loop-4's Copy carries a TODO(loop-3) to swap onto it.
- [x] loop-4 · Web: note-review redesign — single note document + action rail + Copy (ungated) + template/language switch via regenerate — MERGED 2026-07-17 (PR #662). Built from Uzziel's Claude Design import; /simplify + independent review done; conflict/approve/export gates preserved. Deferred → loop-4b: citation-visibility gate + Sources rail + audio replay + detail level + letter + cross-clinician sidebar.
- [ ] loop-5 · Mobile wiring contract for Faïçal (docs) — 1d — lane: backend — depends on loop-2, loop-3; now also carries the loop-1b iOS append-recording gate

### Cohort 5 — Grounded AI Scribe (NEXT — deferred behind Cohort 6 on 2026-07-15) — see memory/grounded-scribe-gap-map.md; epic #626
Goal: create template → map to visit type → pick visit type → record → **polished grounded (non-descriptive) note**. Ordered top-to-bottom = work order. #621/#622 change the AI-output boundary → sanctioned Grounded Synthesis path, dark behind `grounded_synthesis_enabled` + GS-9 sign-off (#551).
- [ ] #620 scribe-0 · Retire descriptive note-gen publication + de-conflict export disclaimers — 1d — lane: backend (+iOS disclaimer) — no blockers — NOTE: operational half (un-publish in Prompt Studio) is a human/portal action, not a loop task
- [x] #621 scribe-1 · Grounded Synthesis as a true mode (boundary always-on + additive overrides + missing-clinician + transparency) — MERGED 2026-07-01 (PR #627 + review-fix #628); parse-time source_id moved to #624
- [ ] #622 scribe-2 · Grounded-voice hardening (grounded specialty prefix, mandate synthesis, descriptive/thinning banlist) — 3d — lane: backend — depends on #621
- [ ] #624 scribe-4 · Note completeness + grounding integrity (stop_reason truncation, max_tokens, non-optional quote-support) — 3d — lane: backend — depends on #621
- [ ] #625 scribe-5 · Grounded scribe render/export (selectable text, hide citations for prod, attestation, A&P layout) — 8d — lane: ios (+web/backend export) — depends on #620
- [ ] #623 scribe-3 · iOS one-tap default context (optional UX; correctness already server-side) — 3d — lane: ios — no blockers
- [ ] scribe-6 · Medico-legal capture in the template library — 3d — lane: backend — no blockers — NEW 2026-07-15, from the loop-2 library audit. `complication`, `consent`, `benefit`, `outcome`, `expectation` appear **0 times** across all 8 templates; `risks counselled` / `trade-offs/cost when mentioned` exist only as a "when mentioned" sub-clause in 3 of 8 plan descriptions (ortho/MSK/plastics), and the two worked examples that model it (`claim_p3`) are unreachable while `grounded_synthesis_enabled` is off. This is Perry's 2026-06-17 #1 complaint ("AI notes drop medico-legal detail"). Note-CONTENT work → sits behind Cohort 6.
- [ ] scribe-7 · Finish the v1.0→v1.1 template enhancement pass — 2d — lane: backend — no blockers — NEW 2026-07-15. The library is two generations, split perfectly: `general`/`emergency_medicine`/`musculoskeletal`/`orthopedic_surgery`/`plastic_surgery` are v1.1 (prose descriptions 37–64 mean words, grounded-aware assessment, both example sets, grounded style variant); `family_medicine`/`internal_medicine`/`pediatrics` are v1.0 (~11-word noun phrases, `— no inference` assessments that CONTRADICT grounded mode, no grounded examples, no grounded style variant — mtimes Jun 2 vs Jun 29–30). Not pilot-blocking (Marie=ortho, Perry=plastics, both v1.1) — but the "no inference" contradiction bites the moment `grounded_synthesis_enabled` flips on.

### Cohort 1 — Foundations (post-pilot)
- [ ] #75 Portal · Org / multi-clinic + SSO (SAML/OIDC) — 15d — lane: backend — no blockers
- [x] #72 Portal · Template + visual-trigger keyword mgmt — foundation shipped 2026-05-30 (PR #112, commit 7631eaa); runtime cache + UI = follow-ups
- [x] #76 Portal · Alerting & notifications — foundation shipped 2026-05-30 (PR #111, commit e3a4a22); SLA trigger + email/SMS sinks + ack flow + UI = follow-ups

### Cohort 2 — Telemetry + Compliance — ✅ FOUNDATIONS COMPLETE
- [x] #73 Portal · Provider cost & usage dashboard — foundation shipped 2026-05-30 (PR #114, commit c402d55); base.py interface refactor + vision/transcription wiring + web UI = follow-ups
- [x] #74 Portal · Model/provider A-B comparison — foundation shipped 2026-05-30 (PR #116, commit 714b7c8); quality-side join with eval_scores + web UI = follow-ups
- [x] #77 Portal · Automated compliance reporting — foundation shipped 2026-05-30 (PR #117, commit d87b992); cron scheduling + masking/retention types + HSM signing + web UI = follow-ups
- [x] #70 Specialty template expansion — shipped 2026-05-30 (PR #118, commit 4343c48); family_medicine + internal_medicine + pediatrics added (5 → 8)

### Cohort 3 — Scribe extensions
- [x] #61 iOS · Longitudinal patient context across encounters — foundation shipped 2026-06-01 (PR #164); identifier set/clear + cross-encounter lookup + portal chip + inbox search + edit modal. Follow-ups: iOS UI for the identifier, full 'previous encounters' timeline panel on review screen, deterministic-hash column for indexed lookup at scale, identifier format validation
- [x] #60 iOS · Physician style learning, macros & smart phrases — foundation shipped 2026-06-01 (PR #165); macros table + /me/macros CRUD + portal management page + inline expansion in note edit. ML-driven style learning = post-pilot follow-up; iOS macros UI = separate slice
- [x] #59 iOS · After-visit summary & patient instructions — foundation shipped 2026-06-01 (PR #166); patient_summaries table + LLM gen + portal card with Copy/Print/Edit/Regenerate. Follow-ups: iOS UI, FR language, patient-portal delivery
- [x] #58 iOS · Orders, referrals & prescription drafting — foundation shipped 2026-06-01 (PR #167); note_orders table + LLM extraction service + 5 /me endpoints + portal OrdersCard with confirm/cancel. Follow-ups: outbound delivery (→ #57), per-kind edit modal, RxNorm/SNOMED coding, order-set templates, iOS slice
- [x] #69 Coding & billing assist (E/M, ICD-10/CPT) — foundation shipped 2026-06-01 (PR #168); coding_suggestions table + LLM extraction with conservative descriptive-anchor prompt + 5 /me endpoints + portal CodingSuggestionsCard (assistive-banner + per-row confidence + edit/confirm/reject). Strategic separate-surface — never writes into clinical note. Follow-ups: RxNorm/ICD-10 official catalog lookup, E/M MDM complexity scoring, CPT modifier support, iOS UI
- [x] #57 iOS · EMR/EHR write-back (FHIR DocumentReference / HL7) — foundation shipped 2026-06-01 (PR pending); emr_write_backs table + EmrConnector abstraction + FHIR DocumentReference serializer + stub connector + 3 /me/emr endpoints + portal EmrWriteBackCard with "Pilot mode" banner. Real connectors (Oscar / Epic SMART / generic FHIR / HL7v2-MLLP) are follow-ups; the foundation gives them the registry to plug into. Follow-ups: real connector backends, retry scheduler, per-clinic AppConfig connector selection, iOS UI

### Cohort 4 — iOS-backed
- [x] #64 iOS · Live note preview during recording — foundation shipped 2026-06-01 (PR pending); live_note_previews table + draft-stage LLM call separate code path from Stage 1 + /me/sessions/{id}/preview endpoints + portal LivePreviewCard with DRAFT badge + amber border + polling every 4s. iOS generation cadence + WebSocket streaming = follow-ups
- [ ] #62 iOS · Procedural / Post-Op capture mode — 15d — lane: backend — no blockers (BUT: CLAUDE.md "What NOT to Build" lists Post-Op/Procedural Mode; reconcile before picking up)

### Other
- [ ] AUR-MP-CROSSCHECK Add MediaPipe as independent second face detector for Apple Vision (pilot follow-up; revisit only if clinical safety committee asks) — 5d — lane: ios — no blockers

## In flight

- [ ] loop-0 · Fix local DB SSL allowlist — lane: backend — branch `lane-backend/loop-0-db-ssl-local` — started 2026-07-15. Unblocks the §9d gate for Cohort 6.

## Blocked

(driver moves items here after 3 failed fix attempts; appends reason)

## Done

- [x] loop-1 Cohort 6 · regenerate-note correctness (confirm-or-409 loss gate + session-pin template default + built-in key validation + NOTE_REGENERATED audit) — merged 2026-07-15 (PR #657, 4 commits). Closed a conflict-laundering hole: regenerate dropped unresolved `conflict_*` claims, so a note `approve_note` refuses to sign became signable. Independent review (2 agents) caught a HIGH — unvalidated `body.template_key` → silent `general` fallback + unvalidated client text into the append-only audit log. `/simplify` §9f caught the `append-recording` twin hole → loop-1b. Plan: `docs/plans/loop-1.md`; receipt: `.claude/state/verify-receipt-loop-1.json` (AC-12 recorded UNVERIFIED — the loop-0 boot blocker).
- [x] LLM Tier 2 F semantic trigger classifier — merged 2026-05-30 (PR #139, commit d334b03); embeddings fallback for paraphrases, opt-in via AURION_SEMANTIC_TRIGGER_ENABLED
- [x] LLM Tier 2 E few-shot examples per specialty — merged 2026-05-30 (PR #138, commit 2af474f); 3 example files (ortho/peds/plastic), loader + render
- [x] LLM Tier 2 G specialty-aware style snippets — merged 2026-05-30 (PR #137, commit 009aa5e); 8 specialties covered
- [x] LLM Tier 1 D self-critique pass — merged 2026-05-30 (PR #136, commit be16ac9); drops unanchored claims + flips bad section statuses
- [x] LLM Tier 1 C real Stage 2 conflict reconciliation — merged 2026-05-30 (PR #135, commit 132ace3); Anthropic Sonnet compares note vs captions
- [x] LLM Tier 1 B structured output on Anthropic + Gemini — merged 2026-05-30 (PR #134, commit 1434150); tool_use + responseSchema
- [x] LLM Tier 1 A AppConfig-driven temperature/max_tokens — merged 2026-05-30 (PR #133, commit 3719704)
- [x] iOS-CI auto-distribute (Uzziel build-4 saga) — merged 2026-05-30 (PRs #123–#132, final run #135); 9 hotfixes deep
- [x] iOS share button → PDF/Word picker — merged 2026-05-30 (PR #122, commit ce72152)
- [x] #43 F1 User Management Backend (+ #44 frontend + web JWT-login switch) — merged 2026-05-30 (PR #109, commit 0b5071b); follow-up #110 for Cognito-side AdminDisableUser hardening
- [x] WEB-COGNITO-UI web portal Cognito hosted UI shipped 2026-05-28 (PR #28-30) — superseded 2026-05-29 by JWT-login switch in #43's PR; lib/cognito.ts retained for restoration
- [x] WEB-METRICS-CHARTS pilot metrics time-series (GET /admin/metrics/timeseries + 8-panel dashboard sparklines) — 3d — lane: backend — merged: 2026-05-26 (PR #17, commit 4a77f66)
- [x] EVAL-3 eval session assignment (admin assigns; list filtered for EVAL_TEAM; score completes assignment) — 1d — lane: backend — merged: 2026-05-26 (PR #16, commit 38212df)
- [x] EVAL-2 eval scoring per spec (descriptive_mode_pass + soap_section_scores + hallucination_count + discrepancies) — 1d — lane: backend — merged: 2026-05-26 (PR #15, commit ac45f7b)
- [x] EVAL-1 eval triad view read-only side-by-side (GET /admin/eval/sessions/{id} + /eval/[id] page) — 1d — lane: backend — merged: 2026-05-26 (PR #14, commit 6f78af3)
- [x] WEB-EXPORT-COMPLIANCE Info.plist ITSAppUsesNonExemptEncryption = false — 0.1d — lane: ios — merged: 2026-05-25 (PR #13)
- [x] WEB-CI-KEYCHAIN Distribution cert in CI temp keychain — 0.3d — lane: backend — merged: 2026-05-25 (PR #12)
- [x] WEB-FASTLANE Fastlane lanes end-to-end (cert + sigh + invite) — 0.5d — lane: backend — merged: 2026-05-25 (PR #11)
- [x] UI-P4b Live Activity (Lock Screen + Dynamic Island) — AurionWidgets target added via xcodeproj gem — 1d — lane: ios — merged: 2026-05-19 (commit ba4900c)
- [x] AUR-DESIGN-DARK Muted-slate dark mode rollout (palette retune + adaptive tokens + bulk navy-text → adaptive swap) — 5d — lane: ios — merged: 2026-05-19 (commit 0cf99c8)
- [x] AUR-DESIGN-NAVY Collapse aurionNavyLegacy → aurionNavy (brand-sampled #0C1B37 wins) — 0.5d — lane: ios — merged: 2026-05-19 (commit d6a88d3)
- [x] Q-06 _DevUser → frozen @dataclass — 0.5d — lane: backend — merged: 2026-05-19 (commit 5c5f1e9)
- [x] Q-05 Consolidate _to_uuid to core/uuids.py — 0.5d — lane: backend — merged: 2026-05-19 (commit bdb22c3)
- [x] UI-P6 Materials + iPad readable-measure pass (regularMaterial toast + 720pt clamp on Inbox/Note/Devices) — 0.5d — lane: ios — merged: 2026-05-19 (commit 9cefee6)
- [x] UI-P5 A11y labels + symbol effects + motion polish (capture controls, sort, toolbar, conflicts pulse, copy bounce) — 0.5d — lane: ios — merged: 2026-05-19 (commit 4d00062)
- [x] UI-P4a App Intents (StartSessionIntent, ShowPendingNotesIntent) + Spotlight donation + deep-link push — 1d — lane: ios — merged: 2026-05-19 (commit df32abb)
- [x] UI-P3 List + screen UX redesigns (inbox search + iPad clamp + amber conflicts banner with scroll-to-first) — 2d — lane: ios — merged: 2026-05-19 (commit 40b3dcf)
- [x] UI-P2 Native TabView + iPad sidebarAdaptable (NavigationStack-based routing) — 1d — lane: ios — merged: 2026-05-19 (commit 312d3fe)
- [x] UI-P1 Color token sweep + semantic typography modifiers + on-navy text tokens — 1d — lane: ios — merged: 2026-05-19 (commit 3a0152a)
- [x] Q-04 SessionUIState shim cleanup — 1d — lane: ios — merged: 2026-05-19 (commit 69b317e)
- [x] Q-03 write_audit kwarg whitelist + strict-mode — 1d — lane: backend — merged: 2026-05-19 (commit d539a57)
- [x] Q-02 privacy.py _purge_session_prefix extraction + latent bug fix — 1d — lane: backend — merged: 2026-05-19 (commit ec3a318)
- [x] Q-01 AuditEventType StrEnum — 2d — lane: backend — merged: 2026-05-19 (commit 5c26052)
- [x] M-04-MP MediaPipe face-detection cross-check verification — 1d — lane: ios — merged: 2026-05-19 (commit ca938d0)
- [x] P0-07 E2E smoke test — 3d — lane: backend — merged: 2026-05-19 (commit 3835704)
- [x] M-07-DASH Dashboard Stage 2 tile — 3d — lane: ios — merged: 2026-05-18 (commit 7f024fa)
- [x] B-08 Eval persistence — 3d — lane: backend — merged: 2026-05-18 (commit pending)
- [x] P0-06 Persistent users + admin refactor — 8d — lane: backend — merged: 2026-05-18 (commit e7a5a90)
- [x] P0-04 Alembic migrations — 8d — lane: backend — merged: 2026-05-17 (commit e330675)
- [x] CQR-1 Backend route helpers DRY (Phase 1) — lane: backend — merged: 2026-05-17 (commit e330675)
- [x] CQR-2 utcnow + NoteVersion repository (Phase 2) — lane: backend — merged: 2026-05-17 (commit e330675)
- [x] CQR-3 iOS multipart dedup + Theme legacy navy (Phase 3) — lane: ios — merged: 2026-05-18 (commit f3c147d)
- [x] CQR-4 admin.py package split + SessionUIState enum (Phase 4) — lane: both — merged: 2026-05-18 (commit 9edfef8)

---

## Notes

### Dependency rules
- A task with `depends on X` cannot be picked by `/next-task` until X is in Done.
- `/next-task` skips dependency-blocked items and picks the next unblocked one.
- If no unblocked Active items exist for a lane, the loop pauses and posts
  to `alerts.md` rather than failing.

### Lane assignment
- `lane: backend` — touches `backend/**`, `infrastructure/**`, or migrations.
- `lane: ios` — touches `ios/**` or `demo/**`.
- Vertical slices (both at once) get tagged with the larger lane and stay
  sequential. The remaining backlog items are deliberately split so no
  vertical slice is needed.

### Effort estimates
Mirror the complexity scale in §10 of `AURION-CODING-WORKFLOW.md`:
S=1d, M=3d, L=8d, XL=15d. These are conservative for a single developer
or a single autonomous lane. Override only with prior-spike data.

### Acceptance criteria
Acceptance criteria are NOT pre-written here — `/plan-task` writes them
on the feature branch as the first commit. This file is the menu, not
the recipe.
