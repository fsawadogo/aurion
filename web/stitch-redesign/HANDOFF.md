# Generating the Aurion portal in Stitch — UI handoff

The Stitch **API** rate-limited under load, so generate in the **Stitch UI** instead (reliable,
immediate, you see each result live). The hard parts are already done for you:

- **Project:** *Aurion Portal Redesign* — `projects/7593312117351625734`
- **Design system:** already created + applied to the project (asset `a072e11c7ae14f3986fcd55254498921`).
  It faithfully encodes the Aurion tokens (navy `#0C1B37`, gold `#C9A84C`, semantic colors, Inter
  scale, 16px cards + soft shadow, 280px navy sidebar w/ gold active indicator, pill badges, mono ID
  chips, "logo is a squircle — never substitute it"). New screens inherit it automatically.
- **Prompts:** one per page in this folder (`01-…`–`46-…`).

## Steps (per screen)
1. Open Stitch → open the **Aurion Portal Redesign** project. Confirm the theme/design system is the
   Aurion one (it's the project default).
2. New screen → paste the **entire contents** of the prompt file.
3. Set **Device = Desktop**, **Model = Gemini 3.1 Pro**.
4. Generate. Then **drop in the real logo** — Stitch may render a placeholder mark; replace it with
   `web/public/brand/aurion-icon.png` (mark) / `aurion-logo-full.png` (lockup). Never let it ship a
   fake/redesigned logo.
5. Tick it off below.

> Tip: generate a few, eyeball fidelity (palette, sidebar, logo handling), and adjust the prompt
> wording before doing the long tail. The `DESIGN.md` screen in the project is just the uploaded
> spec render — ignore or delete it.

## Checklist (34 pages)
**First, verify in the UI which already exist** — the API run *reported* 4 generated but only the
`DESIGN.md` screen confirmed via `list_screens`; regenerate any that aren't actually there.

**Auth & entry**
- [~] 01 login — *API-generated; verify it persisted*
- [~] 02 forgot-password — *reported generated; verify*
- [~] 03 reset-password — *reported generated; verify*
- [ ] 04 app-entry splash (`/`) — branded redirect/loading screen
- [ ] 05 portal-entry splash (`/portal`) — branded redirect/loading screen

**Clinician portal**
- [ ] 10 dashboard · [ ] 11 notes list · [ ] 12 note review (2-pane) · [ ] 13 templates list ·
- [ ] 14 new template · [ ] 15 template detail · [ ] 16 macros · [ ] 17 profile · [ ] 18 account ·
- [ ] 19 my activity · [ ] 20 AI prompts · [ ] 21 patient detail

**Admin / Eval / Compliance**
- [ ] 30 admin dashboard · [ ] 31 sessions list · [ ] 32 session detail · [ ] 33 audit log ·
- [ ] 34 session timeline · [ ] 35 PHI masking · [ ] 36 eval list · [ ] 37 eval triad ·
- [ ] 38 user management · [ ] 39 config (read-only) · [ ] 40 feature flags · [ ] 41 AI providers ·
- [ ] 42 analytics · [ ] 43 system templates · [~] 44 alerts (*reported generated; verify*) ·
- [ ] 45 compliance reports · [ ] 46 captured media

## If you want to share the design system with other Stitch projects
It lives on this project; duplicate the project or re-upload `DESIGN.md` to a new one
(`create_design_system_from_design_md`) to reuse the exact theme.
