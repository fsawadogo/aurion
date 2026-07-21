import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import VideoImportClient from "@/components/portal/VideoImportClient";
import { withIntl } from "./helpers/intl";

/**
 * TE-4b — the processing stepper has to look alive.
 *
 * Found by Uzziel on the first real prod upload: the active stage was a
 * STATIC gold dot, so "Extracting audio" on a real encounter video — minutes
 * of legitimate work — rendered pixel-identical to a hung page. The import
 * was healthy and the note was produced; the UI simply never said so.
 *
 * Polling failure is a different concern and is already handled
 * (`lib/poll.ts` gives up after 5 consecutive errors and points at My Notes).
 * This is only about showing that work is in progress.
 */

vi.mock("@/lib/portal-api", () => ({
  getPortalFeatureFlags: vi.fn(),
  getMyProfile: vi.fn(),
  listMyCustomTemplates: vi.fn(),
  createVideoImport: vi.fn(),
  processVideoImport: vi.fn(),
  getVideoImportStatus: vi.fn(),
  startVideoImportMultipart: vi.fn(),
  completeVideoImportMultipart: vi.fn(),
  abortVideoImportMultipart: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  createAdminVideoImport: vi.fn(),
  processAdminVideoImport: vi.fn(),
  getAdminVideoImportStatus: vi.fn(),
}));

import {
  createVideoImport,
  getPortalFeatureFlags,
  getMyProfile,
  getVideoImportStatus,
  listMyCustomTemplates,
  processVideoImport,
} from "@/lib/portal-api";

class FakeXHR {
  status = 200;
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  getResponseHeader() {
    return '"etag"';
  }
  send() {
    setTimeout(() => this.onload?.(), 0);
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest =
    FakeXHR as unknown as typeof XMLHttpRequest;
  vi.mocked(listMyCustomTemplates).mockResolvedValue([]);
  vi.mocked(getMyProfile).mockResolvedValue({ primary_specialty: "general", consultation_types: [], contexts_per_visit_type: {} } as never);
  vi.mocked(getPortalFeatureFlags).mockResolvedValue({
    video_import_enabled: true,
    multi_clip_import_enabled: false,
  } as never);
  vi.mocked(createVideoImport).mockResolvedValue({
    session_id: "sess-1",
    upload_url: "https://s3.example/put",
  } as never);
  vi.mocked(processVideoImport).mockResolvedValue({} as never);
  // Park the job mid-pipeline — the exact state that looked frozen.
  vi.mocked(getVideoImportStatus).mockResolvedValue({
    status: "running",
    session_state: "PROCESSING_STAGE1",
  } as never);
});

async function startAnImport() {
  render(withIntl(<VideoImportClient />));
  await waitFor(() => expect(getPortalFeatureFlags).toHaveBeenCalled());

  const input = screen.getByTestId(
    "video-import-file-input",
  ) as HTMLInputElement;
  const user = userEvent.setup();
  await user.upload(
    input,
    new File([new Uint8Array([1, 2, 3])], "encounter.mp4", {
      type: "video/mp4",
    }),
  );
  // Consent is a hard gate on this surface — the button stays inert without it.
  await user.click(screen.getByLabelText(/consent was obtained/i));
  await user.click(screen.getByRole("button", { name: /Upload & process/i }));
  await waitFor(() => expect(createVideoImport).toHaveBeenCalled());
}

describe("VideoImportClient — the processing stepper shows motion", () => {
  it("animates the active stage so a slow stage is not a dead page", async () => {
    await startAnImport();

    // AC-5 — the whole bug in one assertion: before this the active dot
    // carried no animation class at all, so minutes of real work were
    // indistinguishable from a crash.
    const dot = await screen.findByTestId("active-stage-dot");
    expect(dot.className).toContain("animate-aurion-pulse");
  });

  it("shows an elapsed time that advances", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await startAnImport();
      await screen.findByTestId("active-stage-dot");

      await vi.advanceTimersByTimeAsync(3000);
      const first = (await screen.findByTestId("elapsed")).textContent;
      expect(first).toMatch(/0:0\d/);

      await vi.advanceTimersByTimeAsync(60000);
      const later = screen.getByTestId("elapsed").textContent;
      expect(later).not.toEqual(first);
      expect(later).toMatch(/1:0\d/);
    } finally {
      vi.useRealTimers();
    }
  });
});
