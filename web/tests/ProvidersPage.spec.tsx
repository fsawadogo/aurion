import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import ProvidersPage from "@/app/portal/admin/providers/page";
import { withIntl } from "./helpers/intl";

/**
 * /portal/admin/providers — runtime AI-provider switch.
 *
 * Verifies the page loads the per-stage overview, highlights the effective
 * provider, pins a new provider via setProviderOverride, and clears an
 * active override via clearProviderOverride. `@/lib/api` is mocked so there's
 * no network round-trip.
 */

vi.mock("@/lib/api", () => ({
  getProviders: vi.fn(),
  getProviderUsage: vi.fn(),
  setProviderOverride: vi.fn(),
  clearProviderOverride: vi.fn(),
  // pass-through fallback so error copy is deterministic
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import {
  getProviders,
  getProviderUsage,
  setProviderOverride,
  clearProviderOverride,
} from "@/lib/api";

const OVERVIEW = {
  providers: [
    {
      provider_type: "note_generation",
      appconfig_value: "anthropic",
      override_value: "gemini",
      effective_value: "gemini",
    },
    {
      provider_type: "vision",
      appconfig_value: "openai",
      override_value: null,
      effective_value: "openai",
    },
    {
      provider_type: "transcription",
      appconfig_value: "assemblyai",
      override_value: null,
      effective_value: "assemblyai",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getProviders).mockResolvedValue(OVERVIEW as never);
  // The usage panel (#73) mounts inside the page — give it an empty rollup
  // so page tests stay focused on the switch behavior.
  vi.mocked(getProviderUsage).mockResolvedValue({
    since: null,
    until: null,
    provider_type: null,
    totals: {
      call_count: 0, success_count: 0, failure_count: 0, fallback_count: 0,
      avg_latency_ms: 0, total_input_tokens: 0, total_output_tokens: 0,
      total_cost_usd: 0,
    },
    by_provider: [],
  } as never);
  vi.mocked(setProviderOverride).mockResolvedValue(OVERVIEW as never);
  vi.mocked(clearProviderOverride).mockResolvedValue(OVERVIEW as never);
});

describe("ProvidersPage", () => {
  it("renders each pipeline stage with its effective provider highlighted", async () => {
    render(withIntl(<ProvidersPage />));
    await waitFor(() => {
      expect(screen.getByTestId("provider-row-note_generation")).toBeTruthy();
    });
    expect(screen.getByTestId("provider-row-vision")).toBeTruthy();
    expect(screen.getByTestId("provider-row-transcription")).toBeTruthy();

    // Gemini is the effective note_generation provider → active + disabled.
    const gemini = screen.getByTestId(
      "provider-note_generation-option-gemini",
    ) as HTMLButtonElement;
    expect(gemini.getAttribute("aria-pressed")).toBe("true");
    expect(gemini.disabled).toBe(true);

    // Anthropic is NOT effective → enabled (switchable).
    const anthropic = screen.getByTestId(
      "provider-note_generation-option-anthropic",
    ) as HTMLButtonElement;
    expect(anthropic.disabled).toBe(false);
  });

  it("pins a new provider via setProviderOverride", async () => {
    render(withIntl(<ProvidersPage />));
    await waitFor(() => screen.getByTestId("provider-row-vision"));

    // vision effective = openai; switch it to gemini.
    fireEvent.click(screen.getByTestId("provider-vision-option-gemini"));
    await waitFor(() => {
      expect(setProviderOverride).toHaveBeenCalledWith(
        "vision",
        "gemini",
        expect.any(String),
      );
    });
  });

  it("clears an active override via clearProviderOverride", async () => {
    render(withIntl(<ProvidersPage />));
    await waitFor(() => screen.getByTestId("provider-row-note_generation"));

    // note_generation carries an override (gemini) → exactly one reset control.
    const resets = screen.getAllByText("Reset to default");
    expect(resets.length).toBe(1);
    fireEvent.click(resets[0]);
    await waitFor(() => {
      expect(clearProviderOverride).toHaveBeenCalledWith("note_generation");
    });
  });

  it("renders the FR catalog (parity)", async () => {
    render(withIntl(<ProvidersPage />, "fr"));
    await waitFor(() => {
      expect(screen.getByText("Fournisseurs IA")).toBeTruthy();
    });
  });
});
