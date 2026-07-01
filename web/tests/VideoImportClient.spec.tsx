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
  listMyCustomTemplates: vi.fn(),
  createVideoImport: vi.fn(),
  processVideoImport: vi.fn(),
  getVideoImportStatus: vi.fn(),
  startVideoImportMultipart: vi.fn(),
  completeVideoImportMultipart: vi.fn(),
  abortVideoImportMultipart: vi.fn(),
}));

// Admin surface fns — imported by the component even on the clinician surface.
vi.mock("@/lib/api", () => ({
  createAdminVideoImport: vi.fn(),
  processAdminVideoImport: vi.fn(),
  getAdminVideoImportStatus: vi.fn(),
}));

import {
  createVideoImport,
  getPortalFeatureFlags,
  listMyCustomTemplates,
  processVideoImport,
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
