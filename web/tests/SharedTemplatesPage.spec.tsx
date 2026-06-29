import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SharedTemplatesPage from "@/app/portal/admin/shared-templates/page";
import { withIntl } from "./helpers/intl";

vi.mock("@/lib/api", () => ({
  humanizeError: (_e: unknown, fallback: string) => fallback,
  listSharedTemplates: vi.fn(),
  createSharedTemplate: vi.fn(),
  updateSharedTemplate: vi.fn(),
  deleteSharedTemplate: vi.fn(),
}));

import {
  createSharedTemplate,
  deleteSharedTemplate,
  listSharedTemplates,
  updateSharedTemplate,
} from "@/lib/api";

const TPL = {
  id: "st1",
  key: "org_ll",
  display_name: "Org Lower Limb",
  version: "1.0",
  owner_id: "admin1",
  is_shared: true,
  template: {
    key: "org_ll",
    display_name: "Org Lower Limb",
    version: "1.0",
    sections: [
      {
        id: "cc",
        title: "CC",
        required: true,
        description: "",
        visual_trigger_keywords: [],
      },
    ],
  },
  created_at: "2026-06-26T00:00:00Z",
  updated_at: "2026-06-26T00:00:00Z",
};

beforeEach(() => {
  vi.mocked(listSharedTemplates).mockResolvedValue([TPL]);
  vi.mocked(createSharedTemplate).mockReset().mockResolvedValue(TPL);
  vi.mocked(updateSharedTemplate).mockReset().mockResolvedValue(TPL);
  vi.mocked(deleteSharedTemplate).mockReset().mockResolvedValue(undefined);
});

describe("SharedTemplatesPage", () => {
  it("lists shared templates", async () => {
    render(withIntl(<SharedTemplatesPage />));
    expect(screen.getByText("Shared templates")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("delete-shared-st1")).toBeInTheDocument(),
    );
    expect(screen.getByText("Org Lower Limb")).toBeInTheDocument();
  });

  it("creates a shared template from the editor", async () => {
    const user = userEvent.setup();
    vi.mocked(listSharedTemplates).mockResolvedValue([]);
    render(withIntl(<SharedTemplatesPage />));

    await user.click(screen.getByTestId("new-shared-template"));
    await user.type(
      screen.getByPlaceholderText("e.g. Lower-limb new patient"),
      "Org LL",
    );
    await user.type(
      screen.getByPlaceholderText("e.g. lower_limb_new_patient"),
      "org_ll",
    );
    await user.type(screen.getByTestId("section-title-0"), "Chief complaint");
    await user.type(screen.getByPlaceholderText("e.g. hpi"), "cc");

    await user.click(screen.getByTestId("save-shared-template"));

    await waitFor(() => expect(createSharedTemplate).toHaveBeenCalledTimes(1));
    const body = vi.mocked(createSharedTemplate).mock.calls[0][0];
    expect(body.key).toBe("org_ll");
    expect(body.display_name).toBe("Org LL");
  });

  it("edits a shared template through the prefilled editor", async () => {
    const user = userEvent.setup();
    render(withIntl(<SharedTemplatesPage />));
    await waitFor(() =>
      expect(screen.getByTestId("edit-shared-st1")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("edit-shared-st1"));
    // Editor opens prefilled with the template's current values.
    const nameInput = screen.getByDisplayValue("Org Lower Limb") as HTMLInputElement;
    await user.clear(nameInput);
    await user.type(nameInput, "Org LL v2");

    await user.click(screen.getByTestId("save-shared-template"));

    await waitFor(() => expect(updateSharedTemplate).toHaveBeenCalledTimes(1));
    const [id, body] = vi.mocked(updateSharedTemplate).mock.calls[0];
    expect(id).toBe("st1");
    expect(body.display_name).toBe("Org LL v2");
    expect(body.key).toBe("org_ll");
    // Edit must not create a new template.
    expect(createSharedTemplate).not.toHaveBeenCalled();
  });

  it("deletes a shared template", async () => {
    const user = userEvent.setup();
    render(withIntl(<SharedTemplatesPage />));
    await waitFor(() =>
      expect(screen.getByTestId("delete-shared-st1")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("delete-shared-st1"));
    await waitFor(() =>
      expect(deleteSharedTemplate).toHaveBeenCalledWith("st1"),
    );
  });
});
