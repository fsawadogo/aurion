import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ForgotPasswordPage from "@/app/(auth)/forgot-password/page";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import { withIntl } from "./helpers/intl";

/**
 * AUTH-EMAIL-RESET-WIRING — forgot-password page regression suite.
 *
 * Critical property: account-existence neutrality. The backend
 * returns 204 in both branches (account found / not found); the
 * page must mirror that. Tests prove that even when the API mock
 * rejects with a 4xx-shaped error, the user still sees the same
 * "Check your inbox" confirmation — never a different message.
 *
 * Transport-level errors (network down / 5xx) DO surface; those
 * aren't enumeration channels.
 */

vi.mock("@/lib/api", () => ({
  requestPasswordReset: vi.fn(),
}));

import { requestPasswordReset } from "@/lib/api";

beforeEach(() => {
  vi.mocked(requestPasswordReset).mockReset();
});

describe("ForgotPasswordPage — form state + submit", () => {
  it("disables the submit button when the email field is empty", async () => {
    render(withIntl(<ForgotPasswordPage />));
    const submit = await screen.findByRole("button", {
      name: enMessages.Auth.forgotPassword.submit,
    });
    expect(submit).toBeDisabled();
    expect(requestPasswordReset).not.toHaveBeenCalled();
  });

  it("POSTs the lowercased email when the form submits successfully", async () => {
    const user = userEvent.setup();
    vi.mocked(requestPasswordReset).mockResolvedValue(undefined);
    render(withIntl(<ForgotPasswordPage />));

    const input = await screen.findByTestId("forgot-password-email-input");
    await user.type(input, "Perry@CREOQ.CA");

    const submit = screen.getByRole("button", {
      name: enMessages.Auth.forgotPassword.submit,
    });
    await user.click(submit);

    await waitFor(() => {
      expect(requestPasswordReset).toHaveBeenCalledWith("perry@creoq.ca");
    });
    // Success → confirmation panel appears.
    expect(
      screen.getByTestId("forgot-password-confirmation"),
    ).toBeInTheDocument();
  });

  it("shows the SAME confirmation panel even when the API throws a 4xx-shaped error (account-existence neutral)", async () => {
    const user = userEvent.setup();
    vi.mocked(requestPasswordReset).mockRejectedValue(
      new Error("Forgot-password request failed: 400"),
    );
    render(withIntl(<ForgotPasswordPage />));

    const input = await screen.findByTestId("forgot-password-email-input");
    await user.type(input, "unknown@example.com");

    const submit = screen.getByRole("button", {
      name: enMessages.Auth.forgotPassword.submit,
    });
    await user.click(submit);

    await waitFor(() => {
      expect(
        screen.getByTestId("forgot-password-confirmation"),
      ).toBeInTheDocument();
    });
    // The confirmation copy is the SAME as the success branch. If
    // this ever diverges, the page is leaking account existence.
    expect(
      screen.getByText(enMessages.Auth.forgotPassword.confirmationBody),
    ).toBeInTheDocument();
    // Transport-error banner MUST NOT render in the 4xx branch — it's
    // reserved for genuine transport-level failures.
    expect(
      screen.queryByTestId("forgot-password-transport-error"),
    ).not.toBeInTheDocument();
  });

  it("surfaces a transport-level error banner on network failure", async () => {
    const user = userEvent.setup();
    vi.mocked(requestPasswordReset).mockRejectedValue(
      new Error("Failed to fetch"),
    );
    render(withIntl(<ForgotPasswordPage />));

    const input = await screen.findByTestId("forgot-password-email-input");
    await user.type(input, "perry@creoq.ca");

    const submit = screen.getByRole("button", {
      name: enMessages.Auth.forgotPassword.submit,
    });
    await user.click(submit);

    await waitFor(() => {
      expect(
        screen.getByTestId("forgot-password-transport-error"),
      ).toBeInTheDocument();
    });
    // The confirmation panel should NOT render — the user needs to
    // retry, not assume success.
    expect(
      screen.queryByTestId("forgot-password-confirmation"),
    ).not.toBeInTheDocument();
  });
});

describe("ForgotPasswordPage — i18n parity", () => {
  it("EN catalog contains Auth.forgotPassword", () => {
    expect(enMessages).toHaveProperty("Auth.forgotPassword");
  });

  it("FR catalog contains Auth.forgotPassword", () => {
    expect(frMessages).toHaveProperty("Auth.forgotPassword");
  });

  it("renders the FR locale without crashing", async () => {
    render(withIntl(<ForgotPasswordPage />, "fr"));
    await waitFor(() => {
      expect(
        screen.getByTestId("forgot-password-email-input"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(frMessages.Auth.forgotPassword.title),
    ).toBeInTheDocument();
  });
});
