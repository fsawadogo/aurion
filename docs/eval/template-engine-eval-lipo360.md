# Template engine eval — Lipo 360 synthetic consult (ENGINE-ON run)

**Date:** 2026-07-29 · **Env:** dev (`api-dev.aurionclinical.com`) · **Operator:** Uzziel + Claude (browser-driven, UI-only)
**Session/note:** `60eabcc3-834d-48a4-a7e5-cfd28b6baaaa` · v1 (stage 1) Signed · v2 (stage 2) in Eval view · provider `anthropic`, vision `gemini`
**Input:** `Plastics follow-up.mp4` (synthetic case, 164.6 MB) via Upload Video, account Dr. Faïçal Sawadogo (CLINICIAN)

> **Arm label — corrected twice, final:** this doc first shipped as "OFF-arm". Post-run inspection of the
> read-only AppConfig (admin → Config) showed `template_engine_enabled = ON` **and**
> `grounded_synthesis_enabled = ON`, Uzziel confirmed he found them already ON (did not flip them), and the
> config change history is EMPTY — so the flags were set in an earlier, unaudited config push and **this run
> executed with the engine ON**. The true OFF baseline has NOT been run yet. Caption evidence corroborates:
> "No procedural elements or markings visible" is a template-aimed answer (TE-3 signature), not a blind
> description.

## Method — Marie's flow, no manual template pick

Upload form: visit type **Lipo-consult** + context **Lipo-consult** (`ctx_b30b8799`). The upload UI has **no
template picker**; the mapping is the only path. The form pre-announced the server resolution before upload:
*Template: Plastic surgery — liposuction (comprehensive)* (`plastic_lipo_consult_v2`, custom
`11d1b7da-1d1b-4814-9ca5-e81b5a2ab832`, v2.0, 15 sections) — `resolve_context_template_key` tier ① (context
pin), the iOS-mirrored flow (TE-4d).

## Result — template application (Stage 1): PASS

- **Structure exact:** all **15 sections of the v2 template, in template order**, including the six granular
  history sections that only exist in v2 (specialty default would have produced the 6-section built-in).
- **Per-section guidance followed, not just titles:** Allergies states "reaction type not specified"
  (guidance: never leave allergy status implicit); Risks itemizes every complication (guidance: "do not
  collapse them. Medico-legal."); Post-op has the swelling-timeline percentages; Next steps has pricing,
  coordinator by name, deposit terms, the creatine hold; Assessment claims attributed to the provider.
- v1: 14/15 populated, 93%; sign-off gates worked (approval held for Stage 2, then Signed; post-approval
  rail rendered).

## Result — visual enrichment WITH THE ENGINE ON: 2 thin claims, exam section still empty

This is the headline finding, and it is a caution against celebrating the flip: **with template-aimed capture
live, 133 frames produced 2 merged visual claims, and the Physical exam section — the one that wanted them —
got neither.**

- 131/133 captions died at the confidence/repeats gates (consult-room footage of a narrated exam — most
  visual content is redundant with the transcript by design).
- `frame_132680` → **Chief complaint**: "seated in an examination chair… hands gesturing towards the
  bilateral flank and abdominal area." Aimed phrasing, filed to its anchor's section (engine tier-1) — but
  exam-adjacent content under the visit reason reads as noise.
- `frame_253670` → **Plan / procedure**: "standing in sports bra and pants. Abdomen is blurred. No procedural
  elements or markings visible." The aimed prompt answered honestly — there was nothing procedural to see —
  and the merge kept it anyway: a **no-finding claim in the chart** (adjacent to the class TE-4 removed
  content-deletion for; the right filter here is confidence, which passed it).
- **Physical exam:** no surviving caption anchored/routed to it; the merge cleanup then flipped it
  `pending_video → not_captured` DESPITE its 6 transcript claims — v2 labels a fully narrated exam
  "Not captured" (defect, chipped).

**Interpretation for the flip decision:** on narrated consult footage, the engine's value is bounded by (a)
what the camera actually saw (an exam performed at webcam distance through clothing), (b) the
confidence/repeats gates, and (c) anchor-first routing. The engine did not misbehave — it had almost nothing
usable to aim at. The meaningful comparison is now **procedure/exam-heavy footage** (where frames carry
non-redundant findings), plus the **OFF baseline on this same video** (see next runs). Claim-level verbosity
(tonsillectomy ×3, creatine ×2) is unchanged by the engine — that axis belongs to detail-level.

## Flag-state findings (governance)

1. **`grounded_synthesis_enabled = ON` in dev (= prod) without the #551/GS-9 sign-off** the flag's own card
   demands. The run's note shows no synthesized A&P (the GS runtime slices appear inert on this path), but
   the gate is breached on paper. Recommend: flip OFF until sign-off, or record a CPO sign-off note.
2. **Config change history is empty** despite multiple non-default flags — the values arrived via an
   unaudited config push, or the history surface is broken. Either way the "every change logged" posture
   isn't holding for flags (chipped).
3. Both discovered only because this eval went looking. The eval-receipt gate (TE-3b: "leave OFF until an
   eval receipt shows notes improve") was in practice already bypassed — worth deciding consciously now
   rather than retroactively.

## Additional defects found (all chipped)

- **Section-status integrity:** pending_video with claims (v1) → not_captured with claims (v2) — parse-time
  and merge-cleanup coercion needed; signed notes must not render "Pending visual".
- **Version divergence:** clinician surface renders v1 · Signed while v2 (stage 2) exists — which version
  export/EMR carries needs a pinned contract.
- **Completeness discrepancy:** 93% (clinician ring, v1) vs 67% (Eval header, v2) — different formulas or a
  recompute; unresolved.
- **FRAMES: Unmasked** on the upload path while vision calls ran — masking-proof posture audit (compliance).
- **portal.peritwin.com uploads broken** (rebrand missed the S3 bucket CORS) — fix in PR #701 + terraform
  apply; this run used the legacy origin.

## Next runs

1. **OFF baseline (now the missing arm):** flip `template_engine_enabled` OFF (Admin → Feature flags →
   Template engine — the audited path, so history records it), re-upload the same video, same visit type +
   context. Diff captions/routing/exam section against this run in the Eval compare panel.
2. **Engine-value footage:** rerun ON with footage where frames carry non-redundant findings (a real exam
   sequence, wound/skin close-ups) — the engine's designed win condition.
3. Decide `grounded_synthesis_enabled` posture explicitly (OFF until #551, or signed off).
