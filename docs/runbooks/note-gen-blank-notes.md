# Blank / empty notes — diagnosis & fixes

A "blank note" = Stage 1 delivered a structurally valid note with
`completeness = 0.00` and every required section `not_captured`. The session
looks successful (state `AWAITING_REVIEW`, `stage1_delivered` audited) but the
clinician sees nothing. Reported from the web-portal video-import path but the
mechanics apply to every Stage 1 run (iOS live capture included).

## Fast triage (5 minutes)

All signals are in CloudWatch **`/aurion/dev/api`** (creds: the Claude-Code
CloudWatch keys or any admin `aurion-dev` profile). Filter on the session id.

Look for these lines, in order:

| Log line | Meaning |
|---|---|
| `... transcription parsed: session=… segments=N` | How much source material existed. `N` large (100s) + blank note ⇒ generation problem, NOT transcription. `N = 0` never reaches note-gen (422 `empty_transcript`). |
| `note parse backfilled M/M template section(s) … out_of_template_ids=0` | **The model's response contained ZERO sections** — the parser backfilled the whole template. This is the truncation signature (see root cause 1). |
| `note parse backfilled k/M … out_of_template_ids>0` | The model returned sections with WRONG ids (template/prompt mismatch — see root cause 3). |
| `note parse produced 0 populated required sections — empty note` | The blank-note event itself. |
| `Audit event written: … event=stage1_empty_note` | Same, as an audit row (query DynamoDB for the historical rate). |

## Root causes, most → least likely

### 1. Output truncation at `max_tokens` (the 2026-07-05 incident)

Long encounter (e.g. a 400-segment video import) ⇒ the note needs more output
tokens than `model_params.note_generation.max_tokens`. When Anthropic hits the
ceiling mid-tool-call it returns `stop_reason="max_tokens"` with an **empty
tool input `{}`** — historically parsed as a zero-section "success".

**Fixed in #646**: the Anthropic provider now checks `stop_reason`; on
truncation it retries once at an escalated ceiling (`max(4×configured, 16k)`,
capped 32k) and raises `ProviderError` (loud failure) if the retry truncates
too. A silent blank note from this path is no longer possible — if you see one
on a build ≥ #646, it is NOT this cause.

Residual operator actions:
- If imports of very long encounters *fail loudly* with
  `Note generation output truncated at max_tokens=…`, raise
  `model_params.note_generation.max_tokens` in AppConfig (Level 1, <30 s,
  no redeploy). 8000 is the pilot default; anthropic retries internally up to
  32k regardless.
- Gemini has an equivalent failure mode via *reasoning tokens* eating the
  output budget (#438) — its truncation yields invalid JSON → a loud
  `STAGE1_FAILED`, not a blank note. Same knob (`max_tokens`) fixes it.

### 2. Genuinely thin transcript

Very short / silent / non-clinical audio can transcribe into a handful of
segments that legitimately populate nothing. Check `segments=N` and the
`stage1_skipped_low_transcript` guard events. This is expected behaviour —
descriptive mode never fabricates content (CLAUDE.md §The Single Most
Important Constraint).

### 3. Template/prompt mismatch (`out_of_template_ids > 0`)

The model answered with section ids outside the template (typically after a
template or prompt change, or a custom template with unusual section ids).
The parse backfills the real template's sections as `not_captured`. Diff the
custom template's section ids (`/me/custom-templates`) against the ids in the
model output; fix the template or the prompt change that caused the drift.

### 4. Provider outage / degraded model

Cross-check `GET /api/v1/admin/providers/usage` (per-provider success rates)
and consider a runtime provider flip via `/admin/providers` or the portal
Providers page — Level 2 switch, immediate, audited.

## Verifying a fix

Re-run generation on the SAME stored transcript — no re-upload needed:
`POST /api/v1/sessions/{id}/regenerate-note` (owner-scoped; enabled while
`note_options_enabled` is ON, or per-user `prompt_testing_enabled`). Then
confirm in logs: no `backfilled M/M`, `completeness > 0`, and on a build
≥ #646 optionally a `truncated at max_tokens … retrying` warning followed by
success.

## Related

- Fix PR: #646 (`providers/note_gen/anthropic.py` + `tests/unit/test_anthropic_truncation.py`)
- Empty-note observability: `STAGE1_EMPTY_NOTE` audit event (#280)
- Gemini reasoning-token truncation precedent: #438
- AppConfig knobs: `model_params.note_generation.{max_tokens,temperature}` —
  read the LIVE value via `appconfigdata` (not the latest hosted version)
