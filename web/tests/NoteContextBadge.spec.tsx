import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import NoteContextBadge from "@/components/portal/NoteContextBadge";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import { withIntl } from "./helpers/intl";

/**
 * #61 full slice — "Context-aware" badge that appears in the note
 * review header when Stage 1 actually consumed prior encounters into
 * the LLM prompt. Web mirror of the iOS ``contextAwareBadgeOrNil``
 * view; same visibility rule + same navigation destination.
 */

// next/link renders to an anchor in tests without mocking; the
// component's href routes to /portal/patients/{identifier}.

describe("NoteContextBadge", () => {
  it("renders when encountersReferenced > 0 and an identifier is set", () => {
    render(
      withIntl(
        <NoteContextBadge
          encountersReferenced={3}
          identifier="MRN-123"
        />,
      ),
    );
    const badge = screen.getByTestId("note-context-badge");
    expect(badge).toBeInTheDocument();
    // The chip's visible "Context-aware" label comes from the i18n
    // catalog — assert it lands rendered, not the bare key.
    expect(screen.getByText(/Context-aware/i)).toBeInTheDocument();
    // The plural-aware count string.
    expect(screen.getByText(/3 prior visits/i)).toBeInTheDocument();
    // Anchor routes to the patient detail page with the identifier
    // URL-encoded.
    expect(badge.getAttribute("href")).toBe(
      "/portal/patients/MRN-123",
    );
  });

  it("renders with singular form when encountersReferenced is 1", () => {
    render(
      withIntl(
        <NoteContextBadge
          encountersReferenced={1}
          identifier="MRN-123"
        />,
      ),
    );
    expect(screen.getByText(/1 prior visit$/i)).toBeInTheDocument();
  });

  it("hides itself when encountersReferenced is 0", () => {
    const { container } = render(
      withIntl(
        <NoteContextBadge
          encountersReferenced={0}
          identifier="MRN-123"
        />,
      ),
    );
    expect(container.firstChild).toBeNull();
    expect(
      screen.queryByTestId("note-context-badge"),
    ).not.toBeInTheDocument();
  });

  it("hides itself when the identifier is null (cold-start session)", () => {
    const { container } = render(
      withIntl(
        <NoteContextBadge
          encountersReferenced={3}
          identifier={null}
        />,
      ),
    );
    expect(container.firstChild).toBeNull();
  });

  it("hides itself when the identifier is an empty string", () => {
    const { container } = render(
      withIntl(
        <NoteContextBadge
          encountersReferenced={3}
          identifier=""
        />,
      ),
    );
    expect(container.firstChild).toBeNull();
  });

  it("URL-encodes identifiers that contain reserved characters", () => {
    render(
      withIntl(
        <NoteContextBadge
          encountersReferenced={2}
          // RAMQ-style identifiers carry uppercase letters + digits;
          // we also exercise a slash to lock the encodeURIComponent
          // path that would otherwise let the value blow out of its
          // path segment.
          identifier="ABCD/01234567"
        />,
      ),
    );
    const badge = screen.getByTestId("note-context-badge");
    expect(badge.getAttribute("href")).toBe(
      "/portal/patients/ABCD%2F01234567",
    );
  });

  it("renders the French label when locale is fr", () => {
    render(
      withIntl(
        <NoteContextBadge
          encountersReferenced={2}
          identifier="MRN-123"
        />,
        "fr",
      ),
    );
    // The FR catalog uses "Contexte intégré" for badge.contextAware.
    expect(screen.getByText(/Contexte intégré/i)).toBeInTheDocument();
  });
});

// i18n catalog parity — every key the component reaches into must
// exist in both en + fr. The component lives or dies by these three.
describe("NoteContextBadge — i18n catalog parity", () => {
  const requiredKeys: Array<keyof typeof enMessages.LongitudinalContext.badge> = [
    "contextAware",
    "priorVisitsCount",
    "tapToView",
  ];

  it("EN catalog carries every key the component reads", () => {
    for (const key of requiredKeys) {
      expect(enMessages.LongitudinalContext.badge[key]).toBeTruthy();
    }
  });

  it("FR catalog carries every key the component reads", () => {
    for (const key of requiredKeys) {
      expect(frMessages.LongitudinalContext.badge[key]).toBeTruthy();
    }
  });
});
