# Aurion Autonomous Loop — Backlog

Canonical task list. The driver loop reads top-to-bottom and works the
topmost Active item matching its lane. Format per line:

    - [ ] {ID} {one-line description} — {effort}d — lane: {backend|ios} — {dependencies}

When a task moves through states, the loop edits this file in place:
Active → In flight → Done (or → Blocked on triple failure).

Last seeded: 2026-05-14. Last updated: 2026-05-30 (seeded 17 backend issues from GitHub per CTO's "implement all backend" directive).

## Active

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
- [ ] #61 iOS · Longitudinal patient context across encounters — 8d — lane: backend — no blockers (unblocks #60, #59)
- [ ] #60 iOS · Physician style learning, macros & smart phrases — 8d — lane: backend — depends on #61
- [ ] #59 iOS · After-visit summary & patient instructions — 5d — lane: backend — depends on #60
- [ ] #58 iOS · Orders, referrals & prescription drafting — 8d — lane: backend — no blockers
- [ ] #69 Coding & billing assist (E/M, ICD-10/CPT) — 8d — lane: backend — depends on #58
- [ ] #57 iOS · EMR/EHR write-back (FHIR DocumentReference / HL7) — 15d — lane: backend — depends on #58, #59, #69

### Cohort 4 — iOS-backed
- [ ] #64 iOS · Live note preview during recording — 5d — lane: backend — no blockers
- [ ] #62 iOS · Procedural / Post-Op capture mode — 15d — lane: backend — no blockers

### Other
- [ ] AUR-MP-CROSSCHECK Add MediaPipe as independent second face detector for Apple Vision (pilot follow-up; revisit only if clinical safety committee asks) — 5d — lane: ios — no blockers

## In flight

(none — autonomous run checkpoint 2026-05-30; see digests/2026-05-30.md)

## Blocked

(driver moves items here after 3 failed fix attempts; appends reason)

## Done

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
