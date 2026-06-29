export const meta = {
  name: 'autopilot-security-audit',
  description: 'OWASP + secrets + domain compliance scan; adversarially verify reachability; file-only',
  phases: [{ title: 'Find' }, { title: 'Verify' }],
}
const FINDER = { model: 'haiku', effort: 'low' }
const VERIFIER = { model: 'opus', effort: 'high' }
const CLASSES = [
  'hardcoded secret/key in code, logs, S3 keys, or AppConfig docs',
  'PHI in logs / error messages / API responses',
  'audit-log update or delete path (must be append-only)',
  'masking fallback-to-raw bytes (P0-01 fail-closed regression)',
  'un-gated AI prompt that interprets/diagnoses (descriptive/grounding breach)',
  'authz gap on /admin/* or /me/* (broken access control)',
  'OWASP: injection / SSRF / JWT or CORS misconfig',
]
const FIND = { type:'object', additionalProperties:false, required:['findings'], properties:{ findings:{ type:'array', items:{
  type:'object', additionalProperties:false, required:['file','rule','title','severity','detail'],
  properties:{ file:{type:'string'}, rule:{type:'string'}, title:{type:'string'},
    severity:{enum:['low','medium','high','critical']}, detail:{type:'string'} } } } } }
const V = { type:'object', additionalProperties:false, required:['real','reason'], properties:{ real:{type:'boolean'}, reason:{type:'string'} } }

phase('Find')
const found = (await parallel(CLASSES.map((c) => () =>
  agent(`Security/compliance FINDER for the Aurion clinical repo. Scan ONLY for: "${c}". Report concrete, `
    + `reachable exposures with exact file + flow. Skip test fixtures + theoretical lint. Empty if none.`,
    { ...FINDER, label: `sec:${c.slice(0,16)}`, phase: 'Find', schema: FIND })
))).filter(Boolean).flatMap((r) => r.findings)

phase('Verify')
async function confirm(f) {
  const votes = await parallel(Array.from({ length: 3 }, (_, i) => () =>
    agent(`Adversarially REFUTE this security finding. Default real=false; set real=true ONLY if the `
      + `exposure is concretely reachable (cite the path). Reject test fixtures + false greps. `
      + `Finding: ${JSON.stringify(f)}`, { ...VERIFIER, label: `v:${f.rule}#${i}`, phase: 'Verify', schema: V })))
  return votes.filter(Boolean).filter((v) => v.real).length >= 2 ? f : null
}
const confirmed = (await parallel(found.map((f) => () => confirm(f)))).filter(Boolean)
// File-only: every confirmed item is needs-human by nature (the skill files issues).
return { found: found.length, confirmed }
