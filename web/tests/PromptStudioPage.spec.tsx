import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PromptStudioPage from "@/app/portal/admin/prompt-studio/page";
import { withIntl } from "./helpers/intl";

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    body: string;
    constructor(status: number, body: string) {
      super(body);
      this.status = status;
      this.body = body;
    }
  },
  humanizeError: (_e: unknown, fallback: string) => fallback,
  getStudioJobs: vi.fn(),
  listStudioPrompts: vi.fn(),
  getStudioPrompt: vi.fn(),
  createStudioPrompt: vi.fn(),
  saveStudioVersion: vi.fn(),
  publishStudioPrompt: vi.fn(),
}));

import {
  ApiError,
  createStudioPrompt,
  getStudioJobs,
  getStudioPrompt,
  listStudioPrompts,
  publishStudioPrompt,
} from "@/lib/api";

const JOBS = [
  {
    job_id: "note_generation",
    name: "Note generation",
    system_prompt: "Document only what was observed. Do not interpret.",
  },
];
const PROMPTS = [
  {
    id: "p1",
    job_id: "note_generation",
    name: "Tighter PE",
    latest_version_no: 1,
    created_at: "2026-06-24T00:00:00Z",
  },
];
const DETAIL = {
  id: "p1",
  job_id: "note_generation",
  name: "Tighter PE",
  created_at: "2026-06-24T00:00:00Z",
  versions: [
    {
      id: "v1",
      version_no: 1,
      text: "Document only what was observed.",
      created_at: "2026-06-24T00:00:00Z",
    },
  ],
};

beforeEach(() => {
  vi.mocked(getStudioJobs).mockResolvedValue(JOBS);
  vi.mocked(listStudioPrompts).mockResolvedValue(PROMPTS);
  vi.mocked(getStudioPrompt).mockResolvedValue(DETAIL);
  vi.mocked(createStudioPrompt).mockReset();
  vi.mocked(publishStudioPrompt).mockReset();
});

describe("PromptStudioPage", () => {
  it("renders the header and lists authored prompts", async () => {
    render(withIntl(<PromptStudioPage />));
    expect(screen.getByText("Prompt Studio")).toBeInTheDocument();
    expect(screen.getByTestId("create-prompt-button")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("prompt-row-p1")).toBeInTheDocument(),
    );
  });

  it("creates a new prompt from the modal (job prefills the text)", async () => {
    const user = userEvent.setup();
    vi.mocked(createStudioPrompt).mockResolvedValue(DETAIL);
    render(withIntl(<PromptStudioPage />));

    await user.click(screen.getByTestId("create-prompt-button"));
    await user.type(screen.getByTestId("create-name-input"), "My prompt");
    await user.selectOptions(
      screen.getByTestId("create-job-select"),
      "note_generation",
    );
    await user.click(screen.getByTestId("create-submit"));

    await waitFor(() => expect(createStudioPrompt).toHaveBeenCalledTimes(1));
    const body = vi.mocked(createStudioPrompt).mock.calls[0][0];
    expect(body.job_id).toBe("note_generation");
    expect(body.name).toBe("My prompt");
    expect(body.text).toContain("Document only");
  });

  it("publishes the selected prompt's latest version to ALL", async () => {
    const user = userEvent.setup();
    vi.mocked(publishStudioPrompt).mockResolvedValue({
      id: "pub1",
      job_id: "note_generation",
      version_id: "v1",
      version_no: 1,
      scope: "ALL",
      target_role: null,
      target_user_id: null,
      published_at: "2026-06-24T00:00:00Z",
    });
    render(withIntl(<PromptStudioPage />));

    await waitFor(() =>
      expect(screen.getByTestId("prompt-row-p1")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("prompt-row-p1"));
    await waitFor(() =>
      expect(screen.getByTestId("publish-button")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("publish-button"));

    await waitFor(() => expect(publishStudioPrompt).toHaveBeenCalledTimes(1));
    const [id, body] = vi.mocked(publishStudioPrompt).mock.calls[0];
    expect(id).toBe("p1");
    expect(body.scope).toBe("ALL");
    expect(body.version_id).toBe("v1");
  });

  it("shows the not-enabled state when the gate 403s (flag off)", async () => {
    vi.mocked(getStudioJobs).mockRejectedValue(
      new ApiError(403, "Prompt Studio is not enabled."),
    );
    vi.mocked(listStudioPrompts).mockRejectedValue(
      new ApiError(403, "Prompt Studio is not enabled."),
    );
    render(withIntl(<PromptStudioPage />));

    await waitFor(() =>
      expect(screen.getByTestId("prompt-studio-disabled")).toBeInTheDocument(),
    );
    // A 403 is "feature off", not an error or a permission scare — the create
    // button and the red error banner are both suppressed.
    expect(screen.queryByTestId("create-prompt-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("prompt-studio-error")).not.toBeInTheDocument();
  });
});
