export const meta = {
  name: 'autopilot-digest',
  description: 'Meta-loop: sanity-check the reconciled accept-rate + ranking before the summary is sent',
  phases: [{ title: 'Audit' }],
}
const VERIFIER = { model: 'opus', effort: 'high' }
// args = { stats: <ledger stats --json>, ranked: [<open findings ranked>] }
phase('Audit')
const review = await agent(
  `You are the digest AUDITOR. Given the reconciled ledger stats + the ranked open findings below, verify: `
  + `(1) the accept-rate / cost-per-accepted numbers are internally consistent (no double-count), `
  + `(2) every loop below min_accept_rate is flagged for throttle/tune at the TOP, `
  + `(3) the ranking is severity x (1/effort) and the surfaced list respects the cap with an overflow note. `
  + `Return the corrected call-outs + any inconsistency. STATS=${JSON.stringify(args && args.stats)} `
  + `RANKED=${JSON.stringify(args && args.ranked)}`,
  { ...VERIFIER, label: 'digest:audit', phase: 'Audit',
    schema: { type:'object', additionalProperties:false, required:['ok','throttle_loops','top_callouts'],
      properties:{ ok:{type:'boolean'}, throttle_loops:{type:'array',items:{type:'string'}},
        top_callouts:{type:'array',items:{type:'string'}}, inconsistencies:{type:'array',items:{type:'string'}} } } })
return review
