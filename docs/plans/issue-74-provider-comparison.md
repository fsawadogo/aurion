# Plan for #74 — Provider A-B comparison (foundation)

## Task
**#74** — Side-by-side comparison of two providers over a date window. Foundation slice ships the **operational** comparison (latency, success rate, fallback rate) reading from `provider_usage` shipped in #73. The **quality** comparison (citation accuracy, hallucination count, descriptive-mode pass-rate per provider) joins `provider_usage` to `eval_scores` and is the next slice.

## Why
"anthropic is 200ms slower but its fallback rate is half openai's" — the dashboard from #73 surfaces that per provider, but you have to flip between rows mentally. #74 puts both providers next to each other with pre-computed deltas so the choice is obvious.

## Approach
- Extend `ProviderUsageService` with `compare(provider_type, a, b, since, until) -> ComparisonResult`. Internally calls `aggregate()` twice (once filtered to provider `a`, once to provider `b`), reuses the existing rollup logic — no new SQL.
- New endpoint `GET /api/v1/admin/providers/compare?provider_type=&a=&b=&since=&until=`. ADMIN + COMPLIANCE_OFFICER gated.
- Deltas in the response: `b - a` for latency (positive = b slower); `b - a` for success_rate / fallback_rate (positive = b higher).
- Tests: extend `test_provider_usage.py` with `TestCompare`.

## Acceptance criteria
- [ ] **AC-1**: `pytest tests/unit/test_provider_usage.py::TestCompare` — both rollups returned + deltas computed.
- [ ] **AC-2**: `GET /api/v1/admin/providers/compare?a=openai&b=anthropic&provider_type=note_generation` → 200; both `a_rollup` and `b_rollup` present even when one or both have zero calls.
- [ ] **AC-3**: CLINICIAN → 403.
- [ ] **AC-4**: Backend suite stays green (307 → ~310 passing).

## DRY / SOLID check
- **Reused**: `ProviderUsageService.aggregate`, the admin-router pattern, AsyncMock helpers in `test_provider_usage.py`.
- **New?** `compare()` is a thin convenience wrapper over `aggregate()` — not a duplicate of the per-provider rollup logic; it composes the two rollups it returns. OK.

## Out of scope (follow-ups)
- **Quality comparison**: join `provider_usage.session_id` ⨯ `eval_scores` so each provider's citation_accuracy / hallucination_count / descriptive_mode_pass_rate is rolled up next to its operational stats.
- **Multi-window comparison**: weeks/days side-by-side for one provider.
- **Web Portal "Compare" page** with provider pickers + chart.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_provider_usage.py -v` → all pass
2. `curl -H "Authorization: Bearer <admin>" 'localhost:8080/api/v1/admin/providers/compare?provider_type=note_generation&a=openai&b=anthropic'` → 200 with both rollups
3. `cd backend && python3 -m pytest -q` → 307 → ~310

## Security implications
- No PHI surfaced; same shape as `/providers/usage`.
- Role gating identical to #73's endpoint.
