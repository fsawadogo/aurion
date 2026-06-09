import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import AdminTemplatesPage from "@/app/portal/admin/templates/page";
import { withIntl } from "./helpers/intl";

/**
 * /portal/admin/templates — built-in template management (#72 final slice).
 *
 * Verifies the list renders with override badges, selecting a template
 * loads the editor, saving PUTs the normalized draft with the key locked
 * to the bundled identity, revert flows through the confirm modal, and
 * the FR catalog renders at parity.
 */

vi.mock("@/lib/api", () => ({
  getAdminTemplates: vi.fn(),
  getAdminTemplateDetail: vi.fn(),
  putAdminTemplate: vi.fn(),
  revertAdminTemplate: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import {
  getAdminTemplateDetail,
  getAdminTemplates,
  putAdminTemplate,
  revertAdminTemplate,
} from "@/lib/api";

const LIST = {
  items: [
    {
      template_key: "general",
      display_name: "General",
      version: "1.0",
      section_count: 5,
      is_override: false,
    },
    {
      template_key: "orthopedic_surgery",
      display_name: "Orthopedic Surgery",
      version: "1.0",
      section_count: 6,
      is_override: true,
    },
  ],
};

const DETAIL = {
  template: {
    key: "orthopedic_surgery",
    display_name: "Orthopedic Surgery",
    version: "1.0",
    sections: [
      {
        id: "chief_complaint",
        title: "Chief Complaint",
        required: true,
        visual_trigger_keywords: ["rom"],
        description: "",
      },
    ],
  },
  is_override: true,
  updated_at: null,
  note: "",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAdminTemplates).mockResolvedValue(LIST as never);
  vi.mocked(getAdminTemplateDetail).mockResolvedValue(DETAIL as never);
  vi.mocked(putAdminTemplate).mockResolvedValue(DETAIL as never);
  vi.mocked(revertAdminTemplate).mockResolvedValue(undefined as never);
});

describe("AdminTemplatesPage", () => {
  it("lists templates with the override badge", async () => {
    render(withIntl(<AdminTemplatesPage />));

    await waitFor(() =>
      expect(screen.getByTestId("template-item-general")).toBeInTheDocument(),
    );
    const ortho = screen.getByTestId("template-item-orthopedic_surgery");
    expect(ortho).toHaveTextContent("Orthopedic Surgery");
    expect(ortho).toHaveTextContent("Edited"); // override badge
    expect(screen.getByTestId("template-item-general")).not.toHaveTextContent("Edited");
  });

  it("selecting a template loads the editor panel", async () => {
    render(withIntl(<AdminTemplatesPage />));
    await waitFor(() =>
      expect(screen.getByTestId("template-item-orthopedic_surgery")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("template-item-orthopedic_surgery"));
    await waitFor(() =>
      expect(screen.getByTestId("template-editor-panel")).toBeInTheDocument(),
    );
    expect(getAdminTemplateDetail).toHaveBeenCalledWith("orthopedic_surgery");
    // Editor rendered with the loaded section.
    expect(screen.getByDisplayValue("Chief Complaint")).toBeInTheDocument();
    // An override exists → the revert affordance shows.
    expect(screen.getByRole("button", { name: /Revert to default/ })).toBeInTheDocument();
  });

  it("save PUTs the draft with the key locked to the bundled identity", async () => {
    render(withIntl(<AdminTemplatesPage />));
    await waitFor(() =>
      expect(screen.getByTestId("template-item-orthopedic_surgery")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("template-item-orthopedic_surgery"));
    await waitFor(() =>
      expect(screen.getByDisplayValue("Chief Complaint")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    await waitFor(() => expect(putAdminTemplate).toHaveBeenCalledTimes(1));

    const [keyArg, templateArg] = vi.mocked(putAdminTemplate).mock.calls[0];
    expect(keyArg).toBe("orthopedic_surgery");
    expect(templateArg.key).toBe("orthopedic_surgery"); // immutable
    await waitFor(() =>
      expect(
        screen.getByText("Template saved — live within ~10 seconds fleet-wide."),
      ).toBeInTheDocument(),
    );
    // List refreshed after save.
    expect(getAdminTemplates).toHaveBeenCalledTimes(2);
  });

  it("revert flows through the confirm modal and DELETEs", async () => {
    render(withIntl(<AdminTemplatesPage />));
    await waitFor(() =>
      expect(screen.getByTestId("template-item-orthopedic_surgery")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("template-item-orthopedic_surgery"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Revert to default/ })).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: /Revert to default/ }));
    // Modal appears; nothing deleted yet.
    expect(revertAdminTemplate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Revert$/ }));

    await waitFor(() =>
      expect(revertAdminTemplate).toHaveBeenCalledWith("orthopedic_surgery"),
    );
    await waitFor(() =>
      expect(
        screen.getByText("Override removed — the disk default is live again."),
      ).toBeInTheDocument(),
    );
  });

  it("renders the FR catalog at parity", async () => {
    render(withIntl(<AdminTemplatesPage />, "fr"));
    await waitFor(() =>
      expect(screen.getByText("Modèles système")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Modifiez les modèles de spécialité intégrés/),
    ).toBeInTheDocument();
    // Badge on the overridden row.
    await waitFor(() =>
      expect(screen.getByTestId("template-item-orthopedic_surgery")).toHaveTextContent(
        "Modifié",
      ),
    );
  });

  it("surfaces a list load error", async () => {
    vi.mocked(getAdminTemplates).mockRejectedValue(new Error("boom"));
    render(withIntl(<AdminTemplatesPage />));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Unable to load templates."),
    );
  });
});
