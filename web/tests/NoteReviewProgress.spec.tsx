import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { withIntl } from "./helpers/intl";

/**
 * TE-4b — the note's actions must not read a note that is being replaced.
 *
 * Found by Uzziel on the first real prod upload. During regeneration the page
 * showed only a small grey caption while the body kept rendering the OLD note
 * at full opacity — and Print, Export and Copy were not disabled by anything.
 * A clinician could print or export mid-regeneration and walk away with the
 * version about to be discarded.
 *
 * The busy expression already existed (it was passed to every NoteSectionCard,
 * which is why inline editing WAS blocked) — the three action buttons were
 * simply never part of it. These tests pin the derived value against all three
 * unstable states so the next control added can't quietly miss it too.
 */

vi.mock("@/lib/use-route-segment", () => ({ useRouteSegment: () => "sess-1" }));
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
} from "@/lib/portal-api";
import { regenerateNote } from "@/lib/api";
import NoteReviewPage from "@/app/portal/notes/[id]/NoteReviewClient";

function detail(sessionState = "AWAITING_REVIEW") {
  return {
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
      session_state: sessionState,
    },
  };
}

const FLAGS = {
  video_import_enabled: false,
  multi_clip_import_enabled: false,
  cross_clinician_chart_enabled: false,
  template_authoring_chat_enabled: false,
  note_review_chat_enabled: false,
};

/**
 * Every control that READS the note — BOTH copy buttons.
 *
 * There are two: the toolbar "Copy" and the action rail's primary "Copy to
 * EHR" (the file's own stated primary action). An earlier version of this
 * helper matched only `/^Copy$/i`, which excludes "Copy to EHR" by
 * construction — so it passed while the primary button was wide open during
 * regeneration. Review caught it; the rail copy is now asserted explicitly.
 */
function actions() {
  return {
    print: screen.getByRole("button", { name: "Print" }),
    exportDocx: screen.getByRole("button", { name: /Export/i }),
    copyToolbar: screen.getByRole("button", { name: /^Copy$/i }),
    copyToEhr: screen.getByRole("button", { name: /Copy to EHR/i }),
    // The approve button's LABEL changes when blocked ("Approve & sign" →
    // "Resolve conflicts to approve"), so match either — otherwise the query
    // silently returns null in exactly the busy state we're testing.
    approve: screen.getByRole("button", {
      name: /Approve & sign|Resolve conflicts to approve/i,
    }),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getNoteDetail).mockResolvedValue(detail() as never);
  vi.mocked(getSession).mockResolvedValue({ state: "AWAITING_REVIEW" } as never);
  vi.mocked(listMyMacros).mockResolvedValue([] as never);
  vi.mocked(listMyCustomTemplates).mockResolvedValue([] as never);
  vi.mocked(getPortalFeatureFlags).mockResolvedValue(FLAGS as never);
});

describe("NoteReview — actions while the note is being replaced", () => {
  it("enables every action when the note is stable", async () => {
    render(withIntl(<NoteReviewPage />));
    await waitFor(() => expect(getNoteDetail).toHaveBeenCalled());

    const a = actions();
    expect(a.print).toBeEnabled();
    expect(a.exportDocx).toBeEnabled();
    expect(a.copyToolbar).toBeEnabled();
    expect(a.copyToEhr).toBeEnabled();
    expect(a.approve).toBeEnabled();
    expect(screen.getByTestId("note-document")).toHaveAttribute(
      "aria-busy",
      "false",
    );
  });

  it("blocks every action that reads the note while regenerating", async () => {
    // Hold the regenerate open so the busy state is observable.
    let release!: () => void;
    vi.mocked(regenerateNote).mockImplementation(
      () => new Promise<void>((res) => { release = res; }) as never,
    );

    render(withIntl(<NoteReviewPage />));
    await waitFor(() => expect(getNoteDetail).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /Français|French|FR/i }));
    await waitFor(() => expect(regenerateNote).toHaveBeenCalled());

    // AC-1 — the bug: every note-reading control was live during regeneration.
    // "Copy to EHR" is the PRIMARY one and was the review's HIGH finding — a
    // clinician could paste the about-to-be-discarded note into the chart.
    await waitFor(() => expect(actions().print).toBeDisabled());
    expect(actions().exportDocx).toBeDisabled();
    expect(actions().copyToolbar).toBeDisabled();
    expect(actions().copyToEhr).toBeDisabled();
    // …and approve must not race the in-flight Stage-1 replacement.
    expect(actions().approve).toBeDisabled();

    release();
  });

  it("marks the note body busy and shows a progress banner while regenerating", async () => {
    let release!: () => void;
    vi.mocked(regenerateNote).mockImplementation(
      () => new Promise<void>((res) => { release = res; }) as never,
    );

    render(withIntl(<NoteReviewPage />));
    await waitFor(() => expect(getNoteDetail).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /Français|French|FR/i }));

    // AC-3 + AC-4 — a sighted user sees motion + dimming; a screen-reader
    // user gets aria-busy and a polite live region. Before this, both got a
    // silent stale document.
    const banner = await screen.findByTestId("regenerating-banner");
    expect(banner).toHaveAttribute("role", "status");
    expect(banner).toHaveAttribute("aria-live", "polite");
    expect(screen.getByTestId("note-document")).toHaveAttribute(
      "aria-busy",
      "true",
    );

    release();
    await waitFor(() =>
      expect(screen.queryByTestId("regenerating-banner")).toBeNull(),
    );
  });

  it("blocks actions during Stage 2 too — one derived value, not three", async () => {
    // AC-2 — the point of deriving `noteBusy` once. Stage 2 rewrites the note
    // from the server side, so the same rule has to hold without anyone
    // remembering to add a second condition to three buttons.
    vi.mocked(getNoteDetail).mockResolvedValue(
      detail("PROCESSING_STAGE2") as never,
    );

    render(withIntl(<NoteReviewPage />));
    await waitFor(() => expect(getNoteDetail).toHaveBeenCalled());

    expect(actions().print).toBeDisabled();
    expect(actions().exportDocx).toBeDisabled();
    expect(actions().copyToolbar).toBeDisabled();
    expect(actions().copyToEhr).toBeDisabled();
    expect(actions().approve).toBeDisabled();
    expect(screen.getByTestId("note-document")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });
});

describe("NoteReview — print leak guard", () => {
  // Disabling the Print button blocks the in-app affordance, but Ctrl+P and
  // the browser menu call window.print() directly. jsdom cannot evaluate an
  // @media print block, so this asserts the source rule exists rather than
  // simulating a print — a regression guard against silently dropping it.
  it("hides a busy note document at print time", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const css = fs.readFileSync(
      path.resolve(__dirname, "../app/globals.css"),
      "utf-8",
    );
    const printBlock = css.slice(css.indexOf("@media print"));
    expect(printBlock).toMatch(/@media print/);
    expect(printBlock).toMatch(
      /\[data-testid="note-document"\]\[aria-busy="true"\][\s\S]*display:\s*none/,
    );
  });
});
