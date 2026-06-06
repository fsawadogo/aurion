import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import ConsultationTypesEditor, {
  MAX_CUSTOM_CONSULTATION_TYPES,
  validateConsultationType,
} from "@/components/portal/ConsultationTypesEditor";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { withIntl } from "./helpers/intl";

/**
 * #259 — ConsultationTypesEditor.
 *
 * Covers:
 *   - default chips toggle on click; selection persists in the value
 *   - "Add custom type" opens an inline input; Cancel closes it
 *   - validation gates (empty / tooLong / SSN / email / full-name /
 *     duplicate) all block the Add button and surface a localized error
 *   - successful Add appends the trimmed value
 *   - delete removes the entry
 *   - the 20-custom soft cap hides the Add button + shows the limit hint
 *   - validateConsultationType is the canonical pure-function gate
 *   - EN + FR catalogs share the same `Profile.consultationTypes.custom.*`
 *     key tree
 */

/* ── Test harness that owns the controlled-input state. ──────────────── */

function Harness({ initial }: { initial: string[] }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ConsultationTypesEditor value={value} onChange={setValue} />
      <pre data-testid="state">{JSON.stringify(value)}</pre>
    </>
  );
}

function getState(): string[] {
  return JSON.parse(screen.getByTestId("state").textContent ?? "[]");
}

/* ── Default chips ────────────────────────────────────────────────────── */

describe("ConsultationTypesEditor — defaults", () => {
  it("renders the four default chips", () => {
    render(withIntl(<Harness initial={[]} />));
    expect(screen.getByRole("button", { name: /new patient/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /follow-up/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pre-op/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /post-op/i })).toBeInTheDocument();
  });

  it("toggles a default chip on click", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={["new_patient"]} />));
    await user.click(screen.getByRole("button", { name: /new patient/i }));
    expect(getState()).not.toContain("new_patient");
    await user.click(screen.getByRole("button", { name: /follow-up/i }));
    expect(getState()).toContain("follow_up");
  });
});

/* ── Custom add flow ──────────────────────────────────────────────────── */

describe("ConsultationTypesEditor — custom add", () => {
  it("opens the inline input when 'Add custom type' is clicked", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={[]} />));
    await user.click(screen.getByRole("button", { name: /add custom type/i }));
    expect(
      screen.getByLabelText(/custom consultation type name/i),
    ).toBeInTheDocument();
  });

  it("closes the inline input when Cancel is clicked", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={[]} />));
    await user.click(screen.getByRole("button", { name: /add custom type/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(
      screen.queryByLabelText(/custom consultation type name/i),
    ).not.toBeInTheDocument();
  });

  it("adds a custom type on Add click", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={[]} />));
    await user.click(screen.getByRole("button", { name: /add custom type/i }));
    await user.type(
      screen.getByLabelText(/custom consultation type name/i),
      "LL fu",
    );
    await user.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => {
      expect(getState()).toContain("LL fu");
    });
  });

  it("renders custom types as removable chips and deletes on click", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={["Breast"]} />));
    expect(screen.getByText("Breast")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /remove "breast"/i }));
    expect(getState()).not.toContain("Breast");
  });

  it("trims whitespace before adding", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={[]} />));
    await user.click(screen.getByRole("button", { name: /add custom type/i }));
    await user.type(
      screen.getByLabelText(/custom consultation type name/i),
      "  Breast  ",
    );
    await user.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => {
      expect(getState()).toContain("Breast");
    });
  });
});

/* ── Validation gates (AC-4) ──────────────────────────────────────────── */

describe("ConsultationTypesEditor — validation gates", () => {
  it("blocks Add for a raw SSN", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={[]} />));
    await user.click(screen.getByRole("button", { name: /add custom type/i }));
    await user.type(
      screen.getByLabelText(/custom consultation type name/i),
      "123456789",
    );
    expect(screen.getByText(/social security/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
  });

  it("blocks Add for an email-shaped label", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={[]} />));
    await user.click(screen.getByRole("button", { name: /add custom type/i }));
    await user.type(
      screen.getByLabelText(/custom consultation type name/i),
      "perry@clinic.lan",
    );
    expect(screen.getByText(/email address/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
  });

  it("blocks Add for a full-name-shaped label", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={[]} />));
    await user.click(screen.getByRole("button", { name: /add custom type/i }));
    await user.type(
      screen.getByLabelText(/custom consultation type name/i),
      "Marie Gdalevitch",
    );
    expect(screen.getByText(/patient names/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
  });

  it("blocks Add for a duplicate of an existing custom", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={["Breast"]} />));
    await user.click(screen.getByRole("button", { name: /add custom type/i }));
    await user.type(
      screen.getByLabelText(/custom consultation type name/i),
      "Breast",
    );
    expect(screen.getByText(/already on the list/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
  });
});

/* ── Soft cap (AC-3) ──────────────────────────────────────────────────── */

describe("ConsultationTypesEditor — soft cap", () => {
  it("hides the Add button when the cap is reached", () => {
    const customs = Array.from(
      { length: MAX_CUSTOM_CONSULTATION_TYPES },
      (_, i) => `custom_${i}`,
    );
    render(withIntl(<Harness initial={customs} />));
    expect(
      screen.queryByRole("button", { name: /add custom type/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/20 custom types maximum/i)).toBeInTheDocument();
  });
});

/* ── Pure-function gate ───────────────────────────────────────────────── */

describe("validateConsultationType helper", () => {
  it.each([
    ["LL fu", []],
    ["LL new pt", []],
    ["Breast", []],
    ["Breast visit", []],
    ["Pre-op-2026", []],
    ["x", []],
    [String.fromCharCode(...Array(60).fill(88)), []], // 60 X's
  ])("accepts %j", (input, existing) => {
    expect(validateConsultationType(input as string, existing as string[])).toBeNull();
  });

  it.each([
    ["", "empty"],
    ["   ", "empty"],
    [String.fromCharCode(...Array(61).fill(88)), "tooLong"],
    ["123456789", "ssn"],
    ["123-45-6789", "ssn"],
    ["jane.doe@clinic.lan", "email"],
    ["Marie Gdalevitch", "name"],
    ["Marie M Gdalevitch", "name"],
  ])("rejects %j with reason %s", (input, expected) => {
    expect(validateConsultationType(input as string, [])).toBe(expected);
  });

  it("rejects a duplicate against existing customs", () => {
    expect(validateConsultationType("Breast", ["Breast"])).toBe("duplicate");
  });

  it("rejects a duplicate against the canonical default keys", () => {
    expect(validateConsultationType("new_patient", [])).toBe("duplicate");
  });
});

/* ── i18n parity ──────────────────────────────────────────────────────── */

describe("ConsultationTypesEditor — i18n parity", () => {
  it("localizes the Add CTA in French", () => {
    render(withIntl(<Harness initial={[]} />, "fr"));
    expect(
      screen.getByRole("button", { name: /ajouter un type personnalisé/i }),
    ).toBeInTheDocument();
  });

  it("localizes the SSN validation error in French", async () => {
    const user = userEvent.setup();
    render(withIntl(<Harness initial={[]} />, "fr"));
    await user.click(
      screen.getByRole("button", { name: /ajouter un type personnalisé/i }),
    );
    await user.type(
      screen.getByLabelText(/nom du type de consultation personnalisé/i),
      "123456789",
    );
    expect(screen.getByText(/assurance sociale/i)).toBeInTheDocument();
  });

  it("EN and FR catalogs share the Profile.consultationTypes.custom key tree", () => {
    const en = (enMessages as Record<string, unknown>).Profile as Record<
      string,
      unknown
    >;
    const fr = (frMessages as Record<string, unknown>).Profile as Record<
      string,
      unknown
    >;
    const enCT = (en?.consultationTypes as Record<string, unknown>)?.custom;
    const frCT = (fr?.consultationTypes as Record<string, unknown>)?.custom;
    expect(enCT).toBeDefined();
    expect(frCT).toBeDefined();
    expect(walk(enCT!).sort()).toEqual(walk(frCT!).sort());
  });
});

function walk(obj: unknown, prefix = ""): string[] {
  if (obj === null || typeof obj !== "object") return [prefix.slice(0, -1)];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    walk(v, prefix + k + "."),
  );
}

/* ── vi mock fallthrough — unused, just here so the test file shape
 * matches the rest of the suite. */
vi.fn();
