## Task
#418 slice 2 — portal accent visual layer (picker + CSS-variable tokens)

## Why
#418 core ask ("my colors"); slice 1 (#422) shipped the validated
accent_color preference. This makes it visible on the portal.

## Approach
- tailwind.config.ts: the `gold` scale becomes
  `rgb(var(--accent-N) / <alpha-value>)` (RGB triplets so /40-style
  opacity modifiers keep working); :root defaults = today's gold hex →
  byte-identical render for everyone (default "gold").
- globals.css: `html[data-accent=X]` blocks for teal/indigo/rose/slate
  (full 50–900 scales from Tailwind's standard palettes — designed
  scales, adequate contrast at the 600/700 text steps in use).
- Apply: the Sidebar profile-sync effect (already applies ui_theme) also
  sets document.documentElement.dataset.accent.
- Picker: "Accent color" swatch row on /portal/profile →
  updateMyProfile({accent_color}) + immediate dataset apply.
- Guardrail: compliance colors (accent.red/amber, audit navy/gray) are
  separate tokens — untouched; CONFLICTS amber & masking indicators
  cannot be themed by this mechanism.

## Acceptance criteria
- [ ] AC-1: picker renders 5 swatches; click → updateMyProfile with the
      palette key + sets data-accent — vitest
- [ ] AC-2: Sidebar profile sync applies stored accent on load — vitest
- [ ] AC-3: default gold → DOM has no data-accent override; render
      byte-identical (no visual change for existing users) — vitest
- [ ] AC-4: full web suite + static build green
- [ ] EN+FR parity

## Out of scope
iOS accent (Theme.swift, TestFlight — bundling with #65 phone-side work);
export branding/signature (separate #418 slices); decorative gradients
that hardcode gold hex (sheen/shadows — residual, noted).

## Test plan (executable)
1. cd web && npx vitest run tests/AccentPicker.spec.tsx
2. cd web && npx vitest run && npm run build

## Security implications
None — UI tokens only; compliance surfaces untouched by construction.
