import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import Sidebar from "@/components/Sidebar";
import { withIntl } from "./helpers/intl";

/**
 * Sidebar — CLINICAL_ADMIN nav surface (#578).
 *
 * The elevatable super-user sees the curation items (the unified Library —
 * #579 — and Prompt Studio) but NOT the infra/security items (Feature Flags,
 * AI Providers, Config, Users) — mirroring the backend require_role sets.
 *
 * `getMe` / profile / portal-flags are mocked so the sidebar resolves a user
 * without network, same as SidebarMyActivity.spec.
 */

vi.mock("@/lib/api", () => ({ getMe: vi.fn(), logout: vi.fn() }));
vi.mock("@/lib/portal-api", () => ({
  getMyProfile: vi.fn(),
  getPortalFeatureFlags: vi.fn(() =>
    Promise.resolve({ video_import_enabled: false }),
  ),
}));
vi.mock("next-themes", () => ({
  useTheme: () => ({ setTheme: vi.fn(), theme: "light", resolvedTheme: "light" }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/portal/admin/templates",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

import { getMe } from "@/lib/api";
import { getMyProfile } from "@/lib/portal-api";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getMyProfile).mockResolvedValue({} as never);
  vi.mocked(getMe).mockResolvedValue({
    user_id: "ca1",
    email: "perry@creoq.ca",
    full_name: "Dr Perry",
    role: "CLINICAL_ADMIN",
  });
});

describe("Sidebar — CLINICAL_ADMIN nav surface (#578)", () => {
  it("surfaces the elevatable curation items", async () => {
    render(withIntl(<Sidebar />));
    await waitFor(() =>
      expect(screen.getAllByText("Library").length).toBeGreaterThan(0),
    );
    expect(screen.getAllByText("Prompt Studio").length).toBeGreaterThan(0);
  });

  it("hides the infra / security items", async () => {
    render(withIntl(<Sidebar />));
    // Wait until the nav has resolved (a curation item is present) before
    // asserting absence, so we're not just racing an empty initial render.
    await waitFor(() =>
      expect(screen.getAllByText("Library").length).toBeGreaterThan(0),
    );
    expect(screen.queryByText("Feature Flags")).toBeNull();
    expect(screen.queryByText("AI Providers")).toBeNull();
    expect(screen.queryByText("Config")).toBeNull();
    expect(screen.queryByText("Users")).toBeNull();
  });
});
