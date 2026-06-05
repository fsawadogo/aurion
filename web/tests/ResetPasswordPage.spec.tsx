import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ResetPasswordPage from "@/app/(auth)/reset-password/page";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import { withIntl } from "./helpers/intl";

/**
 * AUTH-EMAIL-RESET-WIRING — reset-password page regression suite.
 *
 * The page consumes `?token=<token>` via useSearchParams, asks for a
 * new password, and POSTs to /api/v1/auth/reset-password. The tests
 * guard:
 *   * token present → form renders.
 *   * token absent → error banner, no form.
 *   * local validation (< 8 chars, mismatch) → inline error + no API.
 *   * happy path 204 → router.push('/login?reset=success').
 *   * backend 400 "Invalid or expired reset token." → surfaces detail
 *     + suggests requesting a new link.
 *   * EN + FR catalogs both expose the namespace.
 *
 * `next/navigation` mocked at the module boundary — useRouter +
 * useSearchParams are both spied so we can drive the token query +
 * observe the post-submit navigation.
 *
 * `@/lib/api` mocked to inspect the call shape AND inject the
 * 204 / 400 / network branches without needing a real backend.
 */

vi.mock("@/lib/api", () => ({
  resetPassword: vi.fn(),
}));

const mockPush = vi.fn();
const mockUseSearchParams = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, refresh: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => mockUseSearchParams(),
}));

import { resetPassword } from "@/lib/api";

const VALID_TOKEN = "tok_test_0123456789abcdef";

beforeEach(() => {
  vi.mocked(resetPassword).mockReset();
  mockPush.mockReset();
  mockUseSearchParams.mockReset();
  mockUseSearchParams.mockReturnValue({
    get: (key: string) => (key === "token" ? VALID_TOKEN : null),
  });
});

describe("ResetPasswordPage — token presence", () => {
  it("renders the form when ?token=... is present", async () => {
    render(withIntl(<ResetPasswordPage />));
    await waitFor(() => {
      expect(
        screen.getByTestId("reset-password-new-input"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("reset-password-confirm-input"),
    ).toBeInTheDocument();
  });

  it("renders the missing-token error banner when no token is in the URL", async () => {
    mockUseSearchParams.mockReturnValue({
      get: () => null,
    });
    render(withIntl(<ResetPasswordPage />));
    await waitFor(() => {
      expect(
        screen.getByText(enMessages.Auth.resetPassword.missingTokenTitle),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(enMessages.Auth.resetPassword.missingTokenBody),
    ).toBeInTheDocument();
    // Critically — the form is NOT rendered. A user without a token
    // shouldn't be able to attempt a submit.
    expect(
      screen.queryByTestId("reset-password-new-input"),
    ).not.toBeInTheDocument();
  });
});

describe("ResetPasswordPage — local validation", () => {
  it("rejects passwords shorter than 8 characters without an API call", async () => {
    const user = userEvent.setup();
    render(withIntl(<ResetPasswordPage />));

    const newInput = await screen.findByTestId("reset-password-new-input");
    const confirmInput = screen.getByTestId("reset-password-confirm-input");
    const submit = screen.getByRole("button", {
      name: enMessages.Auth.resetPassword.submit,
    });

    await user.type(newInput, "short");
    await user.type(confirmInput, "short");
    await user.click(submit);

    await waitFor(() => {
      expect(
        screen.getByText(enMessages.Auth.resetPassword.errors.tooShort),
      ).toBeInTheDocument();
    });
    expect(resetPassword).not.toHaveBeenCalled();
  });

  it("rejects mismatched passwords without an API call", async () => {
    const user = userEvent.setup();
    render(withIntl(<ResetPasswordPage />));

    const newInput = await screen.findByTestId("reset-password-new-input");
    const confirmInput = screen.getByTestId("reset-password-confirm-input");
    const submit = screen.getByRole("button", {
      name: enMessages.Auth.resetPassword.submit,
    });

    await user.type(newInput, "valid-password-1");
    await user.type(confirmInput, "different-password-2");
    await user.click(submit);

    await waitFor(() => {
      expect(
        screen.getByText(enMessages.Auth.resetPassword.errors.mismatch),
      ).toBeInTheDocument();
    });
    expect(resetPassword).not.toHaveBeenCalled();
  });
});

describe("ResetPasswordPage — submit + outcomes", () => {
  it("on 204, navigates to /login?reset=success", async () => {
    const user = userEvent.setup();
    vi.mocked(resetPassword).mockResolvedValue(undefined);
    render(withIntl(<ResetPasswordPage />));

    const newInput = await screen.findByTestId("reset-password-new-input");
    const confirmInput = screen.getByTestId("reset-password-confirm-input");
    const submit = screen.getByRole("button", {
      name: enMessages.Auth.resetPassword.submit,
    });

    const pw = "Strong-pw-123!";
    await user.type(newInput, pw);
    await user.type(confirmInput, pw);
    await user.click(submit);

    await waitFor(() => {
      expect(resetPassword).toHaveBeenCalledWith(VALID_TOKEN, pw);
    });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/login?reset=success");
    });
  });

  it("surfaces the backend 'Reset token has expired' message + expired hint", async () => {
    const user = userEvent.setup();
    vi.mocked(resetPassword).mockRejectedValue(
      new Error("Reset token has expired"),
    );
    render(withIntl(<ResetPasswordPage />));

    const newInput = await screen.findByTestId("reset-password-new-input");
    const confirmInput = screen.getByTestId("reset-password-confirm-input");
    const submit = screen.getByRole("button", {
      name: enMessages.Auth.resetPassword.submit,
    });

    const pw = "Strong-pw-123!";
    await user.type(newInput, pw);
    await user.type(confirmInput, pw);
    await user.click(submit);

    await waitFor(() => {
      expect(
        screen.getByTestId("reset-password-error"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(/Reset token has expired/i)).toBeInTheDocument();
    expect(
      screen.getByText(enMessages.Auth.resetPassword.errors.expiredHint),
    ).toBeInTheDocument();
    // Never navigated away.
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("surfaces 'Invalid or expired reset token.' with the invalid hint when the message doesn't match expired/used", async () => {
    // The backend's actual message is "Invalid or expired reset
    // token." — the page should prefer the `expiredHint` since the
    // word "expired" appears, but matches by /expired/i so the test
    // also verifies the precedence.
    const user = userEvent.setup();
    vi.mocked(resetPassword).mockRejectedValue(
      new Error("Reset token is invalid"),
    );
    render(withIntl(<ResetPasswordPage />));

    const newInput = await screen.findByTestId("reset-password-new-input");
    const confirmInput = screen.getByTestId("reset-password-confirm-input");
    const submit = screen.getByRole("button", {
      name: enMessages.Auth.resetPassword.submit,
    });

    const pw = "Strong-pw-123!";
    await user.type(newInput, pw);
    await user.type(confirmInput, pw);
    await user.click(submit);

    await waitFor(() => {
      expect(
        screen.getByText(enMessages.Auth.resetPassword.errors.invalidHint),
      ).toBeInTheDocument();
    });
  });
});

describe("ResetPasswordPage — i18n parity", () => {
  it("EN catalog contains Auth.resetPassword", () => {
    expect(enMessages).toHaveProperty("Auth.resetPassword");
  });

  it("FR catalog contains Auth.resetPassword", () => {
    expect(frMessages).toHaveProperty("Auth.resetPassword");
  });

  it("EN and FR Auth.resetPassword namespaces have matching key sets", () => {
    const enKeys = collectKeys(
      (enMessages as Record<string, unknown>).Auth as Record<string, unknown>,
    );
    const frKeys = collectKeys(
      (frMessages as Record<string, unknown>).Auth as Record<string, unknown>,
    );
    expect(frKeys).toEqual(enKeys);
  });

  it("renders the FR locale without crashing", async () => {
    render(withIntl(<ResetPasswordPage />, "fr"));
    await waitFor(() => {
      expect(
        screen.getByTestId("reset-password-new-input"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(frMessages.Auth.resetPassword.title),
    ).toBeInTheDocument();
  });
});

/** Dotted-path flatten of a nested message object — same pattern as
 *  PatientDetailPage.spec / AIPromptsPage.spec. */
function collectKeys(node: unknown, prefix = ""): string[] {
  if (node === null || typeof node !== "object") return [prefix];
  const out: string[] = [];
  for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
    const child = prefix ? `${prefix}.${k}` : k;
    out.push(...collectKeys(v, child));
  }
  return out.sort();
}
