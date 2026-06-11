## Task
OV-4 — A-B compare UI on /portal/admin/providers (#73 + #74)

## Why
#74: "A-B provider/version scoring … feeds provider-selection decisions";
#73: "ties into the runtime provider switch". The two backend compares
exist (operational /compare since #114, quality /compare-quality from
OV-3); this puts them where the switch lives.

## Approach
- lib/api.ts: compareProviders(a,b,type,window) + compareProviderQuality(window);
  types mirroring the backend DTOs exactly.
- ProviderComparePanel component on /portal/admin/providers below the
  usage panel: provider A/B pickers (per type) + the shared range picker
  pattern → operational side-by-side (calls, success, fallback, latency,
  cost) from /compare + a quality table (per provider: scored count, avg
  overall/accuracy/citation/compliance/hallucinations) from
  /compare-quality. "Directional, not significant" sample-size caption
  (the OV-3 honesty contract). EN+FR parity.
- Quality endpoint is EVAL_TEAM+ADMIN while the page is ADMIN+COMPLIANCE:
  a COMPLIANCE_OFFICER gets 403 on quality → the panel hides the quality
  section on that error rather than failing the page.

## Acceptance criteria
- [ ] AC-1: picking A/B + range calls compareProviders with exact params —
      vitest
- [ ] AC-2: quality table renders rows + the sample-size caption — vitest
- [ ] AC-3: 403 on quality hides that section, operational still renders —
      vitest
- [ ] AC-4: FR catalog parity render — vitest
- [ ] AC-5: full web suite + static build green

## DRY / SOLID check
- Reuse: fetchWithAuth, the range-picker + table styling patterns from
  ProviderUsagePanel, Badge/Card/LoadingSkeleton, useFormatter.
- New helper: none — the panel is a sibling of ProviderUsagePanel.
- iOS: n/a.

## Out of scope
- recharts/trends; per-model rows (model_name data accrues via OV-2).

## Test plan (executable)
1. cd web && npx vitest run tests/ProviderComparePanel.spec.tsx
2. cd web && npx vitest run && npm run build

## Security implications
None: aggregates only; role gates enforced server-side; no PHI.
