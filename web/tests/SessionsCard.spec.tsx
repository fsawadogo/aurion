import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SessionsCard from "@/components/portal/SessionsCard";
import type { ActiveSession } from "@/lib/portal-api";

import { withIntl } from "./helpers/intl";

/**
 * SessionsCard — covers AC-9.
 *
 * Validates that:
 *   * the list renders with per-row revoke buttons
 *   * the current-session row is badged + its revoke button is disabled
 *   * clicking a non-current row's revoke button calls the API
 *   * "Sign out everywhere else" CTA fires the bulk API
 */

vi.mock("@/lib/portal-api", () => ({
  listSessions: vi.fn(),
  revokeSession: vi.fn(),
  revokeAllSessions: vi.fn(),
}));

import {
  listSessions,
  revokeSession,
  revokeAllSessions,
} from "@/lib/portal-api";

const CURRENT: ActiveSession = {
  id: "00000000-0000-0000-0000-000000000001",
  device_hint: "Safari · macOS",
  ip_class: "private",
  created_at: "2026-06-06T08:00:00Z",
  last_used_at: "2026-06-06T08:30:00Z",
  is_current: true,
};

const OTHER: ActiveSession = {
  id: "00000000-0000-0000-0000-000000000002",
  device_hint: "Chrome · Windows",
  ip_class: "internet",
  created_at: "2026-06-05T20:00:00Z",
  last_used_at: "2026-06-05T21:00:00Z",
  is_current: false,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SessionsCard", () => {
  it("renders rows with device hint + current badge", async () => {
    vi.mocked(listSessions).mockResolvedValue([CURRENT, OTHER]);
    render(withIntl(<SessionsCard />));
    await waitFor(() => {
      expect(screen.getByText("Safari · macOS")).toBeInTheDocument();
    });
    expect(screen.getByText("Chrome · Windows")).toBeInTheDocument();
    expect(screen.getByText("This device")).toBeInTheDocument();
  });

  it("disables the revoke button on the current row", async () => {
    vi.mocked(listSessions).mockResolvedValue([CURRENT, OTHER]);
    render(withIntl(<SessionsCard />));
    await waitFor(() => {
      expect(screen.getByText("Safari · macOS")).toBeInTheDocument();
    });
    const currentRevoke = screen.getByRole("button", {
      name: /Revoke session on Safari/,
    });
    expect(currentRevoke).toBeDisabled();
    const otherRevoke = screen.getByRole("button", {
      name: /Revoke session on Chrome/,
    });
    expect(otherRevoke).toBeEnabled();
  });

  it("calls revokeSession when a non-current row's button is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(listSessions).mockResolvedValueOnce([CURRENT, OTHER]);
    vi.mocked(revokeSession).mockResolvedValueOnce(undefined);
    vi.mocked(listSessions).mockResolvedValueOnce([CURRENT]);
    render(withIntl(<SessionsCard />));
    await waitFor(() => {
      expect(screen.getByText("Chrome · Windows")).toBeInTheDocument();
    });
    await user.click(
      screen.getByRole("button", {
        name: /Revoke session on Chrome/,
      }),
    );
    await waitFor(() => {
      expect(revokeSession).toHaveBeenCalledWith(OTHER.id);
    });
  });

  it("calls revokeAllSessions when the bulk CTA is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(listSessions).mockResolvedValueOnce([CURRENT, OTHER]);
    vi.mocked(revokeAllSessions).mockResolvedValueOnce(undefined);
    vi.mocked(listSessions).mockResolvedValueOnce([CURRENT]);
    render(withIntl(<SessionsCard />));
    await waitFor(() => {
      expect(screen.getByText("Chrome · Windows")).toBeInTheDocument();
    });
    await user.click(
      screen.getByRole("button", { name: "Sign out everywhere else" }),
    );
    await waitFor(() => {
      expect(revokeAllSessions).toHaveBeenCalledOnce();
    });
  });

  it("disables the bulk CTA when only the current session is active", async () => {
    vi.mocked(listSessions).mockResolvedValue([CURRENT]);
    render(withIntl(<SessionsCard />));
    await waitFor(() => {
      expect(screen.getByText("Safari · macOS")).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: "Sign out everywhere else" }),
    ).toBeDisabled();
  });

  it("renders the empty state when the API returns no sessions", async () => {
    vi.mocked(listSessions).mockResolvedValue([]);
    render(withIntl(<SessionsCard />));
    await waitFor(() => {
      expect(
        screen.getByText("No active sessions on file."),
      ).toBeInTheDocument();
    });
  });
});
