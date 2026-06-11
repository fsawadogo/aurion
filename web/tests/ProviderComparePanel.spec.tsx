import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import ProviderComparePanel from "@/components/portal/ProviderComparePanel";
import { withIntl } from "./helpers/intl";

/**
 * Provider A-B compare (#73/#74, OV-4): operational side-by-side + the
 * eval-quality table with its sample-size honesty caption; quality 403
 * hides only that section.
 */

vi.mock("@/lib/api", () => ({
  compareProviders: vi.fn(),
  compareProviderQuality: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import { compareProviderQuality, compareProviders } from "@/lib/api";

function rollup(name: string, calls: number) {
  return {
    provider_type: "note_generation",
    provider_name: name,
    call_count: calls,
    success_count: calls,
    failure_count: 0,
    fallback_count: 0,
    avg_latency_ms: 2000,
    success_rate: 0.975,
    fallback_rate: 0.0,
    total_input_tokens: 1000,
    total_output_tokens: 500,
    total_cost_usd: 1.25,
  };
}

const OPERATIONAL = {
  provider_type: "note_generation",
  a: "anthropic",
  b: "gemini",
  since: null,
  until: null,
  a_rollup: rollup("anthropic", 40),
  b_rollup: rollup("gemini", 62),
  delta: { avg_latency_ms: 0, success_rate: 0, fallback_rate: 0 },
};

const QUALITY = {
  since: null,
  until: null,
  providers: [
    {
      provider_name: "gemini",
      scored_sessions: 5,
      avg_overall: 0.91,
      avg_transcript_accuracy: 0.93,
      avg_citation_correctness: 0.95,
      avg_descriptive_mode_compliance: 1.0,
      avg_hallucination_count: 0.2,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(compareProviders).mockResolvedValue(OPERATIONAL as never);
  vi.mocked(compareProviderQuality).mockResolvedValue(QUALITY as never);
});

describe("ProviderComparePanel", () => {
  it("calls the operational compare with exact params and renders both sides", async () => {
    render(withIntl(<ProviderComparePanel />));

    await waitFor(() =>
      expect(screen.getByTestId("operational-table")).toBeInTheDocument(),
    );
    const call = vi.mocked(compareProviders).mock.calls[0][0];
    expect(call.a).toBe("anthropic");
    expect(call.b).toBe("gemini");
    expect(call.providerType).toBe("note_generation");
    expect(call.since).toBeTruthy(); // default 30d window

    const calls = screen.getByTestId("compare-row-calls");
    expect(calls).toHaveTextContent("40");
    expect(calls).toHaveTextContent("62");
    expect(screen.getByTestId("compare-row-success")).toHaveTextContent("97.5%");
    expect(screen.getByTestId("compare-row-cost")).toHaveTextContent("$1.25");
  });

  it("renders the quality table with the sample-size caption", async () => {
    render(withIntl(<ProviderComparePanel />));

    await waitFor(() =>
      expect(screen.getByTestId("quality-row-gemini")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("quality-row-gemini");
    expect(row).toHaveTextContent("Gemini");
    expect(row).toHaveTextContent("5");      // scored sessions ride with the data
    expect(row).toHaveTextContent("0.91");
    expect(
      screen.getByText(/directional, not statistically significant/),
    ).toBeInTheDocument();
  });

  it("hides only the quality section on a 403, operational still renders", async () => {
    vi.mocked(compareProviderQuality).mockRejectedValue(new Error("403"));
    render(withIntl(<ProviderComparePanel />));

    await waitFor(() =>
      expect(screen.getByTestId("operational-table")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("quality-table")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("changing the B provider refetches", async () => {
    render(withIntl(<ProviderComparePanel />));
    await waitFor(() => expect(compareProviders).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByTestId("compare-b"), { target: { value: "openai" } });
    await waitFor(() => expect(compareProviders).toHaveBeenCalledTimes(2));
    expect(vi.mocked(compareProviders).mock.calls[1][0].b).toBe("openai");
  });

  it("renders the FR catalog at parity", async () => {
    render(withIntl(<ProviderComparePanel />, "fr"));
    await waitFor(() =>
      expect(screen.getByText("Comparaison A-B")).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByText(/indicatives et non statistiquement/)).toBeInTheDocument(),
    );
  });

  it("surfaces an operational load error", async () => {
    vi.mocked(compareProviders).mockRejectedValue(new Error("boom"));
    render(withIntl(<ProviderComparePanel />));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Unable to load the comparison.",
      ),
    );
  });
});
