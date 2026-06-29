export const meta = {
  name: 'autopilot-research-digest',
  description: 'Web research relevant to the project; judge relevance/credibility; draft-only',
  phases: [{ title: 'Search' }, { title: 'Judge' }],
}
const FINDER = { model: 'haiku', effort: 'low' }
const JUDGE = { model: 'opus', effort: 'high' }
const THEMES = ['ambient clinical documentation / AI scribe market + competitors',
  'AI scribe regulation (FDA SaMD, Health Canada, Law 25 / PHIPA)',
  'grounded vs descriptive clinical note generation research',
  'on-device ASR / vision for clinical capture']
const ITEMS = { type:'object', additionalProperties:false, required:['items'], properties:{ items:{ type:'array', items:{
  type:'object', additionalProperties:false, required:['title','url','why'],
  properties:{ title:{type:'string'}, url:{type:'string'}, why:{type:'string'} } } } } }
const V = { type:'object', additionalProperties:false, required:['relevant','reason'], properties:{ relevant:{type:'boolean'}, reason:{type:'string'} } }

phase('Search')
const found = (await parallel(THEMES.map((t) => () =>
  agent(`Research FINDER for Aurion. Web-search "${t}". Return recent, sourced items (real URLs) with a one-line `
    + `"why it matters to Aurion". If web tools are unavailable here, return an empty list (do NOT fabricate).`,
    { ...FINDER, label: `res:${t.slice(0,14)}`, phase: 'Search', schema: ITEMS })
))).filter(Boolean).flatMap((r) => r.items)

phase('Judge')
async function keep(it) {
  const votes = await parallel(Array.from({ length: 3 }, (_, i) => () =>
    agent(`Adversarially judge: is this item in-scope for Aurion, from a credible/recent source, and actionable? `
      + `Default relevant=false; reject unsourced/off-scope. Item: ${JSON.stringify(it)}`,
      { ...JUDGE, label: `j#${i}`, phase: 'Judge', schema: V })))
  return votes.filter(Boolean).filter((v) => v.relevant).length >= 2 ? it : null
}
const confirmed = (await parallel(found.map((i) => () => keep(i)))).filter(Boolean)
return { found: found.length, confirmed }
