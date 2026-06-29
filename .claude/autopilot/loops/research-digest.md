# Loop: research / competitor digest

## Loop spec
- **GOAL** — web research relevant to THIS project (ambient clinical
  documentation, AI scribe regulation, grounded-vs-descriptive note generation,
  on-device ASR/vision, competitors); summarize; deliver as a DRAFT.
- **VERIFY** — judge panel (`workflows/research-digest.js`, `models.judge`): each
  item must be (relevant to the project's actual scope? recent/credible source?
  actionable for us?). Unsourced or off-scope items dropped. Defaults to "not
  relevant."
- **STOP WHEN** — one digest's worth of vetted items (≤ caps), or budget hit.
- **ON STOP** — a draft digest delivered (NOT auto-published); `log-run`.

## Need a loop? (verdict: WEAK → autonomy `propose-only`, draft-only)
repeats ✓ · auto-reject ✗ (relevance is judgement) · end-to-end ✗ · objective ✗.
Pure-taste output ⇒ **draft for human review, never an action**.

## Specifics
- finders (`models.finder`) run web search per theme (uses WebSearch/WebFetch).
  **Headless caveat**: if web tools are unavailable in the scheduled context, the
  loop records that and exits cleanly (no fabricated research).
- judge panel keeps only sourced, in-scope, actionable items; each item carries
  its URL + a one-line "why it matters to Aurion."
- **act** (`propose-only`): write the draft to the state dir
  (`state/research/<date>.md`) AND, if `email.channel` available, hand to the
  digest loop for the weekly email. Never opens issues/PRs directly (feeds the
  meta-digest).
- **record**: fingerprint = `research:<url-hash>` (dedup so the same article never
  re-digests); accepted = a human acts/keeps, rejected = ignored.
