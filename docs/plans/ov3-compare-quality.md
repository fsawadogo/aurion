## Task
OV-3 — /admin/providers/compare-quality: eval scores × provider (#74)

## Why
#74: "A-B provider/version scoring across sessions … citation-accuracy +
hallucination metrics". OV-1 denormalized provider attribution onto
eval_scores; this endpoint aggregates it so the eval team compares
QUALITY per provider next to the existing operational compare.

## Approach
- eval repository: `aggregate_scores_by_provider(db, since, until)` —
  one grouped SELECT over eval_scores (avg transcript_accuracy /
  citation_correctness / descriptive_mode_compliance / overall, avg
  hallucination_count, scored count) grouped by provider_used (NULL
  rows excluded — pre-OV-1 scores without attribution can't be compared).
- route GET /admin/providers/compare-quality (file: admin/providers.py,
  beside /compare): optional since/until; EVAL_TEAM + ADMIN (quality data
  is the eval team's surface; operational compare stays ADMIN+COMPLIANCE).
- Response: {since, until, providers: [{provider_name, scored_sessions,
  avg_overall, avg_transcript_accuracy, avg_citation_correctness,
  avg_descriptive_mode_compliance, avg_hallucination_count}]}.

## Acceptance criteria
- [ ] AC-1: repository aggregation groups by provider, excludes NULL
      attribution, averages correctly — pytest (mocked rows)
- [ ] AC-2: route registered GET /admin/providers/compare-quality with
      the EVAL_TEAM+ADMIN gate — pytest route-registration test
- [ ] AC-3: response model shape pinned (counts + 5 averages) — pytest
- [ ] AC-4: full backend suite green

## DRY / SOLID check
- Reuse: require_role, the providers.py DTO style, eval_repo module
  placement (aggregation joins existing repo).
- New helper: the grouped query — first of its kind, no copy.
- iOS: n/a.

## Out of scope
- The web UI (OV-4 next).
- Per-model breakdown (model_name still NULL until OV-2 data accrues).
- Statistical significance — pilot N is tiny; present counts honestly.

## Test plan (executable)
1. cd backend && python3 -m pytest tests/unit/test_eval_persistence.py tests/unit/test_compare_quality.py -q
2. cd backend && python3 -m pytest tests/unit -q

## Security implications
None: averages of quality scores + provider names; no PHI (eval notes
text is NOT exposed — only numeric aggregates); role-gated to the team
that already sees the underlying scores.
