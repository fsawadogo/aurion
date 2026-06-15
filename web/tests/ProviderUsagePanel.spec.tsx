import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import ProviderUsagePanel from "@/components/portal/ProviderUsagePanel";
import { withIntl } from "./helpers/intl";

/**
 * Provider usage & cost rollup (#73).
 *
 * Verifies the panel loads the rollup, renders totals + the per-provider
 * table, formats fractions/latency/zero-cost correctly, refetches on range
 * change (with a `since` bound for finite ranges, none for "all"), and
 * shows the empty state when no calls were recorded.
 */

vi.mock("@/lib/api", () => ({
  getProviderUsage: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import { getProviderUsage } from "@/lib/api";

const USAGE = {
  since: null,
  until: null,
  provider_type: null,
  totals: {
    call_count: 142,
    success_count: 139,
    failure_count: 3,
    fallback_count: 5,
    avg_latency_ms: 2310.4,
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cost_usd: 0,
  },
  by_provider: [
    {
      provider_type: "note_generation",
      provider_name: "gemini",
      call_count: 80,
      success_count: 79,
      failure_count: 1,
      fallback_count: 2,
      avg_latency_ms: 3120.0,
      success_rate: 0.9875,
      fallback_rate: 0.025,
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_cost_usd: 0,
    },
    {
      provider_type: "vision",
      provider_name: "gemini",
      call_count: 62,
      success_count: 60,
      failure_count: 2,
      fallback_count: 3,
      avg_latency_ms: 890.2,
      success_rate: 0.9677,
      fallback_rate: 0.0484,
      total_input_tokens: 51000,
      total_output_tokens: 9000,
      total_cost_usd: 0.4321,
    },
  ],
};

const EMPTY = {
  ...USAGE,
  totals: { ...USAGE.totals, call_count: 0, success_count: 0, failure_count: 0 },
  by_provider: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getProviderUsage).mockResolvedValue(USAGE as never);
});

describe("ProviderUsagePanel", () => {
  it("renders totals and the per-provider rollup table", async () => {
    render(withIntl(<ProviderUsagePanel />));

    await waitFor(() =>
      expect(screen.getByTestId("usage-stat-calls")).toHaveTextContent("142"),
    );
    // Derived success rate: 139/142 → 97.9%
    expect(screen.getByTestId("usage-stat-successRate")).toHaveTextContent("97.9%");
    // ≥1s latency renders in seconds
    expect(screen.getByTestId("usage-stat-avgLatency")).toHaveTextContent("2.3 s");
    // Zero cost is "—", never "$0.00"
    expect(screen.getByTestId("usage-stat-estCost")).toHaveTextContent("—");

    const visionRow = screen.getByTestId("usage-row-vision-gemini");
    expect(visionRow).toHaveTextContent("Gemini");
    expect(visionRow).toHaveTextContent("96.8%"); // success_rate fraction → %
    expect(visionRow).toHaveTextContent("890 ms"); // <1s stays in ms
    expect(visionRow.textContent).toMatch(/60[,\u00A0\u202F ]000/); // input+output tokens, delimiter-agnostic
    expect(visionRow).toHaveTextContent("$0.4321"); // sub-$1 cost gets 4 dp

    const noteRow = screen.getByTestId("usage-row-note_generation-gemini");
    expect(noteRow).toHaveTextContent("—"); // zero tokens and zero cost
  });

  it("defaults to 7d with a since bound, and 'all' refetches without one", async () => {
    render(withIntl(<ProviderUsagePanel />));
    // Wait for the initial load to SETTLE, not merely fire. The range
    // buttons are `disabled={active || loading}`, so clicking before the
    // first fetch resolves (loading still true) is a no-op and the refetch
    // never happens — the source of the intermittent "called 1 time, not 2"
    // failure. The stat only renders once loading flips false.
    await waitFor(() =>
      expect(screen.getByTestId("usage-stat-calls")).toBeInTheDocument(),
    );
    expect(getProviderUsage).toHaveBeenCalledTimes(1);

    const first = vi.mocked(getProviderUsage).mock.calls[0][0];
    expect(first?.since).toBeTruthy();
    // since ≈ now - 7d (tolerate test runtime skew)
    const sinceMs = new Date(first!.since!).getTime();
    expect(Date.now() - sinceMs).toBeGreaterThan(6.9 * 24 * 3_600_000);
    expect(Date.now() - sinceMs).toBeLessThan(7.1 * 24 * 3_600_000);

    fireEvent.click(screen.getByTestId("usage-range-all"));
    await waitFor(() => expect(getProviderUsage).toHaveBeenCalledTimes(2));
    expect(vi.mocked(getProviderUsage).mock.calls[1][0]).toBeUndefined();
  });

  it("shows the empty state when no calls are recorded", async () => {
    vi.mocked(getProviderUsage).mockResolvedValue(EMPTY as never);
    render(withIntl(<ProviderUsagePanel />));

    await waitFor(() =>
      expect(
        screen.getByText("No provider calls recorded in this window yet."),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("usage-stat-calls")).not.toBeInTheDocument();
  });

  it("renders the FR catalog at parity (house rule: EN+FR)", async () => {
    render(withIntl(<ProviderUsagePanel />, "fr"));

    await waitFor(() =>
      expect(screen.getByText("Utilisation et coûts")).toBeInTheDocument(),
    );
    // A dynamic-key sample from each nested group, so a dropped FR key
    // fails here rather than shipping silently.
    expect(screen.getByTestId("usage-range-all")).toHaveTextContent(
      "Tout l’historique",
    );
    expect(screen.getByText("Génération de notes")).toBeInTheDocument();
  });

  it("pins the cost precision boundary: 4dp under $1, 2dp at $1+", async () => {
    vi.mocked(getProviderUsage).mockResolvedValue({
      ...USAGE,
      by_provider: [
        { ...USAGE.by_provider[1], provider_name: "openai", total_cost_usd: 0.9999 },
        { ...USAGE.by_provider[1], provider_name: "anthropic", total_cost_usd: 1.0 },
      ],
    } as never);
    render(withIntl(<ProviderUsagePanel />));

    await waitFor(() =>
      expect(screen.getByTestId("usage-row-vision-openai")).toHaveTextContent("$0.9999"),
    );
    expect(screen.getByTestId("usage-row-vision-anthropic")).toHaveTextContent("$1.00");
  });

  it("surfaces a load error without crashing the panel", async () => {
    vi.mocked(getProviderUsage).mockRejectedValue(new Error("boom"));
    render(withIntl(<ProviderUsagePanel />));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Unable to load provider usage.",
      ),
    );
  });
});
