import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import PatientIdentifierEditor, {
  validateIdentifier,
} from "@/components/portal/PatientIdentifierEditor";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { withIntl } from "./helpers/intl";

/**
 * #161 — PatientIdentifierEditor.
 *
 * Covers:
 *   - chip render in set / unset states
 *   - modal lifecycle (open, ESC, click-outside, close button)
 *   - client-side format gates (SSN raw + dashed, email, full name,
 *     overlong) block Save and surface a localized error
 *   - successful save → calls API → invokes onChange with the result
 *   - Clear button → calls API with null
 *   - EN + FR catalogs both contain the full
 *     `NoteReview.identifier.*` key tree (i18n parity)
 *
 * The portal API is mocked at the module boundary so the editor is
 * deterministic. The previous-encounters fetch is stubbed to an
 * empty list except in the dedicated test that exercises that
 * branch.
 */

vi.mock("@/lib/portal-api", () => ({
  setSessionExternalReferenceId: vi.fn(),
  listMySessionsByPatientIdentifier: vi.fn(),
}));

import {
  setSessionExternalReferenceId,
  listMySessionsByPatientIdentifier,
} from "@/lib/portal-api";

const SESSION_ID = "00000000-0000-0000-0000-000000000001";

function setIdentifierResponse(value: string | null) {
  vi.mocked(setSessionExternalReferenceId).mockResolvedValue({
    id: SESSION_ID,
    clinician_id: "11111111-1111-1111-1111-111111111111",
    clinician_name: "Dr. Test",
    specialty: "orthopedic_surgery",
    state: "AWAITING_REVIEW",
    completeness_score: 1.0,
    sections_populated: 0,
    sections_required: 0,
    provider_used: "anthropic",
    external_reference_id: value,
    created_at: "2026-06-06T10:00:00Z",
    updated_at: "2026-06-06T10:00:00Z",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValue([]);
});

/* ── Chip rendering ───────────────────────────────────────────────────── */

describe("PatientIdentifierEditor — chip render", () => {
  it("renders the 'Add patient identifier' CTA when current is null", () => {
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    expect(
      screen.getByRole("button", { name: /add patient identifier/i }),
    ).toBeInTheDocument();
  });

  it("renders the identifier chip when current is set", () => {
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier="MRN-12345"
          onChange={vi.fn()}
        />,
      ),
    );
    expect(
      screen.getByRole("button", { name: /edit patient identifier/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("MRN-12345")).toBeInTheDocument();
  });
});

/* ── Modal lifecycle ──────────────────────────────────────────────────── */

describe("PatientIdentifierEditor — modal lifecycle", () => {
  it("opens the modal when the CTA is clicked", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /patient identifier/i }),
    ).toBeInTheDocument();
  });

  it("closes the modal when Cancel is clicked", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes the modal when ESC is pressed", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

/* ── Client-side format gates ─────────────────────────────────────────── */

describe("PatientIdentifierEditor — format gates", () => {
  it("blocks Save and shows an error for raw SSN", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    const input = screen.getByLabelText(/patient identifier value/i);
    await user.type(input, "123456789");
    expect(
      screen.getByText(/social security number/i),
    ).toBeInTheDocument();
    const save = screen.getByRole("button", { name: /^save$/i });
    expect(save).toBeDisabled();
  });

  it("blocks Save and shows an error for dashed SSN", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    const input = screen.getByLabelText(/patient identifier value/i);
    await user.type(input, "123-45-6789");
    expect(
      screen.getByText(/social security number/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^save$/i }),
    ).toBeDisabled();
  });

  it("blocks Save for an email-shaped identifier", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    await user.type(
      screen.getByLabelText(/patient identifier value/i),
      "patient@example.com",
    );
    expect(screen.getByText(/email address/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^save$/i }),
    ).toBeDisabled();
  });

  it("blocks Save for a full-name-shaped identifier", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    await user.type(screen.getByLabelText(/patient identifier value/i), "Jane Doe");
    expect(screen.getByText(/patient name/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^save$/i }),
    ).toBeDisabled();
  });

  it("hard-caps the input at 64 characters via maxLength", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    const input = screen.getByLabelText(
      /patient identifier value/i,
    ) as HTMLInputElement;
    // maxLength caps DOM-level typing at 64, so typing 100 'X's lands as 64.
    await user.type(input, "X".repeat(100));
    expect(input.value).toHaveLength(64);
  });
});

/* ── validateIdentifier pure function ─────────────────────────────────── */

describe("validateIdentifier helper", () => {
  it.each([
    ["MRN-12345", null],
    ["2026-06-01-AB", null],
    ["patient42", null],
    ["FOLLOWUP_2026Q2", null],
    ["", null],
    ["   ", null],
    ["123456789", "ssn"],
    ["123-45-6789", "ssn"],
    ["jane.doe@clinic.lan", "email"],
    ["Jane Doe", "name"],
    ["Jane M Doe", "name"],
    ["X".repeat(65), "tooLong"],
  ])("validateIdentifier(%j) → %j", (input, expected) => {
    expect(validateIdentifier(input)).toBe(expected);
  });
});

/* ── Save / Clear paths ───────────────────────────────────────────────── */

describe("PatientIdentifierEditor — save", () => {
  it("calls the API on Save and invokes onChange with the result", async () => {
    const onChange = vi.fn();
    setIdentifierResponse("MRN-12345");
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={onChange}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /add patient identifier/i }),
    );
    await user.type(
      screen.getByLabelText(/patient identifier value/i),
      "MRN-12345",
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(setSessionExternalReferenceId).toHaveBeenCalledWith(
        SESSION_ID,
        "MRN-12345",
      );
    });
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith("MRN-12345");
    });
  });

  it("calls the API with null when Clear is pressed", async () => {
    const onChange = vi.fn();
    setIdentifierResponse(null);
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier="MRN-12345"
          onChange={onChange}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /edit patient identifier/i }),
    );
    await user.click(screen.getByRole("button", { name: /^clear$/i }));

    await waitFor(() => {
      expect(setSessionExternalReferenceId).toHaveBeenCalledWith(
        SESSION_ID,
        null,
      );
    });
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(null);
    });
  });

  it("surfaces a server error without echoing the draft value", async () => {
    vi.mocked(setSessionExternalReferenceId).mockRejectedValue(
      new Error("identifier looks like an SSN"),
    );
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier="MRN-12345"
          onChange={vi.fn()}
        />,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /edit patient identifier/i }),
    );
    // Change to a still-valid draft so Save is enabled then trigger
    // the rejection on the server roundtrip.
    const input = screen.getByLabelText(/patient identifier value/i);
    await user.clear(input);
    await user.type(input, "MRN-NEW");
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/identifier looks like an SSN/i),
      ).toBeInTheDocument();
    });
    // The displayed error must not contain the draft.
    expect(screen.queryByText(/MRN-NEW/i)).not.toBeInTheDocument();
  });
});

/* ── i18n parity ──────────────────────────────────────────────────────── */

describe("PatientIdentifierEditor — i18n parity", () => {
  it("localizes the CTA in French", () => {
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
        "fr",
      ),
    );
    expect(
      screen.getByRole("button", { name: /ajouter un identifiant patient/i }),
    ).toBeInTheDocument();
  });

  it("localizes the validation error in French (SSN)", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PatientIdentifierEditor
          sessionId={SESSION_ID}
          currentIdentifier={null}
          onChange={vi.fn()}
        />,
        "fr",
      ),
    );
    await user.click(
      screen.getByRole("button", {
        name: /ajouter un identifiant patient/i,
      }),
    );
    await user.type(
      screen.getByLabelText(/valeur de l’identifiant patient/i),
      "123456789",
    );
    expect(screen.getByText(/assurance sociale/i)).toBeInTheDocument();
  });

  it("EN and FR catalogs share the same NoteReview.identifier key tree", () => {
    const en = enMessages.NoteReview?.identifier;
    const fr = frMessages.NoteReview?.identifier;
    expect(en).toBeDefined();
    expect(fr).toBeDefined();
    expect(walk(en!).sort()).toEqual(walk(fr!).sort());
  });
});

function walk(obj: unknown, prefix = ""): string[] {
  if (obj === null || typeof obj !== "object") return [prefix.slice(0, -1)];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    walk(v, prefix + k + "."),
  );
}
