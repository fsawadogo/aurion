import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import VisitTypeContextsEditor, {
  BUILT_IN_TEMPLATE_KEYS,
  MAX_CONTEXTS_PER_VISIT_TYPE,
  newContextId,
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
}: {
  visitTypes: string[];
  initial: CtxMap;
}) {
  const [value, setValue] = useState<CtxMap>(initial);
  return (
    <>
      <VisitTypeContextsEditor
        visitTypes={visitTypes}
        value={value}
        onChange={setValue}
      />
      <pre data-testid="state">{JSON.stringify(value)}</pre>
    </>
  );
}

function getState(): CtxMap {
  return JSON.parse(screen.getByTestId("state").textContent ?? "{}");
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
  it("offers the default option + all 8 built-in templates", async () => {
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
    const select = screen.getByRole("combobox");
    // 1 "Use my specialty default" + 8 built-ins.
    expect(within(select).getAllByRole("option")).toHaveLength(
      1 + BUILT_IN_TEMPLATE_KEYS.length,
    );
    expect(
      within(select).getByRole("option", { name: /use my specialty default/i }),
    ).toBeInTheDocument();
    expect(
      within(select).getByRole("option", { name: /orthopedic surgery/i }),
    ).toBeInTheDocument();
  });

  it("patches template_key on selection; default option maps back to null", async () => {
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
    const select = screen.getByRole("combobox");
    await user.selectOptions(select, "orthopedic_surgery");
    await waitFor(() => {
      expect(getState().new_patient[0].template_key).toBe("orthopedic_surgery");
    });
    await user.selectOptions(select, "");
    await waitFor(() => {
      expect(getState().new_patient[0].template_key).toBeNull();
    });
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

function walk(obj: unknown, prefix = ""): string[] {
  if (obj === null || typeof obj !== "object") return [prefix.slice(0, -1)];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    walk(v, prefix + k + "."),
  );
}

vi.fn();
