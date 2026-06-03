import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ClaimChip from "@/components/portal/ClaimChip";
import type { CitationExpansion, Claim } from "@/types";
import { withIntl } from "./helpers/intl";

/**
 * P1-FU-WEB-CLIPS — ClaimChip clip-kind branch.
 *
 * Verifies the additive clip-kind behaviour without disturbing the
 * existing frame / transcript / screen / physician_edit paths. Each
 * test isolates one acceptance criterion from the plan.
 */

const VISUAL_CLAIM: Claim = {
  id: "claim_001",
  text: "Tender medial joint line on palpation.",
  source_type: "visual",
  source_id: "frame_00214_clip",
  source_quote: "Frame @ 14s",
};

const CLIP_CITATION: CitationExpansion = {
  source_type: "visual",
  source_id: "frame_00214_clip",
  frame_timestamp_ms: 14_500,
  frame_s3_key: "clips/abc/frame_00214_clip.mp4",
  evidence_kind: "clip",
  duration_ms: 7000,
  clip_url: "https://s3.example.com/clip.mp4?X-Amz-Signature=abc",
};

const FRAME_CITATION: CitationExpansion = {
  source_type: "visual",
  source_id: "frame_00214",
  frame_timestamp_ms: 14_500,
  frame_s3_key: "frames/abc/frame_00214.jpg",
  evidence_kind: "frame",
  duration_ms: null,
  clip_url: null,
};

const FRAME_CLAIM: Claim = {
  ...VISUAL_CLAIM,
  source_id: "frame_00214",
};

describe("ClaimChip — clip-kind overlay (AC-1, AC-2)", () => {
  it("renders the Play overlay when evidence_kind is clip", () => {
    render(
      withIntl(<ClaimChip claim={VISUAL_CLAIM} citation={CLIP_CITATION} />),
    );
    expect(screen.getByTestId("clip-chip-play-overlay")).toBeInTheDocument();
  });

  it("does NOT render the Play overlay for frame-kind visual citations", () => {
    render(
      withIntl(<ClaimChip claim={FRAME_CLAIM} citation={FRAME_CITATION} />),
    );
    expect(screen.queryByTestId("clip-chip-play-overlay")).not.toBeInTheDocument();
  });

  it("does NOT render the Play overlay for non-visual claims", () => {
    const transcriptClaim: Claim = {
      id: "claim_002",
      text: "Patient reports knee pain.",
      source_type: "transcript",
      source_id: "seg_001",
      source_quote: "knee pain since last week",
    };
    render(
      withIntl(<ClaimChip claim={transcriptClaim} citation={undefined} />),
    );
    expect(screen.queryByTestId("clip-chip-play-overlay")).not.toBeInTheDocument();
  });

  it("guards against malformed payloads (clip evidence_kind on non-visual)", () => {
    // A defensive case: the backend shouldn't emit this combo, but if
    // it does, the chip must not render the play overlay (would let
    // users tap into a modal with no clip).
    const bogusCitation: CitationExpansion = {
      source_type: "transcript",
      source_id: "seg_001",
      evidence_kind: "clip",
      clip_url: "https://example.com/clip.mp4",
    };
    const transcriptClaim: Claim = {
      id: "claim_003",
      text: "Hi.",
      source_type: "transcript",
      source_id: "seg_001",
      source_quote: "",
    };
    render(withIntl(<ClaimChip claim={transcriptClaim} citation={bogusCitation} />));
    expect(screen.queryByTestId("clip-chip-play-overlay")).not.toBeInTheDocument();
  });
});

describe("ClaimChip — click semantics (AC-3)", () => {
  it("opens the FullClipModal on click when clip-kind", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      withIntl(
        <ClaimChip
          claim={VISUAL_CLAIM}
          citation={CLIP_CITATION}
          onClick={onClick}
        />,
      ),
    );
    await user.click(screen.getByTestId("claim-chip-clip"));
    // Clip-kind diverts to the modal — the transcript-jump callback
    // does NOT fire so the parent's selected-source state isn't
    // perturbed mid-playback.
    expect(onClick).not.toHaveBeenCalled();
    expect(screen.getByTestId("clip-modal-content")).toBeInTheDocument();
  });

  it("fires onClick (transcript jump) on frame-kind clicks", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      withIntl(
        <ClaimChip
          claim={FRAME_CLAIM}
          citation={FRAME_CITATION}
          onClick={onClick}
        />,
      ),
    );
    await user.click(screen.getByTestId("claim-chip-visual"));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("clip-modal-content")).not.toBeInTheDocument();
  });
});

describe("ClaimChip — accessibility", () => {
  it("labels clip chips with 'clip' so screen readers announce the affordance", () => {
    render(
      withIntl(<ClaimChip claim={VISUAL_CLAIM} citation={CLIP_CITATION} />),
    );
    const btn = screen.getByTestId("claim-chip-clip");
    expect(btn).toHaveAttribute("aria-label", expect.stringContaining("clip"));
  });

  it("leaves the play overlay aria-hidden — the parent button carries the label", () => {
    render(
      withIntl(<ClaimChip claim={VISUAL_CLAIM} citation={CLIP_CITATION} />),
    );
    expect(screen.getByTestId("clip-chip-play-overlay")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });
});

// A minimal "click outside" smoke test for the chip → modal handoff,
// since fireEvent on the backdrop drives the same close path the
// modal-level spec exercises in more detail.
describe("ClaimChip — modal close handoff", () => {
  it("closes the modal when the backdrop is clicked", () => {
    render(
      withIntl(<ClaimChip claim={VISUAL_CLAIM} citation={CLIP_CITATION} />),
    );
    fireEvent.click(screen.getByTestId("claim-chip-clip"));
    expect(screen.getByTestId("clip-modal-content")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("clip-modal-backdrop"));
    expect(screen.queryByTestId("clip-modal-content")).not.toBeInTheDocument();
  });
});
