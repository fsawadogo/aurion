import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { withIntl } from "./helpers/intl";

// Mark the chip + conflict sub-components so we can assert their presence
// without depending on their internals.
vi.mock("@/components/portal/ClaimChip", () => ({
  default: () => <span data-testid="claim-chip" />,
}));
vi.mock("@/components/portal/ConflictResolver", () => ({
  default: () => <div data-testid="conflict-resolver" />,
}));

import NoteSectionCard from "@/components/portal/NoteSectionCard";
import type { NoteSection } from "@/types";

const SECTION: NoteSection = {
  id: "hpi",
  title: "History of present illness",
  status: "populated",
  claims: [
    { id: "c1", text: "Gradual onset, no injury.", source_type: "transcript", source_id: "seg_1", source_quote: "", physician_edited: false },
    { id: "c2", text: "Morning stiffness ~20 minutes.", source_type: "transcript", source_id: "seg_2", source_quote: "", physician_edited: false },
  ],
} as never;

const noop = async () => {};

function renderCard(props: Partial<Parameters<typeof NoteSectionCard>[0]> = {}) {
  return render(
    withIntl(
      <NoteSectionCard
        section={SECTION}
        citations={{}}
        onSaveEdit={noop}
        onResolveConflict={noop}
        {...props}
      />,
    ),
  );
}

describe("NoteSectionCard — document variant (loop-4)", () => {
  it("renders every claim, chrome-less, with no citation chips when citations are off", () => {
    const { container } = renderCard({ variant: "document", showCitations: false });
    expect(screen.getByText("Gradual onset, no injury.")).toBeTruthy();
    expect(screen.getByText("Morning stiffness ~20 minutes.")).toBeTruthy();
    // No card chrome in document mode…
    expect(container.querySelector(".border-gray-200")).toBeNull();
    // …and no chips when citations are off (day-1 note is clean).
    expect(screen.queryByTestId("claim-chip")).toBeNull();
  });

  it("keeps the bordered card + chips in the default variant (unchanged)", () => {
    const { container } = renderCard();
    expect(container.querySelector(".border-gray-200")).not.toBeNull();
    expect(screen.getAllByTestId("claim-chip").length).toBe(2);
  });

  it("shows 'Not captured.' for an empty section in document mode", () => {
    renderCard({
      variant: "document",
      showCitations: false,
      section: { ...SECTION, claims: [] } as never,
    });
    expect(screen.getByText("Not captured.")).toBeTruthy();
  });
});
