import { describe, expect, it } from "vitest";

import { sameContexts } from "@/app/portal/profile/dirty";
import type { VisitTypeContext } from "@/types";

/**
 * #576 — the profile page's `sameContexts` dirty-check must account for the
 * per-context `description` field. Without it, a description-only edit never
 * marks the form dirty, so the Save button stays disabled and the edit is
 * silently unsaveable. These pin that contract (the component-level editor
 * tests don't exercise the page's dirty gate).
 */

type CtxMap = Record<string, VisitTypeContext[]>;

function ctx(over: Partial<VisitTypeContext> = {}): VisitTypeContext {
  return {
    id: "ctx_00000001",
    label: "Left knee",
    template_key: null,
    template_ref: null,
    ...over,
  };
}

describe("profile sameContexts — description (#576)", () => {
  it("is equal for identical maps including description", () => {
    const a: CtxMap = { new_patient: [ctx({ description: "ACL follow-up" })] };
    const b: CtxMap = { new_patient: [ctx({ description: "ACL follow-up" })] };
    expect(sameContexts(a, b)).toBe(true);
  });

  it("is NOT equal when only the description differs (so it marks the form dirty)", () => {
    const a: CtxMap = { new_patient: [ctx({ description: null })] };
    const b: CtxMap = { new_patient: [ctx({ description: "ACL follow-up" })] };
    expect(sameContexts(a, b)).toBe(false);
  });

  it("treats a missing description key and explicit null as equal (no spurious dirty on load)", () => {
    const a: CtxMap = { new_patient: [ctx()] }; // no description key (as loaded)
    const b: CtxMap = { new_patient: [ctx({ description: null })] };
    expect(sameContexts(a, b)).toBe(true);
  });

  it("still detects label/template changes (existing behavior intact)", () => {
    const a: CtxMap = { new_patient: [ctx({ description: "x" })] };
    const b: CtxMap = {
      new_patient: [ctx({ description: "x", template_key: "orthopedic_surgery" })],
    };
    expect(sameContexts(a, b)).toBe(false);
  });
});
