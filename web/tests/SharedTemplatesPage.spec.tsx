import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SharedTemplatesPage from "@/app/portal/admin/shared-templates/page";
import { withIntl } from "./helpers/intl";

vi.mock("@/lib/api", () => ({
  humanizeError: (_e: unknown, fallback: string) => fallback,
  listSharedTemplates: vi.fn(),
  createSharedTemplate: vi.fn(),
  deleteSharedTemplate: vi.fn(),
}));

import {
  createSharedTemplate,
  deleteSharedTemplate,
  listSharedTemplates,
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
    sections: [],
  },
  created_at: "2026-06-26T00:00:00Z",
  updated_at: "2026-06-26T00:00:00Z",
};

beforeEach(() => {
  vi.mocked(listSharedTemplates).mockResolvedValue([TPL]);
  vi.mocked(createSharedTemplate).mockReset().mockResolvedValue(TPL);
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
