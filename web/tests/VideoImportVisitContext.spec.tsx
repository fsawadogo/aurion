import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import VideoImportClient from "@/components/portal/VideoImportClient";
import { withIntl } from "./helpers/intl";

/**
 * TE-4d — the upload form drives template resolution through the clinician's
 * visit type + context (the same path iOS uses), and takes specialty from the
 * profile rather than a picker.
 *
 * These assert the WEB contract: what the form sends. The backend reuse of
 * `resolve_context_template_key` is covered in
 * `backend/tests/unit/test_te4d_video_import_visit_context.py`.
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

const PROFILE = {
  primary_specialty: "plastic_surgery",
  consultation_types: ["new_patient", "follow_up"],
  contexts_per_visit_type: {
    follow_up: [
      { id: "ctx_aaa", label: "Bunion post-op", template_key: null, template_ref: null },
      { id: "ctx_bbb", label: "Liposuction review", template_key: null, template_ref: null },
    ],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest =
    FakeXHR as unknown as typeof XMLHttpRequest;
  vi.mocked(listMyCustomTemplates).mockResolvedValue([]);
  vi.mocked(getMyProfile).mockResolvedValue(PROFILE as never);
  vi.mocked(getPortalFeatureFlags).mockResolvedValue({
    video_import_enabled: true,
    multi_clip_import_enabled: false,
  } as never);
  vi.mocked(createVideoImport).mockResolvedValue({
    session_id: "sess-1",
    upload_url: "https://s3.example/put",
  } as never);
  vi.mocked(processVideoImport).mockResolvedValue({} as never);
});

async function fillAndSubmit() {
  const user = userEvent.setup();
  const input = screen.getByTestId(
    "video-import-file-input",
  ) as HTMLInputElement;
  await user.upload(
    input,
    new File([new Uint8Array([1, 2, 3])], "encounter.mp4", {
      type: "video/mp4",
    }),
  );
  await user.click(screen.getByLabelText(/consent was obtained/i));
  await user.click(screen.getByRole("button", { name: /Upload & process/i }));
  await waitFor(() => expect(createVideoImport).toHaveBeenCalled());
  return vi.mocked(createVideoImport).mock.calls[0][0] as unknown as Record<
    string,
    unknown
  >;
}

describe("VideoImportClient — visit context → template (TE-4d)", () => {
  it("takes specialty from the profile, not a picker", async () => {
    render(withIntl(<VideoImportClient />));
    await waitFor(() => expect(getMyProfile).toHaveBeenCalled());

    // TE-4e — specialty is implied from the profile: no picker AND no
    // read-only field on the upload form (Uzziel: "no need to keep specialty
    // there, it's already implied from profile"). It still rides the request
    // from the profile, asserted below.
    expect(
      screen.queryByRole("combobox", { name: /specialty/i }),
    ).toBeNull();
    expect(
      screen.queryByTestId("video-import-specialty-readonly"),
    ).toBeNull();

    const body = await fillAndSubmit();
    expect(body.specialty).toBe("plastic_surgery"); // from PROFILE, not "general"
  });

  it("sends consultation_type + context_id when a visit context is picked", async () => {
    render(withIntl(<VideoImportClient />));
    await waitFor(() => expect(getMyProfile).toHaveBeenCalled());
    const user = userEvent.setup();

    await user.selectOptions(
      await screen.findByTestId("video-import-visit-type"),
      "follow_up",
    );
    // Context select appears only once a visit type with contexts is chosen.
    await user.selectOptions(
      await screen.findByTestId("video-import-visit-context"),
      "ctx_bbb",
    );

    const body = await fillAndSubmit();
    // AC-5 — the fields that trigger the backend resolver.
    expect(body.consultation_type).toBe("follow_up");
    expect(body.context_id).toBe("ctx_bbb");
    // …and no explicit template, so the backend resolves from the context.
    expect(body.custom_template_id ?? null).toBeNull();
  });

  it("omits visit fields when nothing is picked (specialty default)", async () => {
    render(withIntl(<VideoImportClient />));
    await waitFor(() => expect(getMyProfile).toHaveBeenCalled());

    const body = await fillAndSubmit();
    expect(body.consultation_type).toBeUndefined();
    expect(body.context_id).toBeUndefined();
  });

  it("hides the context select for a visit type with no contexts", async () => {
    render(withIntl(<VideoImportClient />));
    await waitFor(() => expect(getMyProfile).toHaveBeenCalled());
    const user = userEvent.setup();

    // new_patient has no contexts in PROFILE → no context select.
    await user.selectOptions(
      await screen.findByTestId("video-import-visit-type"),
      "new_patient",
    );
    expect(screen.queryByTestId("video-import-visit-context")).toBeNull();

    const body = await fillAndSubmit();
    // Visit type still sent (its default context / org default resolves it).
    expect(body.consultation_type).toBe("new_patient");
    expect(body.context_id).toBeUndefined();
  });
});
