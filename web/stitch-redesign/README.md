# Aurion Web Portal — Google Stitch redesign prompts

One self-contained prompt per portal page, for regenerating each screen in **Google Stitch**
while keeping Aurion's existing brand, theme, and logo **exactly**.

## How to use
1. Read **`00-DESIGN-SYSTEM.md`** first — it's the canonical brand/theme spec. Every page prompt
   embeds a compact version of it, but this file is the source of truth (colors, type, logo,
   components, chrome).
2. Open Google Stitch → paste a single page prompt (one file) per generation.
3. **Logo:** every prompt instructs Stitch to treat the Aurion logo as a *fixed placeholder image* —
   do **not** let Stitch invent, redraw, recolor, or substitute a mark. The real assets are
   `web/public/brand/aurion-icon.png` (squircle mark) and `web/public/brand/aurion-logo-full.png`
   (full lockup). Drop the real PNG into the generated design after.
4. Keep generations **consistent**: same Sidebar shell, header pattern, card system, and palette on
   every screen — they must read as one premium product (and match the iOS app 1:1).

## Non-negotiables (in every prompt)
- Exact theme colors (gold `#C9A84C` default accent, navy `#0C1B37`, semantic amber/green/red/blue).
- Exact logo — never faked or restyled.
- **Compliance/safety surfaces are NOT themeable**: CONFLICTS amber, PHI-masking proof, append-only
  audit, "approximate / not certified", consent, "audited" badges, SHA-256 hashes, retention
  countdowns — keep these in fixed semantic colors, always prominent.
- Premium, professional, calm, clinical-grade. Light mode. Bilingual EN + FR (flexible text widths).

## Pages (one prompt each)
**Auth** — `01` login · `02` forgot-password · `03` reset-password
**Clinician portal** — `10` dashboard · `11` notes list · `12` note review (2-pane) · `13` templates
list · `14` new template · `15` template detail · `16` macros · `17` profile · `18` account ·
`19` my activity · `20` AI prompts · `21` patient detail
**Admin / Eval / Compliance** — `30` admin dashboard (pilot metrics) · `31` sessions list ·
`32` session detail · `33` audit log · `34` session timeline · `35` PHI masking · `36` eval list ·
`37` eval triad · `38` user management · `39` config (read-only) · `40` feature flags ·
`41` AI providers · `42` analytics · `43` system templates · `44` alerts · `45` compliance reports ·
`46` captured media

> Redirect-only routes (`/`, `/portal`) have no UI and are intentionally omitted.
