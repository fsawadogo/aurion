import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import AdminLibraryPage from "@/app/portal/admin/library/page";
import { withIntl } from "./helpers/intl";

/**
 * /portal/admin/library — the unified admin Library (#579) composes the two
 * existing sections (built-in System Templates + org-custom Shared Templates)
 * into one page, reusing their existing APIs. This verifies both sections
 * render together; the sections' own CRUD behaviour stays covered by
 * AdminTemplatesPage.spec / SharedTemplatesPage.spec (which now render the
 * thin page wrappers over the same components).
 */

vi.mock("@/lib/api", () => ({
  humanizeError: (_e: unknown, fb: string) => fb,
  getAdminTemplates: vi.fn(),
  getAdminTemplateDetail: vi.fn(),
  putAdminTemplate: vi.fn(),
  revertAdminTemplate: vi.fn(),
  listSharedTemplates: vi.fn(),
  createSharedTemplate: vi.fn(),
  updateSharedTemplate: vi.fn(),
  deleteSharedTemplate: vi.fn(),
}));

import { getAdminTemplates, listSharedTemplates } from "@/lib/api";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAdminTemplates).mockResolvedValue({
    items: [
      {
        template_key: "orthopedic_surgery",
        display_name: "Orthopedic Surgery",
        version: "1.0",
        section_count: 6,
        is_override: false,
      },
    ],
  } as never);
  vi.mocked(listSharedTemplates).mockResolvedValue([
    {
      id: "11111111-1111-1111-1111-111111111111",
      key: "org_knee",
      display_name: "Org Knee Protocol",
      version: "1.0",
      owner_id: "admin1",
      is_shared: true,
      template: {
        key: "org_knee",
        display_name: "Org Knee Protocol",
        version: "1.0",
        sections: [],
      },
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:00:00Z",
    },
  ] as never);
});

describe("AdminLibraryPage — unified Library (#579)", () => {
  it("renders both sections (built-in + org-custom) in one page", async () => {
    render(withIntl(<AdminLibraryPage />));

    // Both section data sources are fetched on mount.
    await waitFor(() => expect(getAdminTemplates).toHaveBeenCalled());
    expect(listSharedTemplates).toHaveBeenCalled();

    // Built-in section renders its bundled template.
    await waitFor(() =>
      expect(screen.getByText("Orthopedic Surgery")).toBeTruthy(),
    );
    // Org-custom section renders its shared template + the New action.
    expect(screen.getByText("Org Knee Protocol")).toBeTruthy();
    expect(screen.getByTestId("new-shared-template")).toBeTruthy();

    // Both sections live under the one Library page.
    expect(screen.getByTestId("admin-library-page")).toBeTruthy();
    expect(screen.getByTestId("admin-templates-section")).toBeTruthy();
    expect(screen.getByTestId("shared-templates-section")).toBeTruthy();
  });
});
