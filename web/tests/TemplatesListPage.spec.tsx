import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import PortalTemplatesPage from "@/app/portal/templates/page";
import { withIntl } from "./helpers/intl";

/**
 * /portal/templates — ownership gating + delete confirmation modal.
 *
 * The list can include shared templates owned by others; Delete is owner-only
 * (the backend DELETE is owner-scoped → 404). Verifies the Delete control
 * shows for owned rows, is hidden for non-owned, and that deleting goes
 * through the house Modal rather than a native confirm().
 */

vi.mock("@/lib/api", () => ({
  getMe: vi.fn(),
  humanizeError: (_e: unknown, fb: string) => fb,
}));
vi.mock("@/lib/portal-api", () => ({
  listMyCustomTemplates: vi.fn(),
  deleteMyCustomTemplate: vi.fn(),
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
});

describe("PortalTemplatesPage — ownership gating + delete modal", () => {
  it("shows Delete only for owned rows", async () => {
    render(withIntl(<PortalTemplatesPage />));
    await waitFor(() => expect(screen.getByText("My Template")).toBeTruthy());
    expect(screen.getByText("Shared Template")).toBeTruthy();
    // Owned row has a Delete control; the shared (non-owned) row does not.
    expect(screen.queryByLabelText("Delete My Template")).toBeTruthy();
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
