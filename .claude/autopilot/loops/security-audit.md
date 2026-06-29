# Loop: security / compliance audit

## Loop spec
- **GOAL** — OWASP + secrets + this project's domain compliance (PHI, audit
  append-only, masking fail-closed, descriptive/grounding, Law 25 / consent);
  file issues. NEVER auto-fix.
- **VERIFY** — refute panel (`workflows/security-audit.js`, `models.verifier`):
  each candidate must be confirmed as a real, reachable exposure (not a
  theoretical lint) by ≥2 verifiers citing the exact file/flow. Defaults to "not
  a real exposure."
- **STOP WHEN** — confirmed findings filed (≤ caps), or no new confirmed issues.
- **ON STOP** — severity-ranked issue list; `log-run`.

## Need a loop? (verdict: YES (file-only) → autonomy `propose-only`)
repeats ✓ (weekly) · auto-reject ✓ (reachability/secret scan are checkable) ·
end-to-end ✗ (fixing security needs human) · objective ✓ for *detection*. So it
**files, never fixes** — security fixes are always human.

## Specifics
- **Scan classes**: hardcoded secrets / keys (grep + entropy) in code, logs, S3
  keys, AppConfig docs; PHI in logs/errors/API responses; audit-log update/delete
  paths (must be append-only); masking fallback-to-raw (P0-01) regressions;
  un-gated AI prompt that interprets/diagnoses (descriptive/grounding breach);
  authz gaps on `/admin/*` + `/me/*`; OWASP (injection, SSRF, broken access,
  secrets in transit), CORS, JWT handling.
- finders on `models.finder` per class; **verifier panel confirms reachability**
  (a secret in a test fixture or a false grep is rejected).
- **gate**: every finding is in protected/sensitive territory by nature ⇒ every
  issue is `needs-human`. NEVER opens a fixing PR.
- **act** (`propose-only`): one issue per confirmed finding
  (`autopilot`,`autopilot:security`,`needs-human`), severity + exact location +
  remediation sketch. No code changes.
- **record**: fingerprint = `sec:<rule>:<file>`; accepted = a human ships a fix,
  rejected = triaged false-positive/accepted-risk.
