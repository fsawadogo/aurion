# Runbook — Enabling Grounded Synthesis Mode (v3.2)

Operationalizes **GS-9 (#551)**: how to take Aurion from descriptive-only to
grounded A&P synthesis **after** clinical + regulatory sign-off. All v3.2 code
(GS-1…GS-8, Epic #552) is merged and shipping **dark** behind one flag —
`feature_flags.grounded_synthesis_enabled` (default **false**). Nothing in this
runbook changes pilot behaviour until step 3 flips that flag.

> Live env note: **dev IS the pilot/production environment** (see
> `memory/reference_dev_is_live_prod`). AppConfig app `a8wykyf`, env `dyjjd5e`,
> profile `3f4zwpr`, region `ca-central-1`.

---

## What the flag flips (verified integration smoke)
With the flag ON, all five layers switch together; OFF they are byte-identical to
pre-v3.2:

| Layer | OFF | ON |
|---|---|---|
| Note-gen system prompt (GS-1) | describe-only | grounded A&P synthesis (cited) |
| Save-time prompt validator (GS-4) | requires "do not interpret" | requires grounding (cite/traceable) |
| Specialty style (GS-3) | anti-synthesis | grounding-required (5 MVP specialties) |
| Few-shot examples (GS-2) | descriptive only | + grounded example (ortho, plastic) |
| `CLAUDE.md` policy (GS-5) | — | documents both modes |

Always-on guards (NOT gated — grounding holds in both modes): every claim needs a
source anchor; critique drops unanchored/fabricated claims incl. multi-anchor
`additional_sources` (GS-8); vision/reconcile prompts stay literal.

---

## Step 0 — Pre-conditions (GS-9 sign-off gate) — DO NOT skip
Record each in the #551 decision log before enabling:
- [ ] **Clinical lead** review of synthesized-A&P quality + safety on ≥N pilot
      transcripts (grounding rate, hallucination rate, `pilot_metrics.physician_edit_rate`
      vs the descriptive baseline).
- [ ] **Regulatory/QMS** review of the mode change + intended-use statement +
      export labelling (descriptive scribe → grounded synthesis changes the risk posture).
- [ ] **Pilot physician** (Marie / Perry) acceptance.
- [ ] **Decision record**: who signed off + when, linked on #551.

## Step 1 — Capture a baseline (so rollback + audit are clean)
```bash
export AWS_DEFAULT_REGION=ca-central-1
SID=$(aws appconfigdata start-configuration-session --application-identifier a8wykyf \
  --environment-identifier dyjjd5e --configuration-profile-identifier 3f4zwpr \
  --query InitialConfigurationToken --output text)
aws appconfigdata get-latest-configuration --configuration-token "$SID" /tmp/pre_enable.json
python3 -c "import json;d=json.load(open('/tmp/pre_enable.json'));print('model_versions.gemini=',d.get('model_versions',{}).get('gemini'));print('grounded=',d['feature_flags'].get('grounded_synthesis_enabled'))"
```
Confirm `grounded=False` and note `model_versions.gemini` (must survive the flip).

## Step 2 — Flip the flag (preferred: portal; it preserves all sections)
- **Portal**: Admin → Feature Flags → toggle **Grounded Synthesis** → Save. The
  backend re-publishes the full config (#530/#531 fixes) preserving `model_versions`
  + `alerting`, then deploys. (Surfaced in `FeatureFlagsResponse` by GS-7.)
- **CLI fallback** (preserves every section explicitly):
  ```bash
  python3 -c "import json;d=json.load(open('/tmp/pre_enable.json'));d['feature_flags']['grounded_synthesis_enabled']=True;json.dump(d,open('/tmp/enable.json','w'),separators=(',',':'))"
  VER=$(aws appconfig create-hosted-configuration-version --application-id a8wykyf \
    --configuration-profile-id 3f4zwpr --content-type application/json \
    --content fileb:///tmp/enable.json --query VersionNumber --output text)
  aws appconfig start-deployment --application-id a8wykyf --environment-id dyjjd5e \
    --deployment-strategy-id go3hmzn --configuration-profile-id 3f4zwpr --configuration-version "$VER"
  ```

## Step 3 — Verify
```bash
# live config: flag ON, model_versions intact, all 6 sections present
SID=$(aws appconfigdata start-configuration-session --application-identifier a8wykyf --environment-identifier dyjjd5e --configuration-profile-identifier 3f4zwpr --query InitialConfigurationToken --output text)
aws appconfigdata get-latest-configuration --configuration-token "$SID" /tmp/post_enable.json
python3 -c "import json;d=json.load(open('/tmp/post_enable.json'));ff=d['feature_flags'];print('grounded=',ff['grounded_synthesis_enabled'],'gemini=',d.get('model_versions',{}).get('gemini'),'sections=',sorted(d.keys()))"
```
Then run one non-pilot encounter and confirm the Stage-1 note shows a **cited**
A&P (each assessment claim carries `source_id` / `additional_sources`). Watch
`pilot_metrics.physician_edit_rate` + citation-traceability for the first sessions.

## Step 4 — Rollback (instant, reversible)
Flip the flag **OFF** (portal toggle or re-deploy the `/tmp/pre_enable.json`
baseline). Behaviour returns to byte-identical descriptive immediately — no redeploy.
The backend polls AppConfig every ~30s.

---
Closes the operational half of #551 — enabling remains a deliberate, signed-off,
single-flag action with a one-step rollback.
