import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import AdminAnalyticsPage from "@/app/portal/admin/analytics/page";
import { withIntl } from "./helpers/intl";

/**
 * /portal/admin/analytics — adoption & ROI rollup (#71 slice 2).
 *
 * Verifies the stat/quality cards + per-clinician table render from the
 * rollup, time-saved stays "—" until a baseline is typed (then refetches
 * with the baseline and shows the assumption note), the range picker
 * refetches, and CSV export downloads a blob.
 */

vi.mock("@/lib/api", () => ({
  getAdoptionAnalytics: vi.fn(),
  exportAdoptionCsv: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import { exportAdoptionCsv, getAdoptionAnalytics } from "@/lib/api";

const ROW = {
  clinician_id: "11111111-2222-3333-4444-555555555555",
  email: "marie@aurionclinical.com",
  sessions_total: 12,
  sessions_exported: 10,
  active_days: 5,
  notes_per_active_day: 2.0,
  avg_completeness: 0.91,
  avg_citation_traceability: 0.97,
  avg_edit_rate: 0.18,
  avg_stage1_latency_ms: 21000,
  avg_stage2_latency_ms: 130000,
  time_saved_minutes: null as number | null,
  last_active_at: new Date().toISOString(),
};

function usage(baseline: number | null) {
  return {
    since: null,
    until: null,
    baseline_minutes_per_note: baseline,
    totals: {
      active_clinicians: 2,
      sessions_total: 20,
      sessions_exported: 16,
      notes_per_active_day: 1.6,
      avg_completeness: 0.9,
      avg_citation_traceability: 0.96,
      avg_edit_rate: 0.2,
      avg_stage1_latency_ms: 22000,
      avg_stage2_latency_ms: 125000,
      time_saved_minutes: baseline === null ? null : 16 * baseline,
    },
    by_clinician: [
      { ...ROW, time_saved_minutes: baseline === null ? null : 10 * baseline },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAdoptionAnalytics).mockResolvedValue(usage(null) as never);
});

describe("AdminAnalyticsPage", () => {
  it("renders adoption + quality cards and the clinician table", async () => {
    render(withIntl(<AdminAnalyticsPage />));

    await waitFor(() =>
      expect(screen.getByTestId("analytics-stat-activeClinicians")).toHaveTextContent("2"),
    );
    expect(screen.getByTestId("analytics-stat-notesExported")).toHaveTextContent("16");
    expect(screen.getByTestId("analytics-quality-completeness")).toHaveTextContent("90.0%");
    expect(screen.getByTestId("analytics-quality-stage1")).toHaveTextContent("22.0 s");
    // No baseline → time saved is a dash + the how-to hint.
    expect(screen.getByTestId("analytics-stat-timeSaved")).toHaveTextContent("—");
    expect(
      screen.getByText("Set a baseline (min saved per note) to compute."),
    ).toBeInTheDocument();

    const row = screen.getByTestId(`analytics-row-${ROW.clinician_id}`);
    expect(row).toHaveTextContent("marie@aurionclinical.com");
    expect(row).toHaveTextContent("12");
    expect(row).toHaveTextContent("91.0%");
  });

  it("typing a baseline refetches with it and shows the assumption", async () => {
    render(withIntl(<AdminAnalyticsPage />));
    await waitFor(() => expect(getAdoptionAnalytics).toHaveBeenCalledTimes(1));
    expect(getAdoptionAnalytics).toHaveBeenCalledWith(
      expect.not.objectContaining({ baselineMinutesPerNote: expect.anything() }),
    );

    vi.mocked(getAdoptionAnalytics).mockResolvedValue(usage(10) as never);
    fireEvent.change(screen.getByTestId("baseline-input"), { target: { value: "10" } });

    await waitFor(() =>
      expect(getAdoptionAnalytics).toHaveBeenLastCalledWith(
        expect.objectContaining({ baselineMinutesPerNote: 10 }),
      ),
    );
    // 160 min → "2 h 40 min"
    await waitFor(() =>
      expect(screen.getByTestId("analytics-stat-timeSaved")).toHaveTextContent("2 h 40 min"),
    );
    expect(
      screen.getByText("Assumes 10 min of manual documentation per note."),
    ).toBeInTheDocument();
  });

  it("out-of-range baseline (>120) is ignored, not sent", async () => {
    render(withIntl(<AdminAnalyticsPage />));
    await waitFor(() => expect(getAdoptionAnalytics).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByTestId("baseline-input"), { target: { value: "500" } });
    // Give any (incorrect) refetch a chance to fire, then assert none did
    // with a baseline param.
    await new Promise((r) => setTimeout(r, 50));
    for (const call of vi.mocked(getAdoptionAnalytics).mock.calls) {
      expect(call[0] ?? {}).not.toHaveProperty("baselineMinutesPerNote");
    }
  });

  it("range change refetches; 'all' drops the since bound", async () => {
    render(withIntl(<AdminAnalyticsPage />));
    await waitFor(() => expect(getAdoptionAnalytics).toHaveBeenCalledTimes(1));
    expect(vi.mocked(getAdoptionAnalytics).mock.calls[0][0]).toHaveProperty("since");

    fireEvent.click(screen.getByTestId("analytics-range-all"));
    await waitFor(() => expect(getAdoptionAnalytics).toHaveBeenCalledTimes(2));
    expect(vi.mocked(getAdoptionAnalytics).mock.calls[1][0] ?? {}).not.toHaveProperty("since");
  });

  it("exports the CSV blob", async () => {
    vi.mocked(exportAdoptionCsv).mockResolvedValue(new Blob(["a,b"]) as never);
    const createObjectURL = vi.fn(() => "blob:x");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });

    render(withIntl(<AdminAnalyticsPage />));
    await waitFor(() =>
      expect(screen.getByTestId("analytics-stat-activeClinicians")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Export CSV/ }));

    await waitFor(() => expect(exportAdoptionCsv).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalled());
  });

  it("renders the FR catalog at parity", async () => {
    render(withIntl(<AdminAnalyticsPage />, "fr"));
    await waitFor(() =>
      // Page title is now "Statistiques"; "Adoption et ROI" is a section heading.
      expect(screen.getByText("Statistiques")).toBeInTheDocument(),
    );
    expect(screen.getByText("Adoption et ROI")).toBeInTheDocument();
    expect(screen.getByText("Qualité et performance")).toBeInTheDocument();
    expect(screen.getByTestId("analytics-range-all")).toHaveTextContent("Tout l’historique");
    expect(screen.getByText("Cliniciens actifs")).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    vi.mocked(getAdoptionAnalytics).mockRejectedValue(new Error("boom"));
    render(withIntl(<AdminAnalyticsPage />));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Unable to load adoption analytics.",
      ),
    );
  });
});
