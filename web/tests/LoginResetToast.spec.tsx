import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import enMessages from "@/messages/en.json";
import { withIntl } from "./helpers/intl";

/**
 * AUTH-EMAIL-RESET-WIRING — login-page reset-success toast.
 *
 * The reset-password page bounces back to /login?reset=success after
 * a successful password change. The login page reads the query
 * param and shows a green toast above the brand lockup; the toast
 * auto-dismisses after 5 seconds via setTimeout.
 *
 * Mocks @/lib/api (the only auth dependency now that the portal is on
 * backend bcrypt-JWT) so the toast test never touches the real sign-in
 * path; it only cares about the URL flag.
 */

vi.mock("@/lib/api", () => ({
  login: vi.fn(),
  verifyMfaLogin: vi.fn(),
}));

const mockUseSearchParams = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => mockUseSearchParams(),
}));

beforeEach(() => {
  mockUseSearchParams.mockReset();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("LoginResetToast — visibility", () => {
  it("renders the toast when ?reset=success is on the URL", async () => {
    mockUseSearchParams.mockReturnValue({
      get: (key: string) => (key === "reset" ? "success" : null),
    });
    render(withIntl(<LoginPage />));

    await waitFor(() => {
      expect(
        screen.getByTestId("login-reset-success-toast"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(enMessages.Auth.loginToast.resetSuccess),
    ).toBeInTheDocument();
  });

  it("does NOT render the toast on a plain /login (no query)", async () => {
    mockUseSearchParams.mockReturnValue({
      get: () => null,
    });
    render(withIntl(<LoginPage />));

    // Wait for the page to settle (Suspense + LocaleProvider hydration)
    // then assert the toast is absent.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Sign in/i }),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByTestId("login-reset-success-toast"),
    ).not.toBeInTheDocument();
  });

  it("auto-dismisses after 5 seconds", async () => {
    mockUseSearchParams.mockReturnValue({
      get: (key: string) => (key === "reset" ? "success" : null),
    });
    render(withIntl(<LoginPage />));

    await waitFor(() => {
      expect(
        screen.getByTestId("login-reset-success-toast"),
      ).toBeInTheDocument();
    });

    // Advance past the 5-second auto-dismiss window. Use act-aware
    // timer advancement so React state updates flush.
    await vi.advanceTimersByTimeAsync(5_100);

    await waitFor(() => {
      expect(
        screen.queryByTestId("login-reset-success-toast"),
      ).not.toBeInTheDocument();
    });
  });
});

describe("LoginResetToast — forgot-password link", () => {
  it("renders the 'Forgot password?' link pointing at /forgot-password", async () => {
    mockUseSearchParams.mockReturnValue({ get: () => null });
    render(withIntl(<LoginPage />));

    const link = await screen.findByTestId("login-forgot-password-link");
    expect(link.getAttribute("href")).toBe("/forgot-password");
  });
});
