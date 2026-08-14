import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import VideoImportClient from "@/components/portal/VideoImportClient";

import { withIntl } from "./helpers/intl";

/**
 * VideoImportClient — multi-clip import (Slice 2).
 *
 * The portal + admin API modules are mocked at the boundary so the
 * upload/process pipeline never touches the network. We assert:
 *   * flag OFF  → single-file behaviour is unchanged (single input, no
 *     multiple attr, no ordered clip list) and one presigned PUT is used.
 *   * flag ON   → several files can be selected, appear as an ordered list,
 *     can be reordered, and the create call carries clip_count with each
 *     clip PUT fired in order.
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
  cancelVideoImport: vi.fn(),
  discardSession: vi.fn(),
}));

// Admin surface fns — imported by the component even on the clinician surface.
vi.mock("@/lib/api", () => ({
  createAdminVideoImport: vi.fn(),
  processAdminVideoImport: vi.fn(),
  getAdminVideoImportStatus: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import {
  createVideoImport,
  getPortalFeatureFlags,
  getMyProfile,
  listMyCustomTemplates,
  processVideoImport,
  getVideoImportStatus,
  cancelVideoImport,
  discardSession,
} from "@/lib/portal-api";

// Capture every raw S3 PUT (presigned upload). XHR is stubbed so no real
// network I/O happens and we can assert the per-clip upload order.
const putUrls: string[] = [];

class FakeXHR {
  static instances: FakeXHR[] = [];
  status = 200;
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private _url = "";
  open(_method: string, url: string) {
    this._url = url;
  }
  setRequestHeader() {}
  getResponseHeader() {
    return '"etag"';
  }
  send() {
    putUrls.push(this._url);
    // Fire progress then success on the next tick.
    setTimeout(() => {
      this.upload.onprogress?.({
        lengthComputable: true,
        loaded: 100,
        total: 100,
      } as ProgressEvent);
      this.onload?.();
    }, 0);
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  putUrls.length = 0;
  (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest =
    FakeXHR as unknown as typeof XMLHttpRequest;
  vi.mocked(listMyCustomTemplates).mockResolvedValue([]);
  vi.mocked(getMyProfile).mockResolvedValue({ primary_specialty: "general", consultation_types: [], contexts_per_visit_type: {} } as never);
  vi.mocked(processVideoImport).mockResolvedValue({} as never);
});

function mkFile(name: string): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: "video/mp4" });
}

describe("VideoImportClient — flag OFF (single file, unchanged)", () => {
  it("uses a single (non-multiple) input and no ordered clip list", async () => {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue({
      video_import_enabled: true,
      multi_clip_import_enabled: false,
    });
    render(withIntl(<VideoImportClient />));

    // Wait for the flag fetch to settle.
    await waitFor(() =>
      expect(vi.mocked(getPortalFeatureFlags)).toHaveBeenCalled(),
    );

    const input = screen.getByTestId(
      "video-import-file-input",
    ) as HTMLInputElement;
    expect(input.multiple).toBe(false);

    const user = userEvent.setup();
    await user.upload(input, [mkFile("a.mp4"), mkFile("b.mp4")]);

    // Only the first (single) file is retained; no ordered clip list renders.
    expect(screen.queryByTestId("video-import-clip-list")).toBeNull();
    expect(screen.getByText(/a\.mp4/)).toBeInTheDocument();
  });

  it("submits without clip_count and a single presigned PUT", async () => {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue({
      video_import_enabled: true,
      multi_clip_import_enabled: false,
    });
    vi.mocked(createVideoImport).mockResolvedValue({
      session_id: "s1",
      job_id: "j1",
      upload_url: "https://s3/one",
      s3_key: "k1",
    });
    render(withIntl(<VideoImportClient />));
    await waitFor(() =>
      expect(vi.mocked(getPortalFeatureFlags)).toHaveBeenCalled(),
    );

    const user = userEvent.setup();
    await user.upload(
      screen.getByTestId("video-import-file-input"),
      mkFile("a.mp4"),
    );
    await user.click(screen.getByLabelText(/consent was obtained/i));
    await user.click(screen.getByRole("button", { name: /Upload & process/i }));

    await waitFor(() =>
      expect(vi.mocked(processVideoImport)).toHaveBeenCalled(),
    );
    expect(vi.mocked(createVideoImport)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(createVideoImport).mock.calls[0][0]).not.toHaveProperty(
      "clip_count",
    );
    expect(putUrls).toEqual(["https://s3/one"]);
  });
});

describe("VideoImportClient — flag ON (multi-clip)", () => {
  it("selects several files, reorders them, and uploads each in order", async () => {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue({
      video_import_enabled: true,
      multi_clip_import_enabled: true,
    });
    vi.mocked(createVideoImport).mockResolvedValue({
      session_id: "s1",
      job_id: "j1",
      upload_url: "https://s3/clip0",
      s3_key: "k0",
      clips: [
        { index: 0, s3_key: "k0", upload_url: "https://s3/clip0" },
        { index: 1, s3_key: "k1", upload_url: "https://s3/clip1" },
      ],
    });
    render(withIntl(<VideoImportClient />));
    await waitFor(() =>
      expect(vi.mocked(getPortalFeatureFlags)).toHaveBeenCalled(),
    );

    const input = screen.getByTestId(
      "video-import-file-input",
    ) as HTMLInputElement;
    expect(input.multiple).toBe(true);

    const user = userEvent.setup();
    await user.upload(input, [mkFile("first.mp4"), mkFile("second.mp4")]);

    const list = await screen.findByTestId("video-import-clip-list");
    let rows = within(list).getAllByTestId("video-import-clip-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("first.mp4");
    expect(rows[1]).toHaveTextContent("second.mp4");

    // Reorder: move the second clip up -> order becomes second, first.
    await user.click(within(rows[1]).getByLabelText(/Move clip up/i));
    rows = within(list).getAllByTestId("video-import-clip-row");
    expect(rows[0]).toHaveTextContent("second.mp4");
    expect(rows[1]).toHaveTextContent("first.mp4");

    // Submit.
    await user.click(screen.getByLabelText(/consent was obtained/i));
    await user.click(screen.getByRole("button", { name: /Upload & process/i }));

    await waitFor(() =>
      expect(vi.mocked(processVideoImport)).toHaveBeenCalled(),
    );
    // clip_count reflects the file count.
    expect(vi.mocked(createVideoImport).mock.calls[0][0]).toMatchObject({
      clip_count: 2,
    });
    // Both presigned clip PUTs fired, in clips[index] order.
    expect(putUrls).toEqual(["https://s3/clip0", "https://s3/clip1"]);
  });

  it("removes a clip from the list", async () => {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue({
      video_import_enabled: true,
      multi_clip_import_enabled: true,
    });
    render(withIntl(<VideoImportClient />));
    await waitFor(() =>
      expect(vi.mocked(getPortalFeatureFlags)).toHaveBeenCalled(),
    );

    const user = userEvent.setup();
    await user.upload(screen.getByTestId("video-import-file-input"), [
      mkFile("first.mp4"),
      mkFile("second.mp4"),
    ]);

    const list = await screen.findByTestId("video-import-clip-list");
    const rows = within(list).getAllByTestId("video-import-clip-row");
    await user.click(within(rows[0]).getByLabelText(/Remove clip/i));

    expect(
      within(screen.getByTestId("video-import-clip-list")).getAllByTestId(
        "video-import-clip-row",
      ),
    ).toHaveLength(1);
    expect(screen.queryByText(/first\.mp4/)).toBeNull();
  });
});

describe("VideoImportClient — clinician visit-type → context flow (TE-4e)", () => {
  it("drops specialty + template pickers, prefills the context box, shows the resolved template, and sends context_id + encounter_context", async () => {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue({
      video_import_enabled: true,
      multi_clip_import_enabled: false,
    });
    // A profile whose "follow_up" visit type has one saved context, bound to a
    // custom template and carrying a saved note.
    vi.mocked(getMyProfile).mockResolvedValue({
      primary_specialty: "plastic_surgery",
      consultation_types: ["follow_up"],
      contexts_per_visit_type: {
        follow_up: [
          {
            id: "ctx_aaaa1111",
            label: "Bunion consult",
            template_key: null,
            template_ref: "tpl-1",
            description: "Left foot bunion, 6 weeks post-op",
          },
        ],
      },
    } as never);
    vi.mocked(listMyCustomTemplates).mockResolvedValue([
      { id: "tpl-1", display_name: "Ortho Follow-up" },
    ] as never);
    vi.mocked(createVideoImport).mockResolvedValue({
      session_id: "s1",
      job_id: "j1",
      upload_url: "https://s3/one",
      s3_key: "k1",
    });

    render(withIntl(<VideoImportClient />));
    const user = userEvent.setup();

    // The specialty field and the old standalone template dropdown are gone.
    const visitType = await screen.findByTestId("video-import-visit-type");
    expect(screen.queryByTestId("video-import-specialty-readonly")).toBeNull();
    expect(screen.queryByTestId("video-import-template")).toBeNull();

    // Pick the visit type → its context appears; pick the context.
    await user.selectOptions(visitType, "follow_up");
    const ctxSelect = await screen.findByTestId("video-import-visit-context");
    await user.selectOptions(ctxSelect, "ctx_aaaa1111");

    // The context box is prefilled with the context's saved note …
    const note = screen.getByTestId(
      "video-import-context-note",
    ) as HTMLTextAreaElement;
    expect(note.value).toBe("Left foot bunion, 6 weeks post-op");
    // … and the resolved template (from the context's ref) is shown.
    expect(await screen.findByText("Ortho Follow-up")).toBeInTheDocument();

    // Submit → create carries the visit type, context id, and the note as
    // encounter_context; no custom_template_id (template comes from context).
    await user.upload(
      screen.getByTestId("video-import-file-input"),
      mkFile("a.mp4"),
    );
    await user.click(screen.getByLabelText(/consent was obtained/i));
    await user.click(screen.getByRole("button", { name: /Upload & process/i }));

    await waitFor(() =>
      expect(vi.mocked(processVideoImport)).toHaveBeenCalled(),
    );
    const body = vi.mocked(createVideoImport).mock.calls[0][0];
    expect(body).toMatchObject({
      specialty: "plastic_surgery",
      consultation_type: "follow_up",
      context_id: "ctx_aaaa1111",
      encounter_context: "Left foot bunion, 6 weeks post-op",
    });
    expect(body).not.toHaveProperty("custom_template_id");
  });
});


describe("VideoImportClient — cancelling a wedged import", () => {
  /** Drive the form through to the `processing` phase. */
  async function reachProcessing(user: ReturnType<typeof userEvent.setup>) {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue({
      video_import_enabled: true,
      multi_clip_import_enabled: false,
    });
    vi.mocked(createVideoImport).mockResolvedValue({
      session_id: "sess-1",
      upload_url: "https://s3.example/put",
    } as never);
    // Keep the job "running" so the UI stays on the processing card.
    vi.mocked(getVideoImportStatus).mockResolvedValue({
      status: "running",
      session_state: "CONSENT_PENDING",
      frames_extracted: 0,
      frames_dropped: 0,
    } as never);

    render(withIntl(<VideoImportClient />));
    await waitFor(() =>
      expect(vi.mocked(getPortalFeatureFlags)).toHaveBeenCalled(),
    );
    await user.upload(
      screen.getByTestId("video-import-file-input") as HTMLInputElement,
      [mkFile("clip.mp4")],
    );
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /upload & process/i }));
    await waitFor(() =>
      expect(screen.getByTestId("cancel-processing")).toBeInTheDocument(),
    );
  }

  it("offers Retry when the server says the clip is still available", async () => {
    const user = userEvent.setup();
    vi.mocked(cancelVideoImport).mockResolvedValue({
      session_id: "sess-1",
      job_id: "job-1",
      status: "failed",
      retryable: true,
      retry_blocked_reason: null,
    });
    await reachProcessing(user);

    await user.click(screen.getByTestId("cancel-processing"));

    await waitFor(() =>
      expect(vi.mocked(cancelVideoImport)).toHaveBeenCalledWith("sess-1"),
    );
    expect(await screen.findByTestId("retry-processing")).toBeInTheDocument();
    expect(screen.getByTestId("start-over")).toBeInTheDocument();
  });

  it("hides Retry and shows the reason once the clip has been purged", async () => {
    const user = userEvent.setup();
    vi.mocked(cancelVideoImport).mockResolvedValue({
      session_id: "sess-1",
      job_id: "job-1",
      status: "failed",
      retryable: false,
      retry_blocked_reason: "Processing had already started on this recording.",
    });
    await reachProcessing(user);

    await user.click(screen.getByTestId("cancel-processing"));

    expect(await screen.findByTestId("start-over")).toBeInTheDocument();
    // A Retry here would 409 server-side, so it must not be offered.
    expect(screen.queryByTestId("retry-processing")).toBeNull();
    expect(
      screen.getByText(/already started on this recording/i),
    ).toBeInTheDocument();
  });

  it("Start over discards the session and returns to an empty form", async () => {
    const user = userEvent.setup();
    vi.mocked(cancelVideoImport).mockResolvedValue({
      session_id: "sess-1",
      job_id: "job-1",
      status: "failed",
      retryable: false,
      retry_blocked_reason: "The uploaded recording has already been deleted.",
    });
    vi.mocked(discardSession).mockResolvedValue(undefined);
    await reachProcessing(user);

    await user.click(screen.getByTestId("cancel-processing"));
    await user.click(await screen.findByTestId("start-over"));

    await waitFor(() =>
      expect(vi.mocked(discardSession)).toHaveBeenCalledWith("sess-1"),
    );
    expect(
      screen.getByTestId("video-import-file-input"),
    ).toBeInTheDocument();
  });
});
