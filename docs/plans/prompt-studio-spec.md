# Prompt Studio — Feature Spec

**Status:** Draft for review · **Author:** Uzziel Tamon (CPO) · **Eng owner:** TBD (CTO)
**Date:** 2026-06-24 · **Surface:** Web portal only (no iOS) · **Audience for v1:** ADMIN

---

## Problem statement

Today the AI Prompts page is a read-only **transparency** surface: clinicians can see (and personally replace) the system prompts the pipeline uses, but there is no way for an admin to **author, test, and improve the global prompts** that drive note quality. The prompts that matter most live in code (`backend/app/modules/prompts/registry.py`), so tuning them means a code change and a deploy — with no way to see the effect on a real note before shipping. We are running a pilot whose entire value is note quality, and we are flying blind on the one lever that most controls it.

The cost of not solving it: prompt changes are slow, untested, and unmeasured; a regression can reach a clinician's live note before anyone notices; and the eval rubric we already built is disconnected from the act of changing a prompt.

## Goals

1. An admin can take a global prompt from **idea → tested → published** without an engineer or a deploy.
2. Every prompt change is **measured against the current live prompt** on real (masked) cases *before* it ships — no blind publishes.
3. Prompt changes are **versioned and reversible**, with a visible diff of what changed and what it did to the output.
4. A prompt reaches production through a **staged rollout** (self → role → all), so a bad change can never jump straight to a clinician's live note.
5. The whole surface is **flag-gated and role-scoped**, so we can open it from ADMIN to EVAL_TEAM/CLINICIAN over time without a rebuild.

## Non-goals

- **Editing per-clinician personal prompts on their behalf.** The existing CLINICIAN-only override path (`me_prompts.py`) stays as-is; the Studio is about the *global* default, not a clinician's personal replacement. (Separate concern, deliberate transparency boundary.)
- **Creating brand-new AI jobs / pipeline steps.** A Studio prompt always targets an *existing* job (`note_generation`, `vision_frame`, …). New call sites are an engineering task, not a Studio action. (Avoids orphan prompts that do nothing.)
- **Relaxing the descriptive-mode safety boundary.** Studio prompts pass the same `validate_user_prompt` gate. Non-negotiable. (CLAUDE.md.)
- **Mobile.** Authoring/testing is a portal workflow. (No clinician demand on-device.)
- **Auto-tuning / prompt optimization.** Humans author; the system measures. No automated prompt search in v1. (Premature.)

## Personas

- **Prompt author (ADMIN / CPO).** Wants to improve note quality and prove the improvement before it ships.
- **Eval reviewer (EVAL_TEAM).** Later: receives a staged prompt on their own sessions to validate quality. (Flag-gated in.)
- **Clinician (CLINICIAN).** Indirect — receives a published prompt only after it clears staging; their personal override, if set, still wins.

## User stories

**Authoring**
- As an admin, I want to **create a new prompt** for a chosen AI job (e.g. note generation), starting from the current live prompt or blank, so I can iterate without a code change.
- As an admin, I want **live safety feedback** while I write, so I know my prompt preserves descriptive mode before I try to save.
- As an admin, I want **every save to create a new version**, so I never lose a prior prompt and can always roll back.

**Testing**
- As an admin, I want to **pull a full existing session** (masked) and run my draft over its whole transcript, so I can read the *complete* note my prompt produces, not a snippet.
- As an admin, I want to **paste a raw transcript** as an ad-hoc case when I don't have a suitable session.
- As an admin, I want to see my draft's output **side-by-side with the current live prompt's** on the same case, so I can judge whether it's actually better.
- As an admin, I want to **run my draft across a saved panel of cases** and see an aggregate score plus per-case wins/regressions, so one cherry-picked case can't fool me.

**Comparing & shipping**
- As an admin, I want to **diff any two versions** of a prompt (text + what the output did), so I can see exactly what changed.
- As an admin, I want to **publish in stages** (just me → a role → everyone), so a change is validated on a small blast radius before it reaches a clinician.
- As an admin, I want **every publish audit-logged**, so there's a record of who changed what the AI was told and when.

**Edge / empty / error**
- As an admin, when my prompt **fails the safety gate**, I want to see exactly which phrase or missing anchor tripped it, so I can fix it.
- As an admin, when a **test run fails** (provider error/timeout), I want a clear error and the ability to retry, without it counting as a result.
- As an admin testing on a session, I must only ever see the **masked** transcript and a **throwaway** note — the run must never alter the real session or its signed note.

---

## Requirements

### P0 — Must have (the core loop)

**R1 · Flag + role gate.** The Studio is gated by `feature_flags.prompt_studio_enabled` and a role allowlist (`prompt_studio_roles`, default `["ADMIN"]`) in AppConfig.
- Given the flag is off or the caller's role isn't allowlisted, When they hit any Studio route, Then they get 403 and the nav item is hidden.
- Given an admin with the flag on, When they open the Studio, Then they see the prompt library.

**R2 · Create new prompt.** A `+ Create new prompt` action collects: **name**, **target job** (one of the registry `prompt_id`s), **start-from** (current live text or blank).
- New prompts open in the editor as a draft; they do not affect production until published.
- Acceptance: name required; target job required and validated against the registry; "start from current" seeds the editor with the live prompt's text.

**R3 · Author + live safety validation.** The editor runs `validate_user_prompt` feedback as the author types (length, banlist, descriptive-mode anchors), mirroring the existing PATCH error contract (`code`, `matched_phrase`, `missing_anchor_group`).
- Given a prompt missing a descriptive-mode anchor, When the author tries to save, Then save is blocked with the specific missing-anchor hint.

**R4 · Versioning.** Saving creates an **append-only new version** (v1, v2, …). No version is overwritten or deleted.
- Given a saved prompt at v2, When the author edits and saves, Then v3 is created and v2 remains intact and viewable.

**R5 · Test on a case → full note.** The author picks a case source — **pull from session** (select an existing session; the run uses its **masked** transcript) or **paste** — and runs the draft. The result renders the **full note** (all template sections, each claim with its source citation).
- The run calls the provider with the draft text as `system_prompt`; it **does not persist** a note against the real session.
- Given a selected session, When the author runs, Then they see the complete generated note and a rubric summary, and the real session/signed note is unchanged.

**R6 · A/B against current live (single case).** A test run can render the draft's note beside the **current live prompt's** note on the same case, with the rubric metrics under each.
- Acceptance: both notes generated from the identical masked transcript; differences are legible at the section level.

**R7 · Prompt resolution order (the override-collision rule).** At generation time, the prompt for a `(clinician, job)` resolves, highest precedence first:
1. The clinician's **personal override** (`prompt_overrides`) — unchanged behavior.
2. The **active Studio publication** for that job matching the clinician (self → role → all, most specific wins).
3. The **in-code registry default**.
- This preserves the existing personalization/transparency promise (a clinician's own prompt stays sovereign) while letting admins move the default underneath everyone who hasn't overridden.

**R8 · Publish (minimum: self + all).** Publishing makes a specific version the active publication for a scope. v1 must support at least **"just me"** (author's own sessions, for live validation) and **"all clinicians."**
- Every publish writes an audit event (actor, job, version, scope) with **no prompt text**.

**R9 · PHI & safety invariants.**
- Test runs use **masked** transcripts only; pasted text is treated as masked-by-author-assertion and never linked to a patient.
- Dry-run outputs are **ephemeral test artifacts**, excluded from the clinical note store and from session purge logic.
- Studio audit events never contain prompt text or PHI (length + ids only), matching the existing `PROMPT_USER_PROMPT_SET` convention.

### P1 — Should have (completes the agreed design; fast follow)

**R10 · Version history + side-by-side diff.** A history view lists every version (with how far each shipped) and diffs any two: prompt **text diff** plus the **output delta** on a chosen case.

**R11 · Panel testing.** Author runs a draft across a **saved set of masked cases**; sees aggregate metrics (avg SOAP completeness, descriptive-mode pass rate, etc.) and a per-case breakdown that **flags regressions**. A publish can be **soft-blocked** when the panel shows a net regression.

**R12 · Staged rollout + promote.** Full self → **role** → all staging with a "promote to next stage" action and a visible current-stage indicator; each promotion audited.

**R13 · Saved test cases / panels.** Snapshot a masked session (or pasted case) into a reusable, labeled test case; group cases into named panels (e.g. "Ortho regression set").

### P2 — Future considerations (design for, don't build)

- **Auto-computed rubric** beyond what's mechanical (see Open Questions) — LLM-judge for descriptive-mode and hallucination scoring.
- **EVAL_TEAM / CLINICIAN self-service** authoring (the flag/role gate is built to allow this without rework).
- **Stage-2 (vision) prompts** tested with masked frames, not just Stage-1 note generation.
- **Per-specialty publication targeting** (publish a prompt to only ortho clinicians).

---

## Technical notes (for engineering)

Grounded in the current codebase; reuses more than it builds.

**Reuses as-is**
- Provider abstraction: `provider.generate_note(transcript, template, stage, system_prompt)` already takes the system prompt — the dry-run just supplies the candidate text.
- Masked transcripts: the eval surface (`backend/app/api/v1/admin/eval.py`) already fetches masked session transcripts; the picker reuses that access path.
- Safety gate: `app.modules.prompts.safety.validate_user_prompt`.
- Note schema + `completeness_score`: already produced by Stage 1.
- AppConfig feature-flag pattern.

**New data model (proposed — confirm with CTO)**
- `studio_prompts` — the named candidate: `id, job_id (registry prompt_id), name, created_by, created_at, archived_at`.
- `studio_prompt_versions` — append-only: `id, studio_prompt_id, version_no, text, created_by, created_at`.
- `prompt_publications` — append-only rollout history: `id, job_id, version_id, scope (SELF|ROLE|ALL), target_role?, target_user_id?, published_by, published_at, superseded_at`.
- `studio_test_cases` / `studio_test_panels` (+ join) — masked case snapshots and panels (P1).
- Distinct from `prompt_overrides`, which stays the per-clinician *replacement* table (different concept).

**New endpoints (admin-scoped, `/api/v1/admin/prompt-studio/...`)**
- `POST /test` — `{job_id, candidate_text | version_id, source: {session_id | transcript}, compare_to_live}` → `{draft_note, live_note?, rubric, latency_ms}`. Masked-only; no persistence to the clinical store; audited.
- CRUD for prompts/versions; `POST /publish` (`version_id`, `scope`, `target`); list/library; (P1) panels & history/diff.

**Resolution change**
- Extend `assemble_prompt` / `assemble_prompt_for_session` (`app/modules/prompts/assembly.py`) with the R7 step 2 (active publication lookup) between the personal-override check and the registry default.

**Cost/latency**
- Each test = one (or two, for A/B) live provider calls. Add a per-actor rate cap and cache identical `(version_id|text_hash, transcript_hash)` runs to avoid paying twice for the same comparison.

---

## Success metrics

**Leading (days–weeks)**
- **Time to ship a prompt change**: idea → published. Target: **< 30 min** (from days).
- **Tested-before-publish rate**: % of publishes preceded by ≥1 test run. Target: **100%**.
- **Versions tested per published change**: median ≥ 2 (evidence of real iteration).
- **Regressions caught pre-publish**: count of panel-flagged regressions that blocked/changed a publish (the feature paying for itself).

**Lagging (weeks–months)**
- **Note quality delta** on a fixed eval panel after prompt changes: ↑ avg SOAP completeness (toward the ≥90% MVP target), ↓ citation-traceability misses, ↓ human-scored hallucinations.
- **Zero** PHI incidents from test runs; **zero** unaudited publishes; **zero** dry-run notes leaking into the clinical store or purge path.

---

## Open questions

- **[CTO] Override precedence** — confirm R7: a clinician's personal override outranks an admin publication. Tradeoff: overriding clinicians never receive admin improvements. Acceptable for a 3–5 clinician pilot? *(blocking)*
- **[CTO] Versioning storage** — new `studio_*` tables vs extending `prompt_overrides`. Recommendation: new tables. *(blocking)*
- **[Eng/Data] Which rubric metrics auto-compute in v1?** SOAP completeness and citation traceability are mechanical from the note schema. **Descriptive-mode pass and hallucination count are not** — they need a heuristic, an LLM judge, or human eval. Proposal: v1 auto-shows completeness + traceability; descriptive-mode/hallucination deferred to P2 (LLM-judge) or routed to the existing human eval flow. The mockups imply auto hallucination scoring — set expectations here. *(non-blocking, but shapes the test panel)*
- **[Compliance] Display + retention** — confirm ADMIN/EVAL may view masked transcripts and throwaway test notes in the portal, and that dry-run outputs are exempt from retention/purge. *(blocking for launch)*
- **[Eng] Test scope** — Stage 1 (note gen) only for v1, or also Stage 2 (vision, needs masked frames)? Proposal: Stage 1 only. *(non-blocking)*
- **[Design] Nav placement** — does the Studio replace/augment "AI Prompts," or sit beside "Eval" (where transcripts + scoring already live)? *(non-blocking)*
- **[Product] Job coverage** — which jobs are editable in v1? Proposal: `note_generation` first (+ specialty style), others later. *(non-blocking)*

---

## Phasing

- **Phase 1 (P0):** flag/role gate, create→author→version, test on session/paste → full note, single-case A/B, resolution order (R7), publish self+all, audit + PHI invariants. *Ships the core loop.*
- **Phase 2 (P1):** version history + diff, staged rollout + promote, saved test cases.
- **Phase 3 (P1→P2):** panel testing with regression gating, then auto-rubric and wider role access.

P0 alone delivers the goal: tune a global prompt, prove it on a real masked note, ship it safely. P1 completes the design we mocked.
