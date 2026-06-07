import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CapturedMediaPage from "@/app/portal/media/page";
import type { CapturedMediaItem, CapturedMediaList, CurrentUser } from "@/types";
import { withIntl } from "./helpers/intl";

/**
 * Captured Media page (#338).
 *
 * Validates the role split + flag gating the backend enforces, mirrored
 * in the UI:
 *   - ADMIN/EVAL see download actions; COMPLIANCE_OFFICER does not.
 *   - A 403 from the (role-allowed) list call surfaces the "not enabled"
 *     state, never a raw error.
 *   - Rows carry NO patient identifier (only physician/context metadata).
 *
 * The API client is mocked at the module boundary so the page is
 * deterministic regardless of network state.
 */

vi.mock("@/lib/api", () => ({
  getCapturedMedia: vi.fn(),
  getMe: vi.fn(),
  getMediaDownloadUrls: vi.fn(),
}));

import { getCapturedMedia, getMe, getMediaDownloadUrls } from "@/lib/api";

function item(overrides: Partial<CapturedMediaItem> = {}): CapturedMediaItem {
  return {
    session_id: "11111111-1111-1111-1111-111111111111",
    physician_name: "Dr. Perry Gdalevitch",
    started_at: "2026-06-01T12:00:00+00:00",
    visit_type: "follow_up",
    context_label: "LL follow-up",
    encounter_type: "doctor_patient",
    state: "AWAITING_REVIEW",
    has_audio: true,
    clip_count: 2,
    retention_expires_at: "2099-01-01T00:00:00+00:00",
    ...overrides,
  };
}

function list(items: CapturedMediaItem[]): CapturedMediaList {
  return { items, total: items.length, page: 1, page_size: 50, retention_days: 7 };
}

function user(role: CurrentUser["role"]): CurrentUser {
  return {
    user_id: "u",
    email: "x@aurion.local",
    full_name: "X",
    role,
  } as CurrentUser;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CapturedMediaPage", () => {
  it("renders rows with physician + media availability for ADMIN", async () => {
    vi.mocked(getMe).mockResolvedValue(user("ADMIN"));
    vi.mocked(getCapturedMedia).mockResolvedValue(list([item()]));

    render(withIntl(<CapturedMediaPage />));

    expect(await screen.findByText("Dr. Perry Gdalevitch")).toBeInTheDocument();
    expect(screen.getByText("follow_up")).toBeInTheDocument();
    expect(screen.getByText("LL follow-up")).toBeInTheDocument();
    // Media column: audio label + "2 clips".
    expect(screen.getByText("Audio")).toBeInTheDocument();
    expect(screen.getByText("2 clips")).toBeInTheDocument();
    // ADMIN sees both download actions.
    expect(screen.getByRole("button", { name: /Download audio/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download clips/i })).toBeInTheDocument();
  });

  it("hides download actions for COMPLIANCE_OFFICER (view-only)", async () => {
    vi.mocked(getMe).mockResolvedValue(user("COMPLIANCE_OFFICER"));
    vi.mocked(getCapturedMedia).mockResolvedValue(list([item()]));

    render(withIntl(<CapturedMediaPage />));

    // The row still renders (compliance can VIEW).
    expect(await screen.findByText("Dr. Perry Gdalevitch")).toBeInTheDocument();
    // But no download buttons + a view-only note.
    expect(screen.queryByRole("button", { name: /Download audio/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Download clips/i })).toBeNull();
    expect(screen.getByText(/View only/i)).toBeInTheDocument();
  });

  it("shows the not-enabled state when the list call 403s", async () => {
    vi.mocked(getMe).mockResolvedValue(user("ADMIN"));
    vi.mocked(getCapturedMedia).mockRejectedValue(new Error("API 403: not enabled"));

    render(withIntl(<CapturedMediaPage />));

    expect(
      await screen.findByText(/Media retention is not enabled/i),
    ).toBeInTheDocument();
  });

  it("downloads audio via a presigned URL for ADMIN", async () => {
    vi.mocked(getMe).mockResolvedValue(user("ADMIN"));
    vi.mocked(getCapturedMedia).mockResolvedValue(list([item()]));
    vi.mocked(getMediaDownloadUrls).mockResolvedValue({
      audio_url: "https://signed.example/audio.wav",
      clips: [{ clip_id: "clip_1", url: "https://signed.example/c1.mp4" }],
      expires_in: 3600,
    });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    render(withIntl(<CapturedMediaPage />));
    const btn = await screen.findByRole("button", { name: /Download audio/i });
    await userEvent.click(btn);

    await waitFor(() =>
      expect(getMediaDownloadUrls).toHaveBeenCalledWith(
        "11111111-1111-1111-1111-111111111111",
      ),
    );
    expect(clickSpy).toHaveBeenCalled();
    clickSpy.mockRestore();
  });

  it("disables download buttons when no media is present", async () => {
    vi.mocked(getMe).mockResolvedValue(user("EVAL_TEAM"));
    vi.mocked(getCapturedMedia).mockResolvedValue(
      list([item({ has_audio: false, clip_count: 0 })]),
    );

    render(withIntl(<CapturedMediaPage />));
    await screen.findByText("Dr. Perry Gdalevitch");
    expect(screen.getByText("None")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download audio/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Download clips/i })).toBeDisabled();
  });
});
