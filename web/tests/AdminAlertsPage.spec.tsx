import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import AdminAlertsPage from "@/app/portal/admin/alerts/page";
import { withIntl } from "./helpers/intl";

/**
 * /portal/admin/alerts (#76) — list with severity chips + open/ack filter,
 * acknowledge removes from the open view, FR parity.
 */

vi.mock("@/lib/api", () => ({
  listAlerts: vi.fn(),
  acknowledgeAlert: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import { acknowledgeAlert, listAlerts } from "@/lib/api";

const OPEN_ALERT = {
  id: "a1",
  alert_type: "masking_failed",
  severity: "critical" as const,
  source: "vision_service",
  message: "Clip masking failed for session 1a2b3c4d",
  metadata: null,
  created_at: new Date().toISOString(),
  acknowledged_at: null,
  acknowledged_by: null,
};

const ACKED_ALERT = {
  ...OPEN_ALERT,
  id: "a2",
  severity: "warning" as const,
  alert_type: "sla_breach_stage1",
  message: "Stage 1 exceeded 30s",
  acknowledged_at: new Date().toISOString(),
  acknowledged_by: "u1",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listAlerts).mockResolvedValue({
    items: [OPEN_ALERT],
    limit: 100,
    offset: 0,
  } as never);
  vi.mocked(acknowledgeAlert).mockResolvedValue({
    ...OPEN_ALERT,
    acknowledged_at: new Date().toISOString(),
    acknowledged_by: "me",
  } as never);
});

describe("AdminAlertsPage", () => {
  it("defaults to the open filter and renders severity chips", async () => {
    render(withIntl(<AdminAlertsPage />));

    await waitFor(() =>
      expect(screen.getByTestId("alert-row-a1")).toBeInTheDocument(),
    );
    expect(listAlerts).toHaveBeenCalledWith({ status: "open", limit: 100 });
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Clip masking failed for session 1a2b3c4d")).toBeInTheDocument();
    expect(screen.getByTestId("ack-a1")).toBeInTheDocument();
  });

  it("acknowledging removes the row from the open view", async () => {
    render(withIntl(<AdminAlertsPage />));
    await waitFor(() => expect(screen.getByTestId("ack-a1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("ack-a1"));
    await waitFor(() => expect(acknowledgeAlert).toHaveBeenCalledWith("a1"));
    await waitFor(() =>
      expect(screen.queryByTestId("alert-row-a1")).not.toBeInTheDocument(),
    );
    // Empty state appears once the lone open alert is acknowledged.
    expect(screen.getByText("No alerts — all clear.")).toBeInTheDocument();
  });

  it("the all filter shows acknowledged rows without an ack button", async () => {
    vi.mocked(listAlerts).mockResolvedValue({
      items: [OPEN_ALERT, ACKED_ALERT],
      limit: 100,
      offset: 0,
    } as never);
    render(withIntl(<AdminAlertsPage />));
    await waitFor(() => expect(screen.getByTestId("alert-row-a1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("alerts-filter-all"));
    await waitFor(() => expect(listAlerts).toHaveBeenLastCalledWith({ limit: 100 }));
    await waitFor(() => expect(screen.getByTestId("alert-row-a2")).toBeInTheDocument());

    expect(screen.getByTestId("ack-a1")).toBeInTheDocument();      // open → button
    expect(screen.queryByTestId("ack-a2")).not.toBeInTheDocument(); // acked → none
    expect(screen.getByText(/acknowledged/)).toBeInTheDocument();
  });

  it("renders the FR catalog at parity", async () => {
    render(withIntl(<AdminAlertsPage />, "fr"));
    await waitFor(() =>
      expect(screen.getByText("Alertes opérationnelles")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("alerts-filter-open")).toHaveTextContent("Ouvertes");
    await waitFor(() => expect(screen.getByText("Critique")).toBeInTheDocument());
  });

  it("surfaces a load error", async () => {
    vi.mocked(listAlerts).mockRejectedValue(new Error("boom"));
    render(withIntl(<AdminAlertsPage />));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Unable to load alerts."),
    );
  });
});
