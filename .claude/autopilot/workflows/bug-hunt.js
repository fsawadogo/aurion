export const meta = {
  name: 'autopilot-bug-hunt',
  description: 'Find real bugs by class, adversarially verify, fix verified non-protected ones in worktrees',
  phases: [
    { title: 'Find', detail: 'cheap finders, one per bug class, in parallel' },
    { title: 'Verify', detail: 'adversarial refute panel (strong model) — majority confirms' },
    { title: 'Fix', detail: 'strong fixer in an isolated worktree + regression test' },
  ],
}

// Model split (mirrors policy.json models): finders cheap, verifiers/fixers strong.
const FINDER = { model: 'haiku', effort: 'low' }
const VERIFIER = { model: 'opus', effort: 'high' }
const FIXER = { model: 'opus', effort: 'medium' }

const CLASSES = [
  'un-awaited coroutine / async-await misuse',
  'missing or non-append-only audit write',
  'Pydantic validation gap / unvalidated input',
  'SQLAlchemy async session misuse / N+1',
  'provider-registry bypass (if provider == ...)',
  'unhandled None / KeyError on .get',
  'iOS @MainActor isolation / unsafe force-unwrap',
  'missing EN/FR localization parity',
]

const BUG = { type: 'object', additionalProperties: false,
  required: ['file', 'bug_class', 'title', 'detail', 'severity'],
  properties: { file: {type:'string'}, bug_class:{type:'string'}, title:{type:'string'},
    detail:{type:'string'}, severity:{enum:['low','medium','high','critical']} } }
const FINDINGS = { type:'object', additionalProperties:false, required:['bugs'],
  properties:{ bugs:{ type:'array', items: BUG } } }
const VERDICT = { type:'object', additionalProperties:false, required:['real','reason'],
  properties:{ real:{type:'boolean'}, reason:{type:'string'} } }

phase('Find')
const found = (await parallel(CLASSES.map((c) => () =>
  agent(`You are a bug FINDER for the Aurion clinical backend/iOS repo. Hunt ONLY for: "${c}". `
    + `Read real code; report concrete, reproducible suspects with file + a one-line repro. `
    + `Be precise, not exhaustive. If none, return an empty list.`,
    { ...FINDER, label: `find:${c.slice(0,18)}`, phase: 'Find', schema: FINDINGS })
))).filter(Boolean).flatMap((r) => r.bugs)

// Verify is the heart: 3 adversarial refuters, default NOT real, need a majority.
async function verified(bug) {
  const votes = await parallel(Array.from({ length: 3 }, (_, i) => () =>
    agent(`Adversarially REFUTE this claimed bug. Default to real=false; only set real=true if you can `
      + `point to the exact code path + a concrete repro/trace. Claim: ${JSON.stringify(bug)}`,
      { ...VERIFIER, label: `verify:${bug.file}#${i}`, phase: 'Verify', schema: VERDICT })))
  const confirms = votes.filter(Boolean).filter((v) => v.real).length
  return confirms >= 2 ? { ...bug, confirmed: true } : null
}

phase('Verify')
const confirmed = (await parallel(found.map((b) => () => verified(b)))).filter(Boolean)

phase('Fix')
// Fix each confirmed bug in its OWN worktree (parallel-safe). Returns the branch +
// whether the build/regression-test passed; the SKILL gates + opens the PR.
const fixes = await parallel(confirmed.map((b) => () =>
  agent(`Fix this verified bug with the MINIMAL diff + a regression test that fails before your fix. `
    + `Follow .claude/autopilot/ENGINEERING_STANDARDS.md. Run the build/tests; report green/red + the `
    + `changed files + the branch. Do NOT touch protected paths (policy.json) — if the fix would, STOP `
    + `and report needs_escalation=true. Bug: ${JSON.stringify(b)}`,
    { ...FIXER, label: `fix:${b.file}`, phase: 'Fix', isolation: 'worktree',
      schema: { type:'object', additionalProperties:false,
        required:['branch','green','changed_files','needs_escalation'],
        properties:{ branch:{type:'string'}, green:{type:'boolean'},
          changed_files:{type:'array',items:{type:'string'}}, needs_escalation:{type:'boolean'},
          note:{type:'string'} } } })
    .then((f) => f && ({ ...b, ...f }))
)).filter(Boolean)

return { found: found.length, confirmed: confirmed.length, fixes }
