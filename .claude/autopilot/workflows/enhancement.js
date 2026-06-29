export const meta = {
  name: 'autopilot-enhancement',
  description: 'Ideate code-grounded improvements; judge panel vets novelty + value; file-only',
  phases: [{ title: 'Ideate' }, { title: 'Judge' }],
}
const FINDER = { model: 'haiku', effort: 'low' }
const JUDGE = { model: 'opus', effort: 'high' }
const AREAS = ['DX / build & test speed', 'backend perf / hot paths', 'test-coverage gaps', 'small UX / portal polish']
const IDEAS = { type:'object', additionalProperties:false, required:['ideas'], properties:{ ideas:{ type:'array', items:{
  type:'object', additionalProperties:false, required:['area','grounding','idea','effort'],
  properties:{ area:{type:'string'}, grounding:{type:'string'}, idea:{type:'string'}, effort:{enum:['S','M','L']} } } } } }
const V = { type:'object', additionalProperties:false, required:['worth','reason'], properties:{ worth:{type:'boolean'}, reason:{type:'string'} } }

phase('Ideate')
const found = (await parallel(AREAS.map((a) => () =>
  agent(`Enhancement IDEATOR for Aurion. Propose grounded improvements in "${a}" — each MUST cite a real `
    + `file/area (grounding). No speculative abstraction. A few strong ideas, not a list.`,
    { ...FINDER, label: `idea:${a.slice(0,12)}`, phase: 'Ideate', schema: IDEAS })
))).filter(Boolean).flatMap((r) => r.ideas)

phase('Judge')
async function worth(idea) {
  const votes = await parallel(Array.from({ length: 3 }, (_, i) => () =>
    agent(`Adversarially judge this enhancement: is it grounded in real code, NOVEL (check open issues), and `
      + `value >= effort? Default worth=false. Idea: ${JSON.stringify(idea)}`,
      { ...JUDGE, label: `j:${idea.area.slice(0,10)}#${i}`, phase: 'Judge', schema: V })))
  return votes.filter(Boolean).filter((v) => v.worth).length >= 2 ? idea : null
}
const confirmed = (await parallel(found.map((i) => () => worth(i)))).filter(Boolean)
return { found: found.length, confirmed }
