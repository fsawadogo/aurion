import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import AdminCompliancePage from "@/app/portal/admin/compliance/page";
import { withIntl } from "./helpers/intl";

/**
 * /portal/admin/compliance (#77) — generate buttons per type, signed-report
 * table with sha prefix + download, FR parity.
 */

vi.mock("@/lib/api", () => ({
  listComplianceReports: vi.fn(),
  generateComplianceReport: vi.fn(),
  downloadComplianceReport: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import {
  downloadComplianceReport,
  generateComplianceReport,
  listComplianceReports,
} from "@/lib/api";

const REPORT = {
  id: "r1",
  report_type: "masking" as const,
  since: null,
  until: null,
  generated_at: new Date().toISOString(),
  generated_by: "u1",
  sha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
  byte_size: 2048,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listComplianceReports).mockResolvedValue({
    items: [REPORT],
    limit: 50,
    offset: 0,
  } as never);
  vi.mocked(generateComplianceReport).mockResolvedValue(REPORT as never);
  vi.mocked(downloadComplianceReport).mockResolvedValue(new Blob(["a,b"]) as never);
});

describe("AdminCompliancePage", () => {
  it("lists reports with type badge, size, sha prefix, and full-history window", async () => {
    render(withIntl(<AdminCompliancePage />));

    await waitFor(() => expect(screen.getByTestId("report-row-r1")).toBeInTheDocument());
    const row = screen.getByTestId("report-row-r1");
    expect(row).toHaveTextContent("Masking");
    expect(row).toHaveTextContent("2.0 KB");
    expect(row).toHaveTextContent("abcdef012345…");
    expect(row).toHaveTextContent("Full history");
  });

  it("generate posts the type and refreshes with the sha toast", async () => {
    render(withIntl(<AdminCompliancePage />));
    await waitFor(() => expect(screen.getByTestId("generate-retention")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("generate-retention"));
    await waitFor(() =>
      expect(generateComplianceReport).toHaveBeenCalledWith("retention"),
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("sha256 abcdef012345"),
    );
    expect(listComplianceReports).toHaveBeenCalledTimes(2); // initial + refresh
  });

  it("download streams the blob", async () => {
    const createObjectURL = vi.fn(() => "blob:x");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });

    render(withIntl(<AdminCompliancePage />));
    await waitFor(() => expect(screen.getByTestId("download-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("download-r1"));
    await waitFor(() => expect(downloadComplianceReport).toHaveBeenCalledWith("r1"));
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalled());
  });

  it("renders the FR catalog at parity", async () => {
    render(withIntl(<AdminCompliancePage />, "fr"));
    await waitFor(() =>
      expect(screen.getByText("Rapports de conformité")).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId("report-row-r1")).toHaveTextContent("Masquage"),
    );
    expect(screen.getByTestId("generate-audit")).toHaveTextContent("Générer Audit");
  });

  it("surfaces a load error", async () => {
    vi.mocked(listComplianceReports).mockRejectedValue(new Error("boom"));
    render(withIntl(<AdminCompliancePage />));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Unable to load reports."),
    );
  });
});
