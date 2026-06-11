import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { withIntl } from "./helpers/intl";

/**
 * #397/OV-5: the Users page Require-MFA toggle calls updateUser with
 * mfa_required and reflects the current state in its label.
 */

vi.mock("@/lib/api", () => ({
  getUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

// Header pulls in auth context we don't need for this unit; stub it.
vi.mock("@/components/Header", () => ({
  default: ({ title }: { title: string }) => <div>{title}</div>,
}));

import UsersPage from "@/app/users/page";
import { getUsers, updateUser } from "@/lib/api";

function user(over: Record<string, unknown> = {}) {
  return {
    id: "u-1",
    email: "marie@aurionclinical.com",
    full_name: "Dr Marie",
    role: "CLINICIAN",
    is_active: true,
    voice_enrolled: false,
    mfa_required: false,
    mfa_enrolled: false,
    created_at: new Date().toISOString(),
    last_login_at: null,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getUsers).mockResolvedValue([user()] as never);
  vi.mocked(updateUser).mockResolvedValue(user({ mfa_required: true }) as never);
});

describe("UsersPage — Require MFA toggle (#397)", () => {
  it("shows the current MFA state and toggles it on", async () => {
    render(withIntl(<UsersPage />));

    await waitFor(() => expect(screen.getByTestId("mfa-toggle-u-1")).toBeInTheDocument());
    const toggle = screen.getByTestId("mfa-toggle-u-1");
    expect(toggle).toHaveTextContent("MFA: optional"); // mfa_required=false

    fireEvent.click(toggle);
    await waitFor(() =>
      expect(updateUser).toHaveBeenCalledWith("u-1", { mfa_required: true }),
    );
  });

  it("toggles back off when already required", async () => {
    vi.mocked(getUsers).mockResolvedValue([user({ mfa_required: true })] as never);
    render(withIntl(<UsersPage />));

    await waitFor(() => expect(screen.getByTestId("mfa-toggle-u-1")).toHaveTextContent("MFA: required"));
    fireEvent.click(screen.getByTestId("mfa-toggle-u-1"));
    await waitFor(() =>
      expect(updateUser).toHaveBeenCalledWith("u-1", { mfa_required: false }),
    );
  });
});
