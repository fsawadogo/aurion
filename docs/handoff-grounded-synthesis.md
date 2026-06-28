# Handoff — v3.2 Grounded Synthesis: turn it on + test everything

For Uzziel (and anyone picking this up). Everything for **v3.2 Grounded
Synthesis** is merged to `main` and shipping **dark**, plus a few flags and
fixes from this stretch. Epic: **#552**. Enable runbook (detailed):
`docs/runbooks/grounded-synthesis-enable.md`.

> ⚠️ **dev IS the live pilot environment.** Grounded Synthesis must **not** be
> enabled on it until clinical + regulatory sign-off (**#551**). Test with the
> flag toggled in a throwaway/non-pilot context, or just run the automated suite.

---

## 1. What's behind which flag

| Flag (`feature_flags.*`) | Default | What it does |
|---|---|---|
| `grounded_synthesis_enabled` | **OFF** | The v3.2 feature. Flips 5 layers at once: note-gen prompt (GS-1), save-time validator (GS-4), specialty style (GS-3), few-shot examples (GS-2), and the CLAUDE.md policy (GS-5). OFF = byte-identical descriptive. **Gated on #551 sign-off.** |
| `specialty_style_in_prompt_enabled` | ON (dev) | Injects per-specialty style guidance into Stage 1. Already on. |
| `prompt_studio_enabled` (+ `prompt_studio_roles`) | ON, `["ADMIN"]` | Admin Prompt Studio. Already on. |

`grounded_synthesis_enabled` is the only one not yet enabled — on purpose.

Always-on grounding guards (NOT gated; hold in both modes): every claim needs a
source anchor; critique drops unanchored/fabricated claims incl. multi-anchor
`additional_sources` (GS-6/GS-8); vision/reconcile prompts stay literal.

## 2. How to turn it on

**Easiest — portal:** Admin → **Feature Flags** → toggle **Grounded Synthesis**
→ **Save**. The save persists correctly and preserves `model_versions` (the
Gemini override) — that was the #530/#531 fix.

**CLI fallback + full procedure:** `docs/runbooks/grounded-synthesis-enable.md`
— baseline capture, AppConfig flip, verification, and **instant rollback** (flip
OFF; the backend re-reads AppConfig in ~30s, no redeploy).

## 3. How to test

### A. Automated (fastest)
```bash
cd backend && python3 -m pytest tests/unit -q          # ~1572 passing
# the v3.2 suites specifically:
python3 -m pytest tests/unit/test_grounded_synthesis_flag.py \
  tests/unit/test_grounded_synthesis_prompt.py tests/unit/test_grounding_validator.py \
  tests/unit/test_grounded_specialty_style.py tests/unit/test_grounded_examples.py \
  tests/unit/test_multianchor_claim.py tests/unit/test_grounding_guard.py -q
```

### B. The flag flips everything (integration)
- **OFF:** note-gen prompt is describe-only; the save-time validator *rejects* a
  synthesis prompt; specialty style says "never interpret"; no grounded examples.
- **ON:** prompt allows cited synthesis; validator *accepts* a grounded ("cite
  every claim to its source") prompt; specialty style says "synthesize… cite
  each"; the grounded few-shot example appears for ortho/plastic.

### C. End-to-end note (the real test) — flag ON, non-pilot session
Run an ortho or plastic encounter. The Stage-1 **Assessment & Plan** should be
**synthesized** (e.g. "Working assessment: ACL tear") with **every claim citing
its source(s)** — including multi-source claims via `additional_sources`.
Confirm: no uncited/fabricated statements (critique drops those), and the
descriptive sections (HPI / exam / imaging) stay literal.

### D. Related fixes worth re-verifying on TestFlight
- **Bluetooth mic (#542):** record on the **built-in iPhone** source **with
  Bluetooth connected** (AirPods/glasses) → audio is captured + the note
  generates. (Previously: silent recording → "no speech detected.")
- **Feature Flags save (#530/#531):** flip any flag in the portal → saves
  without 502, and `model_versions.gemini` is still intact afterward.
- **DB SSL (#532):** no `pg_hba` flakiness; `/auth/me`, `/me/prompts/*` stay 200.

## 4. Before enabling on the pilot
GS-9 (**#551**) sign-off: clinical-lead review of synthesized-A&P quality,
regulatory/QMS review, pilot-physician acceptance, decision record. Runbook
Step 0 has the checklist. Until then it stays OFF.
