export const meta = {
  name: 'autopilot-core-quality',
  description: 'Exercise the core note pipeline; confirm regressions reproduce; file-only',
  phases: [{ title: 'Find' }, { title: 'Verify' }],
}
const FINDER = { model: 'haiku', effort: 'low' }
const VERIFIER = { model: 'opus', effort: 'high' }
const CHECKS = [
  'pytest tests/unit green (contract suite)',
  'note-gen schema invariant: every claim source-anchored',
  'descriptive prompt byte-identical with grounded flag OFF',
  'grounded path cited when flag ON (test_grounded_synthesis_*, test_grounding_guard)',
  'provider-registry parity: all providers return same schema',
]
const FIND = { type:'object', additionalProperties:false, required:['regressions'], properties:{ regressions:{ type:'array', items:{
  type:'object', additionalProperties:false, required:['check','command','observed','severity'],
  properties:{ check:{type:'string'}, command:{type:'string'}, observed:{type:'string'}, severity:{enum:['low','medium','high','critical']} } } } } }
const V = { type:'object', additionalProperties:false, required:['reproduces','reason'], properties:{ reproduces:{type:'boolean'}, reason:{type:'string'} } }

phase('Find')
const found = (await parallel(CHECKS.map((c) => () =>
  agent(`Core-quality CHECKER for Aurion. Run/assert: "${c}". Report a regression ONLY if a concrete check `
    + `fails, with the exact command + observed output. Empty if it passes.`,
    { ...FINDER, label: `chk:${c.slice(0,16)}`, phase: 'Find', schema: FIND })
))).filter(Boolean).flatMap((r) => r.regressions)

phase('Verify')
async function confirm(r) {
  // A regression is real only if it RE-RUNS to the same failure (not flaky/env).
  const votes = await parallel(Array.from({ length: 3 }, (_, i) => () =>
    agent(`Re-run and adversarially confirm this regression reproduces deterministically (not flaky/env). `
      + `Default reproduces=false. Regression: ${JSON.stringify(r)}`,
      { ...VERIFIER, label: `v:${r.check.slice(0,12)}#${i}`, phase: 'Verify', schema: V })))
  return votes.filter(Boolean).filter((v) => v.reproduces).length >= 2 ? r : null
}
const confirmed = (await parallel(found.map((r) => () => confirm(r)))).filter(Boolean)
return { found: found.length, confirmed }
