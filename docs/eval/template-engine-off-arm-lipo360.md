# Template engine eval — OFF arm (Lipo 360 synthetic consult)

**Date:** 2026-07-29 · **Env:** dev (`api-dev.aurionclinical.com`) · **Operator:** Uzziel + Claude (browser-driven, UI-only)
**Flag state:** `template_engine_enabled = OFF` (dark — this run is the baseline arm for the flip decision)
**Session/note:** `60eabcc3-834d-48a4-a7e5-cfd28b6baaaa` · Stage 1 · v1 · provider `anthropic` · **Signed**
**Input:** `Plastics follow-up.mp4` (synthetic case, 164.6 MB) via Upload Video, account Dr. Faïçal Sawadogo (CLINICIAN)

## Method — Marie's flow, no manual template pick

Upload form: visit type **Lipo-consult** + context **Lipo-consult** (`ctx_b30b8799`) + auto-filled context description.
The upload UI has **no template picker**; the mapping is the only path. The form pre-announced the server
resolution before upload: *Template: Plastic surgery — liposuction (comprehensive)* (`plastic_lipo_consult_v2`,
custom `11d1b7da-1d1b-4814-9ca5-e81b5a2ab832`, v2.0, 15 sections) — i.e. `resolve_context_template_key`
tier ① (context pin) fired, exactly the iOS-mirrored flow (TE-4d).

## Result — template application: PASS

- **Structure exact:** the note rendered all **15 sections of the v2 template, in template order** — including the
  six granular history sections (Past medical / Past surgical / Meds & supplements / Allergies / Social / Family)
  that only exist in v2. The specialty default would have produced the 6-section built-in.
- **Completeness:** 14/15 populated, **93%**. The one non-populated section is *Physical exam* — the template's
  visual-trigger section — correctly `pending_video` at Stage 1.
- **Per-section guidance followed, not just titles:**
  - Allergies: "sulfa; **reaction type not specified**" (guidance: never leave allergy status implicit);
  - Risks & benefits: every complication itemized separately (guidance: "do not collapse them. Medico-legal.");
  - Post-op expectations: swelling timeline as percentages (75/85/90/100), garment, follow-up schedule;
  - Next steps: pricing, coordinator by name, deposit terms, creatine pre-op hold;
  - Assessment claims attributed to the provider, per guidance.
- Sign-off gates worked: approval was held for the Stage-2 pass ("Resolve conflicts to approve"), then Signed;
  post-approval rail (Orders / AVS / Coding / EMR stub) rendered.

## Result — visual enrichment (the engine's target): baseline confirmed EMPTY

Stage 2 processed **133 frames → 0 merged visual claims, 0 conflicts**; note stayed v1; *Physical exam* kept its
transcript-derived content and its `pending visual` badge after signing. Expected with the engine dark: captioning
is template-blind, so consult-room footage yields low-confidence/repeat captions that the merge drops. **This is
the OFF-arm datum:** the machinery TE-2/3/4 built (template-aimed captioning + template-routed merge) exists to
make exactly this section gain grounded visual claims.

## Quality observations (for the ON-arm diff)

- Claim-level duplication (the "trop verbeuse" axis): tonsillectomy facts stated 3×, creatine 2× in otherwise
  strong sections. Section-level shaping is solved; claim-level economy is what detail-level + the engine target.
- Grounded/descriptive voice held throughout; patient quotes preserved; no uncited interpretation observed.

## Defect found post-run — "Pending visual" on a signed, content-rich section

*Physical exam* shows 6 transcript claims **and** status `pending_video` — a combination the Stage-1 prompt
explicitly forbids (`note_gen/service.py:420`: populated whenever the transcript narrates findings;
pending_video only with an EMPTY claims array). Nothing validates the pair post-parse, so the model's soft
violation shipped, and it is why the score reads 93% instead of 100% despite a full section. It then never
resolved because the only flip to `populated` lives inside the Stage-2 merge (`vision/service.py:950`) and the
merge never ran — zero captions survived the confidence/repeat gates, so the note was never rewritten (still
v1) and the Stage-1 status survived into the **signed** note, where a permanent "Pending visual" badge is
misleading. Fixes chipped: (a) backend — coerce claims-present + pending_video → populated at parse time;
(b) web — never render "pending" on a signed note; (c) stale comment at `vision/service.py:956` says
processing_failed, code sets not_captured.

## Incidental find (fixed in-flight)

Uploads from **portal.peritwin.com** fail instantly (`part_network_error`): the rebrand extended the API CORS but
missed the S3 `video_imports` bucket CORS (`infrastructure/s3.tf`). Fix: **PR #701** (+ `terraform apply` after
merge). This run was executed from `portal.aurionclinical.com`, which the bucket allows.

## ON arm — what to run next

1. Flip `template_engine_enabled` ON: **portal → Admin → Feature flags → "Template engine" card** (admin account;
   Level-2 audited toggle, TE-3b).
2. Re-upload the same video with the same visit type + context.
3. Compare in the eval Compare-runs panel (EVAL-1): expect template-aimed captions to populate *Physical exam*
   with grounded visual claims (per-zone pinchable adipose, laxity, diastasis per the template's triggers);
   diff verbosity and section completeness against this run.
4. Receipt from that comparison = the flip decision for the pilot (Cohort 7 gate).
