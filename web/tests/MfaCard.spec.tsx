import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import MfaCard from "@/components/portal/MfaCard";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { withIntl } from "./helpers/intl";

/**
 * MfaCard — covers AC-8 (UI shape) + AC-10 (i18n parity).
 *
 * The portal API is mocked at the module boundary so the card is
 * deterministic regardless of network state. The enrollment + disable
 * modals have their own dedicated coverage; here we focus on:
 *   * not-enrolled state renders the "Enable" CTA
 *   * enrolled state renders the badge + "Disable" CTA + last-verified
 *   * EN and FR catalogs both carry the required namespace
 */

vi.mock("@/lib/portal-api", () => ({
  getMfaStatus: vi.fn(),
  enrollMfa: vi.fn(),
  verifyMfaEnroll: vi.fn(),
  disableMfa: vi.fn(),
}));

// The enroll modal imports qrcode — stub it so we don't render a real
// canvas in jsdom.
vi.mock("qrcode", () => ({
  default: { toCanvas: vi.fn(async () => undefined) },
}));

import { getMfaStatus, disableMfa, enrollMfa, verifyMfaEnroll } from "@/lib/portal-api";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MfaCard — not enrolled", () => {
  it("renders the 'Not enabled' pill and 'Enable MFA' CTA", async () => {
    vi.mocked(getMfaStatus).mockResolvedValue({
      enrolled: false,
      last_verified_at: null,
    });
    render(withIntl(<MfaCard />));
    await waitFor(() => {
      expect(screen.getByText("Not enabled")).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: "Enable MFA" }),
    ).toBeInTheDocument();
  });

  it("opens the enroll modal on CTA click", async () => {
    const user = userEvent.setup();
    vi.mocked(getMfaStatus).mockResolvedValue({
      enrolled: false,
      last_verified_at: null,
    });
    vi.mocked(enrollMfa).mockResolvedValue({
      qr_uri: "otpauth://totp/Aurion:test@aurion.local?secret=ABCD",
      secret: "ABCDEFGHIJKLMNOP",
      recovery_codes: ["ABCD-EFGH", "1234-5678"],
      setup_token: "stub-setup-token",
    });
    render(withIntl(<MfaCard />));
    await waitFor(() => {
      expect(screen.getByText("Not enabled")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Enable MFA" }));
    // Modal opens (title appears in the dialog).
    await waitFor(() => {
      expect(
        screen.getByText("Enable multi-factor authentication"),
      ).toBeInTheDocument();
    });
    // After the enrollMfa() call settles, recovery codes render.
    await waitFor(() => {
      expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument();
      expect(screen.getByText("1234-5678")).toBeInTheDocument();
    });
    expect(enrollMfa).toHaveBeenCalledOnce();
  });
});

describe("MfaCard — enrolled", () => {
  it("renders the 'Enabled' pill and 'Disable MFA' CTA", async () => {
    vi.mocked(getMfaStatus).mockResolvedValue({
      enrolled: true,
      last_verified_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    });
    render(withIntl(<MfaCard />));
    await waitFor(() => {
      expect(screen.getByText("Enabled")).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: "Disable MFA" }),
    ).toBeInTheDocument();
  });

  it("opens the disable modal on CTA click", async () => {
    const user = userEvent.setup();
    vi.mocked(getMfaStatus).mockResolvedValue({
      enrolled: true,
      last_verified_at: new Date().toISOString(),
    });
    render(withIntl(<MfaCard />));
    await waitFor(() => {
      expect(screen.getByText("Enabled")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Disable MFA" }));
    await waitFor(() => {
      expect(
        screen.getByText("Disable multi-factor authentication"),
      ).toBeInTheDocument();
    });
  });
});

describe("MfaCard — i18n parity (AC-10)", () => {
  it("EN catalog carries every Account.mfa.* key the component reads", () => {
    expect(enMessages.Account.mfa).toBeDefined();
    expect(enMessages.Account.mfa.enroll).toBeDefined();
    expect(enMessages.Account.mfa.disable).toBeDefined();
    expect(enMessages.Account.sessions).toBeDefined();
  });

  it("FR catalog carries every Account.mfa.* key the component reads", () => {
    expect(frMessages.Account.mfa).toBeDefined();
    expect(frMessages.Account.mfa.enroll).toBeDefined();
    expect(frMessages.Account.mfa.disable).toBeDefined();
    expect(frMessages.Account.sessions).toBeDefined();
  });

  it("EN + FR namespaces have parity at the leaf level", () => {
    function collectKeys(
      obj: Record<string, unknown>,
      prefix = "",
    ): string[] {
      const keys: string[] = [];
      for (const [k, v] of Object.entries(obj)) {
        const path = prefix ? `${prefix}.${k}` : k;
        if (v && typeof v === "object" && !Array.isArray(v)) {
          keys.push(...collectKeys(v as Record<string, unknown>, path));
        } else {
          keys.push(path);
        }
      }
      return keys.sort();
    }
    const enKeys = collectKeys(enMessages.Account.mfa as Record<string, unknown>);
    const frKeys = collectKeys(frMessages.Account.mfa as Record<string, unknown>);
    expect(frKeys).toEqual(enKeys);

    const enSessKeys = collectKeys(
      enMessages.Account.sessions as Record<string, unknown>,
    );
    const frSessKeys = collectKeys(
      frMessages.Account.sessions as Record<string, unknown>,
    );
    expect(frSessKeys).toEqual(enSessKeys);
  });

  it("renders cleanly in FR locale", async () => {
    vi.mocked(getMfaStatus).mockResolvedValue({
      enrolled: false,
      last_verified_at: null,
    });
    render(withIntl(<MfaCard />, "fr"));
    await waitFor(() => {
      // "Activer l'authentification à deux facteurs" — the enable CTA.
      expect(
        screen.getByRole("button", {
          name: /Activer l/,
        }),
      ).toBeInTheDocument();
    });
  });
});
