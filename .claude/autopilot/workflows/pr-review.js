export const meta = {
  name: 'autopilot-pr-review',
  description: 'Review one open PR across dimensions, adversarially verify, return consolidated notes (advisory)',
  phases: [{ title: 'Find' }, { title: 'Verify' }],
}
const FINDER = { model: 'haiku', effort: 'low' }
const VERIFIER = { model: 'opus', effort: 'high' }
// args = { pr: <number>, diffRef: <head sha> }
const DIMS = ['correctness / logic bug', 'security / PHI / authz', 'project conventions (DRY/SOLID, registry, descriptive-mode)', 'test coverage of the change']
const FIND = { type:'object', additionalProperties:false, required:['notes'], properties:{ notes:{ type:'array', items:{
  type:'object', additionalProperties:false, required:['dimension','severity','where','note'],
  properties:{ dimension:{type:'string'}, severity:{enum:['nit','minor','major','blocker']}, where:{type:'string'}, note:{type:'string'} } } } } }
const V = { type:'object', additionalProperties:false, required:['real','reason'], properties:{ real:{type:'boolean'}, reason:{type:'string'} } }

phase('Find')
const pr = args && args.pr
const found = (await parallel(DIMS.map((d) => () =>
  agent(`PR REVIEWER for Aurion. Review PR #${pr} (use gh to read its diff) on the "${d}" dimension. `
    + `Report only substantive notes with exact location. Empty if clean.`,
    { ...FINDER, label: `rev:${d.slice(0,14)}`, phase: 'Find', schema: FIND })
))).filter(Boolean).flatMap((r) => r.notes)

phase('Verify')
async function confirm(n) {
  const votes = await parallel(Array.from({ length: 3 }, (_, i) => () =>
    agent(`Adversarially REFUTE this PR-review note against the ACTUAL diff of PR #${pr}. Default real=false; `
      + `keep only if it's a true issue in the diff (not a nitpick/false positive). Note: ${JSON.stringify(n)}`,
      { ...VERIFIER, label: `v:${n.dimension.slice(0,10)}#${i}`, phase: 'Verify', schema: V })))
  return votes.filter(Boolean).filter((v) => v.real).length >= 2 ? n : null
}
const confirmed = (await parallel(found.map((n) => () => confirm(n)))).filter(Boolean)
return { pr, found: found.length, confirmed }
