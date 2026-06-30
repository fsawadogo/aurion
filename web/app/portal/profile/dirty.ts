import type { PhysicianProfile } from "@/types";

/** Deep-compare two visit-type → context maps. Context order within a
 * visit type is significant (it's the render + save order), so we
 * compare positionally; only the key set is order-insensitive.
 *
 * Lives outside `page.tsx` because a Next route module may only export the
 * page default + framework hooks — exporting a helper from there fails the
 * generated page-type check (and lets this be unit-tested directly). */
export function sameContexts(
  a: Record<string, PhysicianProfile["contexts_per_visit_type"][string]>,
  b: Record<string, PhysicianProfile["contexts_per_visit_type"][string]>,
): boolean {
  const aKeys = Object.keys(a).sort();
  const bKeys = Object.keys(b).sort();
  if (aKeys.length !== bKeys.length) return false;
  for (let i = 0; i < aKeys.length; i++) {
    if (aKeys[i] !== bKeys[i]) return false;
    const av = a[aKeys[i]];
    const bv = b[bKeys[i]];
    if (av.length !== bv.length) return false;
    for (let j = 0; j < av.length; j++) {
      if (
        av[j].id !== bv[j].id ||
        av[j].label !== bv[j].label ||
        av[j].template_key !== bv[j].template_key ||
        av[j].template_ref !== bv[j].template_ref ||
        // #576: a description-only edit must mark the form dirty. Normalize
        // undefined↔null so a freshly-loaded context (key omitted) and an
        // edited one (explicit null) don't read as a spurious change.
        (av[j].description ?? null) !== (bv[j].description ?? null)
      ) {
        return false;
      }
    }
  }
  return true;
}
