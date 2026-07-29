import { describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import VisitTypeContextsEditor, {
  BUILT_IN_TEMPLATE_KEYS,
  MAX_CONTEXTS_PER_VISIT_TYPE,
  newContextId,
  type ContextCustomTemplate,
} from "@/components/portal/VisitTypeContextsEditor";
import type { VisitTypeContext } from "@/types";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { withIntl } from "./helpers/intl";

/**
 * #313/W1 — VisitTypeContextsEditor.
 *
 * Covers:
 *   - one accordion per visit type; default keys localize, customs render verbatim
 *   - expanding a section reveals its context rows + the Add affordance
 *   - the template <select> offers "Use my specialty default" + the 8 built-ins
 *   - editing a label / template patches the controlled value
 *   - "Add context" reuses validateConsultationType (PHI gates block Add)
 *   - delete removes a context; emptying a visit type drops its map key
 *   - the 30-per-visit-type soft cap hides Add + shows the limit hint
 *   - new ids are well-formed ctx_<8 hex> (so the backend preserves them)
 *   - EN + FR catalogs share the Profile.contexts.* key tree
 */

type CtxMap = Record<string, VisitTypeContext[]>;

function Harness({
  visitTypes,
  initial,
  customTemplates,
}: {
  visitTypes: string[];
  initial: CtxMap;
  customTemplates?: ContextCustomTemplate[];
}) {
  const [value, setValue] = useState<CtxMap>(initial);
  return (
    <>
      <VisitTypeContextsEditor
        visitTypes={visitTypes}
        value={value}
        onChange={setValue}
        customTemplates={customTemplates}
      />
      <pre data-testid="state">{JSON.stringify(value)}</pre>
    </>
  );
}

const CUSTOM_TEMPLATES: ContextCustomTemplate[] = [
  { id: "11111111-1111-1111-1111-111111111111", display_name: "Knee Protocol" },
  {
    id: "22222222-2222-2222-2222-222222222222",
    display_name: "Shoulder Workup",
  },
];

/** A context already bound to a custom `template_ref`. */
function ctxRef(label: string, template_ref: string): VisitTypeContext {
  return { id: newContextId(), label, template_key: null, template_ref };
}

function getState(): CtxMap {
  return JSON.parse(screen.getByTestId("state").textContent ?? "{}");
}

/** The per-context template select — disambiguated from the TE-4h
 * default-template select rendered in the same panel. */
function rowSelect(): HTMLSelectElement {
  return screen.getByRole("combobox", {
    name: /template for context/i,
  }) as HTMLSelectElement;
}

function ctx(label: string, template_key: string | null = null): VisitTypeContext {
  return { id: newContextId(), label, template_key, template_ref: null };
}

/* ── Accordion rendering ──────────────────────────────────────────────── */

describe("VisitTypeContextsEditor — accordions", () => {
  it("renders one section per visit type, localizing default keys", () => {
    render(
      withIntl(
        <Harness visitTypes={["new_patient", "Breast"]} initial={{}} />,
      ),
    );
    expect(
      screen.getByRole("button", { name: /new patient/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /breast/i })).toBeInTheDocument();
  });

  it("shows an empty-state hint when there are no visit types", () => {
    render(withIntl(<Harness visitTypes={[]} initial={{}} />));
    expect(screen.getByText(/add a visit type above/i)).toBeInTheDocument();
  });

  it("expands a section to reveal contexts + the Add affordance", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee")] }}
        />,
      ),
    );
    // Collapsed by default — context label input not yet shown.
    expect(screen.queryByDisplayValue("Left knee")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    expect(screen.getByDisplayValue("Left knee")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /add context/i }),
    ).toBeInTheDocument();
  });
});

/* ── Template select ──────────────────────────────────────────────────── */

describe("VisitTypeContextsEditor — template select", () => {
  it("offers only the my-specialty-default option (no flat built-in list) — TE-4e", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee")] }}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    const select = rowSelect();
    // Only "Use my specialty default" — specialty is a profile property, not a
    // per-context pick, so the 8-specialty list is gone.
    expect(within(select).getAllByRole("option")).toHaveLength(1);
    expect(
      within(select).getByRole("option", { name: /use my specialty default/i }),
    ).toBeInTheDocument();
    expect(
      within(select).queryByRole("option", { name: /orthopedic surgery/i }),
    ).not.toBeInTheDocument();
  });

  it("surfaces a legacy built-in template_key as a re-pickable option, not a blank select (TE-4e)", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee", "orthopedic_surgery")] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    const select = rowSelect();
    // The built-in key has no normal option anymore; a placeholder keeps the
    // <select> ON it (value round-trips) instead of snapping silently to blank.
    expect(select.value).toBe("orthopedic_surgery");
    expect(
      within(select).getByRole("option", { name: /specialty template/i }),
    ).toBeInTheDocument();
  });
});

/* ── Custom templates (#320/W2) ───────────────────────────────────────── */

describe("VisitTypeContextsEditor — custom templates", () => {
  it("adds a Custom templates optgroup populated from the owned library", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee")] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    const select = rowSelect();
    // 1 default + 2 custom (TE-4e: no flat built-in list).
    expect(within(select).getAllByRole("option")).toHaveLength(
      1 + CUSTOM_TEMPLATES.length,
    );
    expect(
      within(select).getByRole("group", { name: /custom templates/i }),
    ).toBeInTheDocument();
    expect(
      within(select).getByRole("option", { name: /knee protocol/i }),
    ).toBeInTheDocument();
  });

  it("sets template_ref + clears template_key when a custom option is picked", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee", "orthopedic_surgery")] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    const select = rowSelect();
    await user.selectOptions(select, CUSTOM_TEMPLATES[0].id);
    await waitFor(() => {
      const row = getState().new_patient[0];
      expect(row.template_ref).toBe(CUSTOM_TEMPLATES[0].id);
      expect(row.template_key).toBeNull();
    });
  });

  it("selecting the default clears a previously-bound custom ref", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{
            new_patient: [ctxRef("Left knee", CUSTOM_TEMPLATES[0].id)],
          }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    await user.selectOptions(rowSelect(), "");
    await waitFor(() => {
      const row = getState().new_patient[0];
      expect(row.template_ref).toBeNull();
      expect(row.template_key).toBeNull();
    });
  });

  it("shows only the my-specialty-default option when the custom library is empty", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee")] }}
          customTemplates={[]}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    const select = rowSelect();
    expect(within(select).getAllByRole("option")).toHaveLength(1);
    expect(
      within(select).queryByRole("group", { name: /custom templates/i }),
    ).not.toBeInTheDocument();
  });

  it("gracefully surfaces a stale ref whose template is gone, preserving the binding", async () => {
    const user = userEvent.setup();
    const staleId = "deadbeef-dead-dead-dead-deaddeaddead";
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctxRef("Left knee", staleId)] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    const select = rowSelect();
    // The placeholder option is selected (the select reflects the ref).
    expect(
      within(select).getByRole("option", { name: /unavailable/i }),
    ).toBeInTheDocument();
    expect(select.value).toBe(staleId);
    // No interaction → the binding is untouched (no silent reset).
    expect(getState().new_patient[0].template_ref).toBe(staleId);
  });
});

/* ── Add / edit / delete ──────────────────────────────────────────────── */

describe("VisitTypeContextsEditor — add / edit / delete", () => {
  it("adds a context with a well-formed ctx_ id and null template", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness visitTypes={["new_patient"]} initial={{}} />));
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    await user.click(screen.getByRole("button", { name: /add context/i }));
    await user.type(screen.getByLabelText(/context label/i), "Revision");
    await user.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => {
      const rows = getState().new_patient;
      expect(rows).toHaveLength(1);
      expect(rows[0].label).toBe("Revision");
      expect(rows[0].template_key).toBeNull();
      expect(rows[0].template_ref).toBeNull();
      expect(rows[0].id).toMatch(/^ctx_[0-9a-f]{8}$/);
    });
  });

  it("edits an existing context label in place", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee")] }}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    const input = screen.getByDisplayValue("Left knee");
    await user.type(input, " revision");
    await waitFor(() => {
      expect(getState().new_patient[0].label).toBe("Left knee revision");
    });
  });

  it("deletes a context and drops the map key when the last one goes", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee")] }}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    await user.click(
      screen.getByRole("button", { name: /remove context "left knee"/i }),
    );
    await waitFor(() => {
      expect(getState()).not.toHaveProperty("new_patient");
    });
  });
});

/* ── Context description (#576) ───────────────────────────────────────── */

describe("VisitTypeContextsEditor — context description", () => {
  it("renders a description textarea prefilled from ctx.description", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{
            new_patient: [
              { ...ctx("Left knee"), description: "ACL tear follow-up" },
            ],
          }}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    expect(screen.getByDisplayValue("ACL tear follow-up")).toBeInTheDocument();
  });

  it("patches description on edit and stores null when cleared", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee")] }}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    const area = screen.getByLabelText(/description for context/i);
    await user.type(area, "Post-op week 2");
    await waitFor(() => {
      expect(getState().new_patient[0].description).toBe("Post-op week 2");
    });
    await user.clear(area);
    await waitFor(() => {
      expect(getState().new_patient[0].description).toBeNull();
    });
  });

  it("starts a newly-added context with a null description", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness visitTypes={["new_patient"]} initial={{}} />));
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    await user.click(screen.getByRole("button", { name: /add context/i }));
    await user.type(screen.getByLabelText(/context label/i), "Revision");
    await user.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => {
      expect(getState().new_patient[0].description).toBeNull();
    });
  });
});

/* ── Validation reuse ─────────────────────────────────────────────────── */

describe("VisitTypeContextsEditor — validation gates", () => {
  it("blocks Add for an email-shaped label and surfaces the error", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness visitTypes={["new_patient"]} initial={{}} />));
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    await user.click(screen.getByRole("button", { name: /add context/i }));
    await user.type(screen.getByLabelText(/context label/i), "perry@clinic.lan");
    expect(screen.getByText(/email address/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
  });

  it("blocks Add for a duplicate label within the same visit type", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Breast")] }}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    await user.click(screen.getByRole("button", { name: /add context/i }));
    await user.type(screen.getByLabelText(/context label/i), "Breast");
    expect(screen.getByText(/already on the list/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
  });
});

/* ── Soft cap ─────────────────────────────────────────────────────────── */

describe("VisitTypeContextsEditor — soft cap", () => {
  it("hides Add + shows the limit hint at 30 contexts", async () => {
    const user = userEvent.setup();
    const full = Array.from({ length: MAX_CONTEXTS_PER_VISIT_TYPE }, (_, i) =>
      ctx(`ctx ${i}`),
    );
    render(
      withIntl(
        <Harness visitTypes={["new_patient"]} initial={{ new_patient: full }} />,
      ),
    );
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    expect(
      screen.queryByRole("button", { name: /add context/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/30 contexts maximum/i)).toBeInTheDocument();
  });
});

/* ── i18n parity ──────────────────────────────────────────────────────── */

describe("VisitTypeContextsEditor — i18n parity", () => {
  it("localizes the Add CTA + default template option in French", async () => {
    const user = userEvent.setup();
    render(
      withIntl(<Harness visitTypes={["new_patient"]} initial={{}} />, "fr"),
    );
    await user.click(screen.getByRole("button", { name: /nouveau patient/i }));
    expect(
      screen.getByRole("button", { name: /ajouter un contexte/i }),
    ).toBeInTheDocument();
  });

  it("EN and FR catalogs share the Profile.contexts key tree", () => {
    const en = (enMessages as Record<string, unknown>).Profile as Record<
      string,
      unknown
    >;
    const fr = (frMessages as Record<string, unknown>).Profile as Record<
      string,
      unknown
    >;
    const enCtx = en?.contexts;
    const frCtx = fr?.contexts;
    expect(enCtx).toBeDefined();
    expect(frCtx).toBeDefined();
    expect(walk(enCtx!).sort()).toEqual(walk(frCtx!).sort());
  });

  it("has a localized name for every built-in template key", () => {
    const en = (enMessages as Record<string, unknown>).Profile as Record<
      string,
      Record<string, Record<string, string>>
    >;
    const templates = en.contexts.templates;
    for (const key of BUILT_IN_TEMPLATE_KEYS) {
      expect(templates[key]).toBeTruthy();
    }
  });
});

/* ── Default template per visit type (TE-4h) ──────────────────────────── */

describe("VisitTypeContextsEditor — default template (TE-4h)", () => {
  const KNEE = CUSTOM_TEMPLATES[0];
  const SHOULDER = CUSTOM_TEMPLATES[1];

  /** The visit type's `is_default` context (#577). */
  function defaultCtx(patch: Partial<VisitTypeContext> = {}): VisitTypeContext {
    return {
      ...ctxRef("New patient", KNEE.id),
      id: "ctx_default1",
      is_default: true,
      ...patch,
    };
  }

  async function openPanel(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: /new patient/i }));
  }

  function defaultSelect(): HTMLSelectElement {
    return screen.getByRole("combobox", {
      name: /default template for/i,
    }) as HTMLSelectElement;
  }

  it("picking a custom template upserts the is_default row, preserving other contexts", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [ctx("Left knee")] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await openPanel(user);
    await user.selectOptions(defaultSelect(), KNEE.id);

    const rows = getState().new_patient;
    const def = rows.find((c) => c.is_default);
    expect(def?.template_ref).toBe(KNEE.id);
    expect(def?.template_key).toBeNull();
    expect(def?.label).toBe("New Patient");
    // The named context is untouched.
    expect(rows.some((c) => c.label === "Left knee" && !c.is_default)).toBe(
      true,
    );
  });

  it("picking the specialty default DROPS the is_default row (empty map key removed)", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [defaultCtx()] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await openPanel(user);
    expect(defaultSelect().value).toBe(KNEE.id);
    await user.selectOptions(defaultSelect(), "");
    // Sole row gone → the visit type's key is dropped entirely, so the PUT
    // carries no pinned default — the server falls through to specialty.
    expect(getState().new_patient).toBeUndefined();
  });

  it("re-picking preserves the row's id, label, and description", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{
            new_patient: [
              defaultCtx({ label: "My NP default", description: "keep me" }),
            ],
          }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await openPanel(user);
    await user.selectOptions(defaultSelect(), SHOULDER.id);

    const def = getState().new_patient.find((c) => c.is_default);
    expect(def?.id).toBe("ctx_default1");
    expect(def?.label).toBe("My NP default");
    expect(def?.description).toBe("keep me");
    expect(def?.template_ref).toBe(SHOULDER.id);
  });

  it("a default still pinned to a built-in shows the re-pick option, and '' clears it", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{
            new_patient: [
              defaultCtx({
                template_ref: null,
                template_key: "orthopedic_surgery",
              }),
            ],
          }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await openPanel(user);
    // The legacy pin is visible and selected — not a silent blank select.
    expect(defaultSelect().value).toBe("orthopedic_surgery");
    expect(
      within(defaultSelect()).getByText("Specialty template (re-pick)"),
    ).toBeInTheDocument();
    await user.selectOptions(defaultSelect(), "");
    expect(getState().new_patient).toBeUndefined();
  });

  it("a default whose custom template no longer resolves shows the unavailable placeholder", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [defaultCtx({ template_ref: "gone-id" })] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await openPanel(user);
    expect(defaultSelect().value).toBe("gone-id");
    expect(
      within(defaultSelect()).getByText("Custom template (unavailable)"),
    ).toBeInTheDocument();
  });

  it("the is_default row never renders as a context row; the badge counts named contexts only", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [defaultCtx(), ctx("Left knee")] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    const header = screen.getByRole("button", { name: /new patient/i });
    // Badge = named contexts only (1), not the hidden default row.
    expect(within(header).getByText("1")).toBeInTheDocument();
    // Collapsed summary names the default's template.
    expect(within(header).getByText("Default: Knee Protocol")).toBeInTheDocument();

    await openPanel(user);
    // Exactly one label input — the named context. No phantom "New patient" row.
    expect(screen.getByDisplayValue("Left knee")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("New patient")).not.toBeInTheDocument();
  });

  it("summarizes 'Specialty default' when nothing is pinned", () => {
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{}}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    const header = screen.getByRole("button", { name: /new patient/i });
    expect(
      within(header).getByText("Default: Specialty default"),
    ).toBeInTheDocument();
  });

  it("deleting a named context leaves the default row intact", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [defaultCtx(), ctx("Left knee")] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await openPanel(user);
    await user.click(
      screen.getByRole("button", { name: /remove context "left knee"/i }),
    );
    const rows = getState().new_patient;
    expect(rows).toHaveLength(1);
    expect(rows[0].is_default).toBe(true);
  });

  it("default select is disabled at the 30-context cap when no default exists (inserting would 422 the save)", async () => {
    const user = userEvent.setup();
    const full = Array.from({ length: MAX_CONTEXTS_PER_VISIT_TYPE }, (_, i) =>
      ctx(`Context ${i + 1}`),
    );
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: full }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await openPanel(user);
    expect(defaultSelect()).toBeDisabled();
    // The panel's single limit line (the Add area's) explains why.
    expect(screen.getByText(/30 contexts maximum/i)).toBeInTheDocument();
  });

  it("an existing default stays re-pickable at the cap (replacing never grows the list)", async () => {
    const user = userEvent.setup();
    const named = Array.from(
      { length: MAX_CONTEXTS_PER_VISIT_TYPE - 1 },
      (_, i) => ctx(`Context ${i + 1}`),
    );
    render(
      withIntl(
        <Harness
          visitTypes={["new_patient"]}
          initial={{ new_patient: [defaultCtx(), ...named] }}
          customTemplates={CUSTOM_TEMPLATES}
        />,
      ),
    );
    await openPanel(user);
    const sel = defaultSelect();
    expect(sel).toBeEnabled();
    await user.selectOptions(sel, SHOULDER.id);
    const rows = getState().new_patient;
    expect(rows).toHaveLength(MAX_CONTEXTS_PER_VISIT_TYPE);
    expect(rows.find((c) => c.is_default)?.template_ref).toBe(SHOULDER.id);
  });
});

function walk(obj: unknown, prefix = ""): string[] {
  if (obj === null || typeof obj !== "object") return [prefix.slice(0, -1)];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    walk(v, prefix + k + "."),
  );
}

