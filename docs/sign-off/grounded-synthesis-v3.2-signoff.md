# Sign-off record — Grounded Synthesis Mode (v3.2)

**Decision gate for #551 (GS-9). The `grounded_synthesis_enabled` flag must NOT
be turned on for the pilot until every box below is checked and this record is
completed + linked on #551.** Until then the pilot runs descriptive-only
(flag OFF, byte-identical to pre-v3.2).

- Epic: #552 · Enable runbook: `docs/runbooks/grounded-synthesis-enable.md`
- Eval harness: `backend/scripts/grounded_synthesis_eval.py` (descriptive-vs-grounded comparison)
- Code status at time of review: all slices merged dark (GS-1…GS-8). Commit: `__________`

---

## 1. Evidence reviewed
- [ ] **Descriptive-vs-grounded comparison report** attached (output of the eval
      harness over ≥ ___ consented/non-PHI eval encounters). Link/attachment: `__________`
  - Grounded **grounding_rate**: ______ (target ~1.0) · **ungrounded_claims/note**: ______ (target 0)
  - Section completeness OFF→ON: ______ → ______ · A&P populated OFF→ON: ______ → ______
- [ ] **Spot-read** of ___ grounded A&P sections: every conclusion supported by
      its cited source(s); no fabrication / over-reach. Notes: `__________`
- [ ] **Post-enable metric plan** agreed: monitor `pilot_metrics.physician_edit_rate`
      + citation_traceability_rate for the first ___ sessions; rollback trigger: `__________`

## 2. Clinical sign-off
- [ ] Clinical lead has reviewed grounded-A&P **quality + safety** and accepts it
      for pilot use.
  - Name / role: `__________`  · Date: `__________`  · Signature/approval ref: `__________`

## 3. Regulatory / QMS sign-off
- [ ] Mode change (descriptive scribe → grounded, cited synthesis) reviewed against
      intended-use statement + risk classification; **export labelling** updated.
  - Name / role: `__________`  · Date: `__________`  · QMS record ref: `__________`

## 4. Pilot physician acceptance
- [ ] Pilot physician(s) (Marie / Perry) have seen sample grounded notes and accept.
  - Name(s): `__________`  · Date: `__________`

## 5. Decision
- [ ] **APPROVED to enable** — proceed to the enable runbook (flip
      `grounded_synthesis_enabled` ON, verify, monitor).
- [ ] **NOT approved** — reasons + required changes: `__________`

Decision by: `__________`  · Date: `__________`

---

## 6. Enablement log (filled when flipped)
| Field | Value |
|---|---|
| Enabled on (UTC) | `__________` |
| AppConfig hosted version | `__________` |
| `model_versions.gemini` confirmed intact | ☐ |
| Verified grounded note shows cited A&P | ☐ |
| Rollback owner / contact | `__________` |

> Rollback: flip the flag OFF (portal toggle or redeploy the pre-enable baseline).
> Returns to descriptive immediately (~30s), no redeploy. See the runbook §4.
