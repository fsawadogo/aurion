import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import PortalTemplatesPage from "@/app/portal/templates/page";
import { withIntl } from "./helpers/intl";

/**
 * /portal/templates — tabbed split (My Templates / Library), ownership gating,
 * and the delete confirmation modal.
 *
 * The list can include shared templates owned by others; the tabs are a disjoint
 * split on `is_shared` and only the active tab's list is mounted. Delete is
 * owner-only (the backend DELETE is owner-scoped → 404). These verify the tab
 * separation, that Delete shows for owned rows only, the fork-to-mine flow, and
 * that deleting goes through the house Modal rather than a native confirm().
 */

vi.mock("@/lib/api", () => ({
  getMe: vi.fn(),
  humanizeError: (_e: unknown, fb: string) => fb,
}));
vi.mock("@/lib/portal-api", () => ({
  listMyCustomTemplates: vi.fn(),
  deleteMyCustomTemplate: vi.fn(),
  duplicateMyCustomTemplate: vi.fn(),
  uploadTemplateDocument: vi.fn(),
}));
vi.mock("@/lib/session-format", () => ({ formatRelative: () => "today" }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => children,
}));

import { getMe } from "@/lib/api";
import {
  listMyCustomTemplates,
  deleteMyCustomTemplate,
  duplicateMyCustomTemplate,
} from "@/lib/portal-api";

function tpl(id: string, name: string, ownerId: string, shared = false) {
  return {
    id,
    key: id,
    display_name: name,
    version: "1.0",
    owner_id: ownerId,
    is_shared: shared,
    template: { key: id, display_name: name, version: "1.0", sections: [] },
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getMe).mockResolvedValue({
    user_id: "me",
    email: "me@x.com",
    full_name: "Me",
    role: "CLINICIAN",
  } as never);
  vi.mocked(listMyCustomTemplates).mockResolvedValue([
    tpl("mine", "My Template", "me"),
    tpl("theirs", "Shared Template", "other", true),
  ] as never);
  vi.mocked(deleteMyCustomTemplate).mockResolvedValue(undefined as never);
  vi.mocked(duplicateMyCustomTemplate).mockResolvedValue(
    tpl("mine-copy", "Shared Template (copy)", "me") as never,
  );
});

describe("PortalTemplatesPage — ownership gating + delete modal", () => {
  it("shows Delete only for owned rows", async () => {
    render(withIntl(<PortalTemplatesPage />));
    // My Templates is the default tab: the owned row's Delete renders.
    await waitFor(() =>
      expect(screen.getByLabelText("Delete My Template")).toBeTruthy(),
    );
    // The shared (non-owned) row lives in the Library tab and has no Delete.
    fireEvent.click(screen.getByTestId("templates-tab-library"));
    expect(screen.getByText("Shared Template")).toBeTruthy();
    expect(screen.queryByLabelText("Delete Shared Template")).toBeNull();
  });

  it("deletes through the modal (not a native confirm)", async () => {
    render(withIntl(<PortalTemplatesPage />));
    await waitFor(() => screen.getByLabelText("Delete My Template"));

    fireEvent.click(screen.getByLabelText("Delete My Template"));
    // Modal title appears.
    await waitFor(() => expect(screen.getByText("Delete template")).toBeTruthy());
    // Confirm button (destructive) in the modal footer.
    const confirmBtn = screen
      .getAllByRole("button", { name: "Delete" })
      .at(-1) as HTMLButtonElement;
    fireEvent.click(confirmBtn);
    await waitFor(() =>
      expect(deleteMyCustomTemplate).toHaveBeenCalledWith("mine"),
    );
  });
});

describe("PortalTemplatesPage — tabbed My Templates / Library split + fork", () => {
  it("separates owned and shared templates across the two tabs", async () => {
    render(withIntl(<PortalTemplatesPage />));
    // My Templates tab (default): owned row has Open, and no fork control here.
    await waitFor(() =>
      expect(screen.getByLabelText("Delete My Template")).toBeTruthy(),
    );
    expect(screen.getAllByText("Open").length).toBe(1);
    expect(
      screen.queryByRole("button", { name: "Save to My Templates" }),
    ).toBeNull();
    // Library tab: shared row has the fork button, and no Open control.
    fireEvent.click(screen.getByTestId("templates-tab-library"));
    expect(
      screen.getByRole("button", { name: "Save to My Templates" }),
    ).toBeTruthy();
    expect(screen.queryByText("Open")).toBeNull();
  });

  it("forks a Library row and the copy lands under My Templates", async () => {
    // First load: one owned + one shared. After the fork, the reload returns
    // the owned copy too (is_shared=false → owned → has a Delete control).
    vi.mocked(listMyCustomTemplates)
      .mockReset()
      .mockResolvedValueOnce([
        tpl("mine", "My Template", "me"),
        tpl("theirs", "Shared Template", "other", true),
      ] as never)
      .mockResolvedValueOnce([
        tpl("mine", "My Template", "me"),
        tpl("mine-copy", "Shared Template (copy)", "me"),
        tpl("theirs", "Shared Template", "other", true),
      ] as never);

    render(withIntl(<PortalTemplatesPage />));
    // Fork happens from the Library tab.
    fireEvent.click(await screen.findByTestId("templates-tab-library"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Save to My Templates" }),
    );

    await waitFor(() =>
      expect(duplicateMyCustomTemplate).toHaveBeenCalledWith("theirs"),
    );
    // Back on My Templates, the fork now shows as an owned row (has Delete).
    fireEvent.click(screen.getByTestId("templates-tab-mine"));
    await waitFor(() =>
      expect(
        screen.getByLabelText("Delete Shared Template (copy)"),
      ).toBeTruthy(),
    );
    expect(listMyCustomTemplates).toHaveBeenCalledTimes(2);
  });

  it("surfaces a friendly error when the fork fails", async () => {
    vi.mocked(duplicateMyCustomTemplate).mockRejectedValueOnce(
      new Error("boom"),
    );
    render(withIntl(<PortalTemplatesPage />));
    fireEvent.click(await screen.findByTestId("templates-tab-library"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Save to My Templates" }),
    );
    await waitFor(() =>
      expect(screen.getByText("Couldn't copy the template.")).toBeTruthy(),
    );
  });
});
