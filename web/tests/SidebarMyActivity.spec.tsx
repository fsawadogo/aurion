import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import Sidebar from "@/components/Sidebar";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { withIntl } from "./helpers/intl";

/**
 * Sidebar — "My Activity" nav entry (issue #162, AC-6 + AC-8).
 *
 * Verifies the new entry shows for CLINICIAN + ADMIN roles and that
 * the i18n catalogs both carry the `Sidebar.nav.myActivity` key.
 *
 * `getMe` is mocked so the sidebar resolves a current user without a
 * network round-trip. Profile fetch (theme + locale sync) is mocked
 * to a no-op for the same reason.
 */

vi.mock("@/lib/api", () => ({
  getMe: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("@/lib/portal-api", () => ({
  getMyProfile: vi.fn(),
}));

// Sidebar pulls in `next-themes`; default the hook to a no-op
// implementation so we don't have to mount a `ThemeProvider`.
vi.mock("next-themes", () => ({
  useTheme: () => ({
    setTheme: vi.fn(),
    theme: "light",
    resolvedTheme: "light",
  }),
}));

// `usePathname` returns null when there's no Next router in the
// jsdom tree; we stub it so the sidebar's active-link logic doesn't
// throw. `useRouter` is consumed by LocaleSwitcher which the sidebar
// mounts for clinicians — return a no-op router so it doesn't crash.
vi.mock("next/navigation", () => ({
  usePathname: () => "/portal/dashboard",
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
});

describe("Sidebar — My Activity nav entry (AC-6)", () => {
  it("renders the entry for the CLINICIAN role", async () => {
    vi.mocked(getMe).mockResolvedValue({
      user_id: "u1",
      email: "clinician@aurionclinical.com",
      full_name: "Test Clinician",
      role: "CLINICIAN",
    });

    render(withIntl(<Sidebar />));

    await waitFor(() => {
      // There are TWO matches: mobile + desktop sidebar render the
      // same nav, so the entry shows up twice in the DOM tree.
      expect(screen.getAllByText("My Activity").length).toBeGreaterThan(0);
    });

    // The entry links to /portal/audit.
    const links = screen
      .getAllByRole("link", { name: /My Activity/ })
      .filter((el): el is HTMLAnchorElement => el instanceof HTMLAnchorElement);
    expect(links.length).toBeGreaterThan(0);
    for (const a of links) {
      expect(a.getAttribute("href")).toBe("/portal/audit");
    }
  });

  it("renders the entry for the ADMIN role (preview mode)", async () => {
    vi.mocked(getMe).mockResolvedValue({
      user_id: "u2",
      email: "admin@aurionclinical.com",
      full_name: "Test Admin",
      role: "ADMIN",
    });

    render(withIntl(<Sidebar />));

    await waitFor(() => {
      expect(screen.getAllByText("My Activity").length).toBeGreaterThan(0);
    });
  });

  it("does NOT render the entry for COMPLIANCE_OFFICER (admin /audit covers that role)", async () => {
    vi.mocked(getMe).mockResolvedValue({
      user_id: "u3",
      email: "compliance@aurionclinical.com",
      full_name: "Test Compliance",
      role: "COMPLIANCE_OFFICER",
    });

    render(withIntl(<Sidebar />));

    await waitFor(() => {
      // "Audit Log" (admin route) is visible, but "My Activity" is
      // not — compliance officers see the full audit at /audit.
      expect(screen.getAllByText("Audit Log").length).toBeGreaterThan(0);
    });
    expect(screen.queryByText("My Activity")).toBeNull();
  });
});

describe("Sidebar.nav.myActivity — i18n parity (AC-8)", () => {
  it("EN catalog carries Sidebar.nav.myActivity", () => {
    expect(enMessages.Sidebar.nav.myActivity).toBeDefined();
    expect(typeof enMessages.Sidebar.nav.myActivity).toBe("string");
  });

  it("FR catalog carries Sidebar.nav.myActivity", () => {
    expect(frMessages.Sidebar.nav.myActivity).toBeDefined();
    expect(typeof frMessages.Sidebar.nav.myActivity).toBe("string");
  });

  it("renders 'Mon activité' in FR locale", async () => {
    vi.mocked(getMe).mockResolvedValue({
      user_id: "u_fr",
      email: "clinician.fr@aurionclinical.com",
      full_name: "Clinicien Test",
      role: "CLINICIAN",
    });

    render(withIntl(<Sidebar />, "fr"));
    await waitFor(() => {
      expect(screen.getAllByText("Mon activité").length).toBeGreaterThan(0);
    });
  });
});
