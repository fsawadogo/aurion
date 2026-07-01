# Plan — scribe-2 (#622): grounded-voice hardening

## Task
Make the grounded voice reliably produce a cited Assessment & Plan, and stop
descriptive/thinning overrides from steering it back.

## Why
Even with scribe-1's always-on grounded boundary, the grounded prompt only
PERMITTED an A&P ("you MAY synthesize"), so a grounded encounter could still
yield a describe-only note; and the grounded banlist didn't reject
descriptive/thinning override text. #622. Context: `memory/grounded-scribe-gap-map.md`.

## Approach
- `providers/note_gen/shared.py`: Rule 2 of `NOTE_GEN_GROUNDED_SYSTEM_PROMPT`
  MAY → MUST-when-cited-support, with an explicit anti-over-reach clause for thin
  encounters (grounding floor unchanged).
- `prompts/safety.py`: extend `GROUNDED_BANNED_PHRASES` with multi-word
  descriptive/thinning directives ("do not synthesize", "do not diagnose",
  "descriptive mode only", "summarize to a handful", …) — each verified NOT to
  false-match a legitimate grounded prompt or the grounded specialty style.
- Goal (1) — grounded specialty-style/few-shot selection — is ALREADY wired
  (`get_specialty_style`/`get_few_shot_examples` return grounded variants when
  the flag is ON, and they're grounded-appropriate). No code change; added a
  guard test.

## Acceptance criteria
- [ ] AC-1: the grounded prompt mandates ("must synthesize"), no longer "may synthesize the assessment", floor tokens intact + anti-over-reach clause.
- [ ] AC-2: flag ON → a suppressive override ("… do not synthesize", "descriptive mode only", "summarize to a handful", …) is BANNED at save.
- [ ] AC-3: a legitimate grounded override still passes; injection still banned.
- [ ] AC-4: flag OFF byte-identical (descriptive validator + descriptive prompt unchanged; new phrases are grounded-only).
- [ ] AC-5: grounded mode selects the grounded specialty style (guard); OFF stays descriptive.

## DRY / SOLID check
- No new mechanism: extends the existing `GROUNDED_BANNED_PHRASES` tuple and edits the existing grounded prompt constant; reuses `_active_safety_sets` gating. No new branch.

## Out of scope
- Completeness/truncation + source_id integrity → #624 (scribe-4). Render → #625.

## Test plan (executable)
1. `cd backend && python -m pytest tests/unit/test_scribe2_grounded_voice.py -q`
2. Regression: `python -m pytest tests/unit/test_grounding_validator.py tests/unit/test_grounded_synthesis_prompt.py tests/unit/test_grounded_specialty_style.py tests/unit/test_specialty_guidance.py tests/unit/test_prompt_assembly_safety.py -q`

## Review outcome (#629) — banlist dropped
The adversarial review of #629 showed the descriptive/thinning **banlist is the wrong tool**: as case-insensitive substrings it false-matches legitimate grounded prompts (grounding caveats say "do not synthesize beyond the sources", "documentation only where evidence exists", "cite a few claims per finding", …), and it also leaks into `validate_specialty_guidance`. The real guarantee is scribe-1's always-on grounded boundary (`compose_system_prompt`), which an override cannot strip and which the banlist could neither improve nor robustly enforce (trivially evadable). **Decision: drop the banlist additions entirely** and keep scribe-2 as the mandate only. The mandate wording was also strengthened (synthesis is the default; declining is a narrow exception, not a co-equal branch — review finding #9). Net PR = the grounded prompt Rule 2 edit + tests; `safety.py` is unchanged.

## Security implications
- Sanctioned Grounded Synthesis Mode path, flag-gated (default OFF → byte-identical; GS-9 gates flip-on). Mandating synthesis stays within the grounding floor (every clause cited; anti-over-reach on thin encounters). Banlist additions only tighten what a grounded override may contain. No PHI; no consent/masking/audit path touched.
