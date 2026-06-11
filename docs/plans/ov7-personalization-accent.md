## Task
OV-7 — Physician accent-color preference, backend foundation (#418)

## Why
CTO mid-run request (#418): "customize the app with my colors, make it my
own." The portal already has theme (light/dark) plumbing + a ui_theme
preference; the missing personalization primitive is ACCENT COLOR. This
ships the validated, persisted preference end-to-end (backend) so the
visual-application slice (CSS-variable token wiring + picker, which #418
flags as needing design-token + AA-contrast care) is pure frontend.

## Approach
- model: PhysicianProfileModel.accent_color (String(16), default "gold"),
  mirroring ui_theme exactly. Curated palette (gold/teal/indigo/rose/
  slate) — NOT free-form hex, so the visual slice maps each to a
  pre-validated AA-contrast-safe token (no runtime contrast math, and
  compliance surfaces stay non-themeable per #418 guardrails).
- migration 0038: add column default "gold".
- ProfileResponse.accent_color + UpdateProfileRequest.accent_color with a
  field_validator restricting to the palette (mirrors _validate_ui_theme).
- profile service: persist accent_color like ui_theme.

## Acceptance criteria
- [ ] AC-1: profile update accepts a palette accent_color + rejects an
      off-palette value (422) — pytest
- [ ] AC-2: ProfileResponse surfaces accent_color; default "gold" on a
      profile that predates the column — pytest
- [ ] AC-3: full backend suite green; migration single head 0038

## DRY / SOLID check
- Reuse: the ui_theme field/validator/persist triad is the exact template;
  accent_color is a parallel addition (OCP — new pref, no branching).
- New helper: none.
- iOS: n/a.

## Out of scope (the next, reviewed slice — #418)
- Portal accent picker UI + the CSS-variable token wiring that APPLIES the
  color (design-system change; AA-contrast validation; daytime/reviewed).
- iOS accent (Theme.swift token override + TestFlight build).
- Branding-on-exports, signature block, etc. (#418's companion features).

## Test plan (executable)
1. cd backend && python3 -m pytest tests/unit/test_profile*.py -q
2. cd backend && python3 -m pytest tests/unit -q && python3 -m alembic heads

## Security implications
None: accent_color is a non-PHI UI preference from a fixed vocabulary;
no new read surface; profile updates already audited.
