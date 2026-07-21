import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import EvalCompareRuns from "@/app/eval/[id]/EvalCompareRuns";

/**
 * EVAL-1 — the Compare-runs panel. The eval API is mocked at the boundary so
 * no network I/O happens. Asserts the run selector + the settings/metrics
 * comparison table + the side-by-side notes, and the ≥2-runs gate.
 */

vi.mock("@/lib/api", () => ({
  getEvalSessionRuns: vi.fn(),
}));

import { getEvalSessionRuns } from "@/lib/api";

const RUNS = [
  {
    version: 1,
    stage: 1,
    provider_used: "anthropic",
    completeness_score: 0.7,
    is_approved: false,
    created_at: "2026-07-20T10:00:00Z",
    // Pre-provenance version — no snapshot; settings show "—".
    settings_snapshot: null,
    metrics: {
      total_claims: 20,
      grounding_rate: 0.9,
      ungrounded_claims: 2,
      section_completeness: 0.8,
      ap_claims: 0,
      multi_anchor_rate: 0,
    },
    note_sections: [
      {
        id: "hpi",
        title: "HPI",
        status: "populated",
        claims: [
          {
            id: "c1",
            text: "Alpha claim",
            source_type: "transcript",
            source_id: "seg_1",
            source_quote: "",
          },
        ],
      },
    ],
  },
  {
    version: 2,
    stage: 2,
    provider_used: "anthropic",
    completeness_score: 0.85,
    is_approved: true,
    created_at: "2026-07-20T10:05:00Z",
    settings_snapshot: {
      template_engine_enabled: true,
      grounded_synthesis_enabled: false,
      template_key: "orthopedic_surgery",
      detail_level: "brief",
    },
    metrics: {
      total_claims: 12,
      grounding_rate: 1.0,
      ungrounded_claims: 0,
      section_completeness: 1.0,
      ap_claims: 3,
      multi_anchor_rate: 0.33,
    },
    note_sections: [
      {
        id: "hpi",
        title: "HPI",
        status: "populated",
        claims: [
          {
            id: "c2",
            text: "Beta claim",
            source_type: "transcript",
            source_id: "seg_1",
            source_quote: "",
          },
        ],
      },
    ],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getEvalSessionRuns).mockResolvedValue(RUNS as never);
});

describe("EvalCompareRuns", () => {
  it("preselects the last two runs and lays metrics + settings side by side", async () => {
    render(<EvalCompareRuns sessionId="sess-1" />);
    await screen.findByTestId("eval-compare-table");

    // Both runs' claim counts appear, per version.
    expect(screen.getByTestId("metric-total_claims-v1")).toHaveTextContent("20");
    expect(screen.getByTestId("metric-total_claims-v2")).toHaveTextContent("12");
    // Rates render as percentages.
    expect(screen.getByTestId("metric-grounding_rate-v1")).toHaveTextContent("90%");
    expect(screen.getByTestId("metric-grounding_rate-v2")).toHaveTextContent("100%");

    // v2 carries a snapshot → "On" for the template engine; v1 has none.
    expect(screen.getByText("On")).toBeInTheDocument();
    // Both notes render side by side.
    expect(screen.getByTestId("eval-run-note-1")).toHaveTextContent("Alpha claim");
    expect(screen.getByTestId("eval-run-note-2")).toHaveTextContent("Beta claim");
  });

  it("requires at least two runs selected", async () => {
    render(<EvalCompareRuns sessionId="sess-1" />);
    await screen.findByTestId("eval-compare-table");
    const user = userEvent.setup();

    // Deselect v1 → only one run selected → the table drops, hint appears.
    await user.click(screen.getByTestId("eval-run-pill-1"));
    await waitFor(() =>
      expect(screen.queryByTestId("eval-compare-table")).toBeNull(),
    );
    expect(screen.getByText(/select at least two runs/i)).toBeInTheDocument();
  });
});
