import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { withIntl } from "./helpers/intl";

// This spec exercises the two integration points the isolation test can't:
// the `chatEnabled` flag gate and `onAssist` (assistNote → re-fetch on applied).
// The heavy child cards/panes (each fetches on mount) are stubbed to null — the
// real NoteAssistChat is left unmocked so the gate + wiring are genuinely tested.
vi.mock("@/lib/use-route-segment", () => ({ useRouteSegment: () => "sess-1" }));
// loop-4: the page now calls regenerateNote (template/language switch) and
// catches RegenerateDiscardError on the 409 loss gate. Provide both; the class
// is defined inside the factory (vi.mock is hoisted — no outer references) and
// must be real so the `instanceof` in doRegenerate works.
vi.mock("@/lib/api", () => {
  class RegenerateDiscardError extends Error {
    wouldDiscard: Record<string, number>;
    constructor(wouldDiscard: Record<string, number>) {
      super("would discard");
      this.name = "RegenerateDiscardError";
      this.wouldDiscard = wouldDiscard;
    }
  }
  return {
    humanizeError: (_e: unknown, fb: string) => fb,
    regenerateNote: vi.fn(),
    RegenerateDiscardError,
  };
});
vi.mock("@/components/portal/OrdersCard", () => ({ default: () => null }));
vi.mock("@/components/portal/PatientSummaryCard", () => ({ default: () => null }));
vi.mock("@/components/portal/CodingSuggestionsCard", () => ({ default: () => null }));
vi.mock("@/components/portal/EmrWriteBackCard", () => ({ default: () => null }));
vi.mock("@/components/portal/PreviewVsFinalCard", () => ({ default: () => null }));
vi.mock("@/components/portal/EncounterAudioCard", () => ({ default: () => null }));
vi.mock("@/components/portal/LivePreviewCard", () => ({ default: () => null }));
vi.mock("@/components/portal/NoteContextBadge", () => ({ default: () => null }));
vi.mock("@/components/portal/PageHeader", () => ({ default: () => null }));
vi.mock("@/components/portal/PatientIdentifierEditor", () => ({ default: () => null }));
vi.mock("@/components/portal/StageTwoProgressBanner", () => ({ default: () => null }));
vi.mock("@/components/portal/NoteSectionCard", () => ({ default: () => null }));
vi.mock("@/components/portal/CompletenessRing", () => ({ default: () => null }));
vi.mock("@/components/portal/TranscriptPane", async () => {
  const React = await import("react");
  return { default: React.forwardRef(() => null) };
});
vi.mock("@/lib/portal-api", () => ({
  getNoteDetail: vi.fn(),
  getSession: vi.fn(),
  listMyMacros: vi.fn(),
  listMyCustomTemplates: vi.fn(),
  getPortalFeatureFlags: vi.fn(),
  getMyProfile: vi.fn(),
  assistNote: vi.fn(),
  approveAll: vi.fn(),
  editNote: vi.fn(),
  exportNote: vi.fn(),
  resolveConflict: vi.fn(),
}));

import {
  getNoteDetail,
  getSession,
  listMyMacros,
  listMyCustomTemplates,
  getPortalFeatureFlags,
  getMyProfile,
  assistNote,
} from "@/lib/portal-api";
import { regenerateNote } from "@/lib/api";
import NoteReviewPage from "@/app/portal/notes/[id]/NoteReviewClient";

const DETAIL = {
  note: {
    session_id: "sess-1",
    stage: 1,
    version: 1,
    provider_used: "anthropic",
    specialty: "general",
    completeness_score: 1,
    sections: [],
    created_at: "2026-07-01T00:00:00Z",
  },
  citations: {},
  conflict_state: {
    has_unresolved: false,
    unresolved_count: 0,
    unresolved_section_ids: [],
    unresolved_claim_ids: [],
  },
  export_metadata: {
    latest_version: 1,
    is_approved: false,
    can_export: true,
    session_state: "AWAITING_REVIEW",
  },
};

const PLACEHOLDER = "Ask, edit, or fix anything…";

function flags(noteReview: boolean) {
  return {
    video_import_enabled: false,
    multi_clip_import_enabled: false,
    cross_clinician_chart_enabled: false,
    template_authoring_chat_enabled: false,
    note_review_chat_enabled: noteReview,
  };
}

describe("NoteReviewPage — fix-this-note chat wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getNoteDetail).mockResolvedValue(DETAIL as never);
    vi.mocked(getSession).mockResolvedValue({ state: "AWAITING_REVIEW" } as never);
    vi.mocked(listMyMacros).mockResolvedValue([] as never);
    vi.mocked(listMyCustomTemplates).mockResolvedValue([] as never);
    vi.mocked(getMyProfile).mockResolvedValue({ primary_specialty: "general" } as never);
  });

  it("hides the chat when note_review_chat_enabled is off (fails closed)", async () => {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue(flags(false) as never);
    render(withIntl(<NoteReviewPage />));
    await waitFor(() => expect(getNoteDetail).toHaveBeenCalled());
    expect(screen.queryByText("Fix this note")).toBeNull();
  });

  it("shows the chat when on and re-fetches the note after an applied edit", async () => {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue(flags(true) as never);
    vi.mocked(assistNote).mockResolvedValue({
      assistant_message: "Shortened.",
      applied: true,
      note: DETAIL.note,
    } as never);
    render(withIntl(<NoteReviewPage />));

    expect(await screen.findByText("Fix this note")).toBeTruthy();
    expect(getNoteDetail).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByPlaceholderText(PLACEHOLDER), {
      target: { value: "shorten" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(assistNote).toHaveBeenCalledWith("sess-1", "shorten"),
    );
    // applied=true → onAssist calls load() again to re-sync citations/etc.
    await waitFor(() => expect(getNoteDetail).toHaveBeenCalledTimes(2));
  });

  it("does NOT re-fetch when the assist turn is conversational (applied=false)", async () => {
    vi.mocked(getPortalFeatureFlags).mockResolvedValue(flags(true) as never);
    vi.mocked(assistNote).mockResolvedValue({
      assistant_message: "Which section?",
      applied: false,
      note: DETAIL.note,
    } as never);
    render(withIntl(<NoteReviewPage />));

    await screen.findByText("Fix this note");
    fireEvent.change(screen.getByPlaceholderText(PLACEHOLDER), {
      target: { value: "hmm" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(assistNote).toHaveBeenCalled());
    expect(screen.getByText("Which section?")).toBeTruthy();
    expect(getNoteDetail).toHaveBeenCalledTimes(1); // no re-fetch
  });
});

describe("NoteReviewPage — loop-4 copy + regenerate wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getNoteDetail).mockResolvedValue(DETAIL as never);
    vi.mocked(getSession).mockResolvedValue({ state: "AWAITING_REVIEW" } as never);
    vi.mocked(listMyMacros).mockResolvedValue([] as never);
    vi.mocked(listMyCustomTemplates).mockResolvedValue([] as never);
    vi.mocked(getPortalFeatureFlags).mockResolvedValue(flags(false) as never);
    vi.mocked(getMyProfile).mockResolvedValue({ primary_specialty: "orthopedic_surgery" } as never);
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("Copy writes the full note to the clipboard — not gated on approval", async () => {
    render(withIntl(<NoteReviewPage />));
    // Two Copy affordances (toolbar + rail); the toolbar one is unambiguous.
    const copyBtn = await screen.findByText("Copy");
    fireEvent.click(copyBtn);
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalled(),
    );
    // DETAIL is an unapproved AWAITING_REVIEW note — copy still fired.
    expect(DETAIL.export_metadata.is_approved).toBe(false);
  });

  it("changing the template regenerates the note", async () => {
    vi.mocked(regenerateNote).mockResolvedValue({
      version: 2,
      stage: 1,
      completeness_score: 1,
      provider_used: "anthropic",
    } as never);
    render(withIntl(<NoteReviewPage />));
    const select = await screen.findByLabelText("Note template");
    fireEvent.change(select, { target: { value: "orthopedic_surgery" } });
    await waitFor(() =>
      expect(regenerateNote).toHaveBeenCalledWith("sess-1", {
        template_key: "orthopedic_surgery",
      }),
    );
  });

  it("the template dropdown offers only my specialty default + custom, not the 8 built-ins (TE-4e)", async () => {
    render(withIntl(<NoteReviewPage />));
    // getMyProfile → orthopedic_surgery, so the only specialty option is the
    // clinician's own default; the flat 8-specialty list is gone.
    expect(
      await screen.findByRole("option", { name: /my specialty default/i }),
    ).toBeTruthy();
    expect(screen.queryByRole("option", { name: /plastic surgery/i })).toBeNull();
    expect(screen.queryByRole("option", { name: /family medicine/i })).toBeNull();
  });

  it("a language switch that hits the loss gate confirms, then retries with confirm_discard", async () => {
    const { RegenerateDiscardError } = await import("@/lib/api");
    vi.mocked(regenerateNote)
      .mockRejectedValueOnce(
        new (RegenerateDiscardError as unknown as new (
          c: Record<string, number>,
        ) => Error)({ visual_claims: 2 } as Record<string, number>),
      )
      .mockResolvedValueOnce({
        version: 3,
        stage: 1,
        completeness_score: 1,
        provider_used: "anthropic",
      } as never);
    render(withIntl(<NoteReviewPage />));

    fireEvent.click(await screen.findByText("Français"));
    // First call carries no confirm — the 409 surfaces the confirm prompt.
    await waitFor(() =>
      expect(regenerateNote).toHaveBeenCalledWith("sess-1", {
        output_language: "fr",
      }),
    );
    const confirm = await screen.findByText("Regenerate anyway");
    fireEvent.click(confirm);
    // Second call carries confirm_discard so the backend proceeds.
    await waitFor(() =>
      expect(regenerateNote).toHaveBeenCalledWith("sess-1", {
        output_language: "fr",
        confirm_discard: true,
      }),
    );
  });
});
