export const meta = {
  name: 'autopilot-dep-watch',
  description: 'Scan deps for outdated/CVE; verify safe; apply safe bumps in worktrees',
  phases: [{ title: 'Find' }, { title: 'Verify' }, { title: 'Apply' }],
}
const FINDER = { model: 'haiku', effort: 'low' }
const VERIFIER = { model: 'opus', effort: 'high' }
const FIXER = { model: 'opus', effort: 'medium' }
const ECO = ['backend Python (pip list --outdated + pip-audit)', 'web npm (npm outdated + npm audit)', 'iOS SPM resolved versions']
const FIND = { type:'object', additionalProperties:false, required:['bumps'], properties:{ bumps:{ type:'array', items:{
  type:'object', additionalProperties:false, required:['pkg','from','to','semver','cve'],
  properties:{ pkg:{type:'string'}, from:{type:'string'}, to:{type:'string'}, semver:{enum:['patch','minor','major']}, cve:{type:'string'} } } } } }
const V = { type:'object', additionalProperties:false, required:['safe','reason'], properties:{ safe:{type:'boolean'}, reason:{type:'string'} } }

phase('Find')
const found = (await parallel(ECO.map((e) => () =>
  agent(`Dependency FINDER for Aurion. In "${e}", list outdated/vulnerable packages with from→to + semver + any CVE. Empty if current.`,
    { ...FINDER, label: `dep:${e.slice(0,12)}`, phase: 'Find', schema: FIND })
))).filter(Boolean).flatMap((r) => r.bumps)

phase('Verify')
async function safe(b) {
  const votes = await parallel(Array.from({ length: 3 }, (_, i) => () =>
    agent(`Adversarially decide if this bump is SAFE to auto-merge. Default safe=false. safe=true ONLY for `
      + `patch/minor with no breaking changelog. Major / break-risk = false. Bump: ${JSON.stringify(b)}`,
      { ...VERIFIER, label: `v:${b.pkg}#${i}`, phase: 'Verify', schema: V })))
  return { ...b, safe: votes.filter(Boolean).filter((v) => v.safe).length >= 2 }
}
const judged = await parallel(found.map((b) => () => safe(b)))

phase('Apply')
// Apply safe bumps each in its own worktree; report green/red. Risky ones are escalated by the skill.
const applied = await parallel(judged.filter((b) => b.safe).map((b) => () =>
  agent(`Apply the bump ${b.pkg} ${b.from}->${b.to} (manifest + lockfile only, minimal diff). Run the build/tests; `
    + `report green + changed_files + branch. Don't touch protected paths. Bump: ${JSON.stringify(b)}`,
    { ...FIXER, label: `bump:${b.pkg}`, phase: 'Apply', isolation: 'worktree',
      schema: { type:'object', additionalProperties:false, required:['branch','green','changed_files'],
        properties:{ branch:{type:'string'}, green:{type:'boolean'}, changed_files:{type:'array',items:{type:'string'}} } } })
    .then((r) => r && ({ ...b, ...r }))
)).then((a) => a.filter(Boolean))
return { found: found.length, safe: judged.filter((b)=>b.safe).length, risky: judged.filter((b)=>!b.safe), applied }
