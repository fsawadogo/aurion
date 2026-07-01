import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import { withIntl } from "./helpers/intl";

/**
 * Templates → "Visit Types" tab (the admin org-default layer of the visit-type
 * → template map). Admins get a per-visit-type template selector that writes the
 * org default; non-admins get a read-only note (the org GET is admin-gated) and
 * the org list is never fetched.
 */

vi.mock("@/lib/api", () => ({
  getMe: vi.fn(),
  humanizeError: (_e: unknown, fb: string) => fb,
  listOrgVisitTypeTemplates: vi.fn(),
  setOrgVisitTypeTemplate: vi.fn(),
  clearOrgVisitTypeTemplate: vi.fn(),
}));
vi.mock("@/lib/portal-api", () => ({
  getMyProfile: vi.fn(),
  listMyCustomTemplates: vi.fn(),
  updateMyProfile: vi.fn(),
}));
vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => children,
}));
// Keep the real i18n keys but avoid pulling the full editor component tree.
vi.mock("@/components/portal/VisitTypeContextsEditor", () => ({
  BUILT_IN_TEMPLATE_KEYS: ["general", "orthopedic_surgery", "plastic_surgery"],
  newContextId: () => "ctx_test1234",
}));

import {
  clearOrgVisitTypeTemplate,
  getMe,
  listOrgVisitTypeTemplates,
  setOrgVisitTypeTemplate,
} from "@/lib/api";
import {
  getMyProfile,
  listMyCustomTemplates,
  updateMyProfile,
} from "@/lib/portal-api";
import VisitTypesTab from "@/components/portal/VisitTypesTab";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getMyProfile).mockResolvedValue({
    consultation_types: ["follow_up", "pre_op"],
    contexts_per_visit_type: {},
  } as never);
  vi.mocked(updateMyProfile).mockResolvedValue({} as never);
  vi.mocked(listMyCustomTemplates).mockResolvedValue([
    { id: "c1", display_name: "Ortho FU", is_shared: true },
    { id: "c2", display_name: "Private one", is_shared: false },
  ] as never);
  vi.mocked(listOrgVisitTypeTemplates).mockResolvedValue([
    {
      visit_type: "follow_up",
      template_key: "orthopedic_surgery",
      custom_template_id: null,
      updated_at: null,
    },
  ] as never);
  vi.mocked(setOrgVisitTypeTemplate).mockResolvedValue({
    visit_type: "follow_up",
    template_key: null,
    custom_template_id: "c1",
    updated_at: null,
  } as never);
});

describe("VisitTypesTab", () => {
  it("admin: shows per-visit-type selectors reflecting the org default", async () => {
    vi.mocked(getMe).mockResolvedValue({ role: "ADMIN" } as never);
    render(withIntl(<VisitTypesTab />));

    const sel = (await screen.findByTestId(
      "visit-type-template-follow_up",
    )) as HTMLSelectElement;
    // Reflects the existing org default (built-in orthopedic_surgery).
    expect(sel.value).toBe("builtin:orthopedic_surgery");
    // A private (non-shared) custom template is NOT offered as an org option.
    expect(screen.queryByText("Private one")).toBeNull();
    // Both configured visit types render.
    expect(screen.getByTestId("visit-type-template-pre_op")).toBeTruthy();
  });

  it("admin: changing the selector writes the org default", async () => {
    vi.mocked(getMe).mockResolvedValue({ role: "ADMIN" } as never);
    render(withIntl(<VisitTypesTab />));
    const sel = await screen.findByTestId("visit-type-template-follow_up");

    fireEvent.change(sel, { target: { value: "custom:c1" } });
    await waitFor(() =>
      expect(setOrgVisitTypeTemplate).toHaveBeenCalledWith("follow_up", {
        custom_template_id: "c1",
      }),
    );
  });

  it("clinician: sets their own per-visit default via an is_default context; never fetches org defaults", async () => {
    vi.mocked(getMe).mockResolvedValue({ role: "CLINICIAN" } as never);
    render(withIntl(<VisitTypesTab />));

    const sel = await screen.findByTestId("visit-type-template-follow_up");
    fireEvent.change(sel, { target: { value: "custom:c1" } });

    await waitFor(() => expect(updateMyProfile).toHaveBeenCalled());
    const arg = vi.mocked(updateMyProfile).mock.calls.at(-1)![0] as {
      contexts_per_visit_type: Record<
        string,
        { is_default?: boolean; template_ref: string | null }[]
      >;
    };
    const def = arg.contexts_per_visit_type.follow_up.find((c) => c.is_default);
    expect(def?.template_ref).toBe("c1");
    // A clinician never hits the admin-gated org endpoint.
    expect(listOrgVisitTypeTemplates).not.toHaveBeenCalled();
  });

  it("admin: selecting the specialty default clears the org default", async () => {
    vi.mocked(getMe).mockResolvedValue({ role: "ADMIN" } as never);
    render(withIntl(<VisitTypesTab />));
    const sel = await screen.findByTestId("visit-type-template-follow_up");

    fireEvent.change(sel, { target: { value: "" } });
    await waitFor(() =>
      expect(clearOrgVisitTypeTemplate).toHaveBeenCalledWith("follow_up"),
    );
  });

  it("shows a retryable error (not the clinician note) when the load fails", async () => {
    vi.mocked(getMe).mockResolvedValue({ role: "ADMIN" } as never);
    vi.mocked(getMyProfile).mockRejectedValueOnce(new Error("boom"));
    render(withIntl(<VisitTypesTab />));

    await waitFor(() =>
      expect(screen.getByText("Failed to load visit types.")).toBeTruthy(),
    );
    expect(
      screen.queryByText("Org visit-type defaults are set by your admin."),
    ).toBeNull();
  });
});
