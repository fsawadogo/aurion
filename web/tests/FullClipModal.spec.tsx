import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import FullClipModal from "@/components/portal/FullClipModal";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import { withIntl } from "./helpers/intl";

/**
 * P1-FU-WEB-CLIPS — FullClipModal behaviour + i18n parity.
 *
 * Verifies the modal's video / empty-state branches plus the three
 * close affordances (button, Escape, backdrop). i18n parity is
 * asserted by spot-checking the FR + EN catalogs for the modal's
 * five strings.
 */

describe("FullClipModal — video rendering (AC-4)", () => {
  it("renders a <video> element with the signed clip URL", () => {
    const onClose = vi.fn();
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4?sig=abc"
          timestampMs={14_500}
          durationMs={7000}
          onClose={onClose}
        />,
      ),
    );
    const video = screen.getByTestId("clip-modal-video") as HTMLVideoElement;
    expect(video).toBeInTheDocument();
    expect(video.tagName.toLowerCase()).toBe("video");
    expect(video).toHaveAttribute("src", "https://example.com/clip.mp4?sig=abc");
    expect(video).toHaveAttribute("controls");
  });

  it("renders the M:SS timestamp in the header", () => {
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4"
          timestampMs={14_500} // 0:14
          durationMs={7000}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(screen.getByText("0:14")).toBeInTheDocument();
  });

  it("renders the duration pill formatted to one decimal", () => {
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4"
          timestampMs={14_500}
          durationMs={7500}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(screen.getByText("7.5s")).toBeInTheDocument();
  });

  it("hides the duration pill when durationMs is 0 or null", () => {
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4"
          timestampMs={14_500}
          durationMs={null}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(screen.queryByText(/\d+\.\ds/)).not.toBeInTheDocument();
  });
});

describe("FullClipModal — empty state (AC-5)", () => {
  it("renders the localized unavailable copy when clipUrl is null", () => {
    render(
      withIntl(
        <FullClipModal
          clipUrl={null}
          timestampMs={14_500}
          durationMs={7000}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(screen.queryByTestId("clip-modal-video")).not.toBeInTheDocument();
    expect(screen.getByTestId("clip-modal-unavailable")).toHaveTextContent(
      "Clip not yet available. The note may still be processing.",
    );
  });

  it("renders the FR unavailable copy when the FR catalog is active", () => {
    render(
      withIntl(
        <FullClipModal
          clipUrl={null}
          timestampMs={14_500}
          durationMs={7000}
          onClose={vi.fn()}
        />,
        "fr",
      ),
    );
    expect(screen.getByTestId("clip-modal-unavailable")).toHaveTextContent(
      "Clip non disponible pour l’instant. La note est peut-être encore en traitement.",
    );
  });

  it("renders unavailable when clipUrl is empty string", () => {
    render(
      withIntl(
        <FullClipModal
          clipUrl=""
          timestampMs={14_500}
          durationMs={7000}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(screen.queryByTestId("clip-modal-video")).not.toBeInTheDocument();
    expect(screen.getByTestId("clip-modal-unavailable")).toBeInTheDocument();
  });
});

describe("FullClipModal — close affordances (AC-6, AC-7)", () => {
  it("Escape key closes the modal", () => {
    const onClose = vi.fn();
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4"
          timestampMs={14_500}
          durationMs={7000}
          onClose={onClose}
        />,
      ),
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("backdrop click closes the modal", () => {
    const onClose = vi.fn();
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4"
          timestampMs={14_500}
          durationMs={7000}
          onClose={onClose}
        />,
      ),
    );
    fireEvent.click(screen.getByTestId("clip-modal-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("inner content click does NOT close the modal", () => {
    const onClose = vi.fn();
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4"
          timestampMs={14_500}
          durationMs={7000}
          onClose={onClose}
        />,
      ),
    );
    fireEvent.click(screen.getByTestId("clip-modal-content"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Close button click closes the modal", () => {
    const onClose = vi.fn();
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4"
          timestampMs={14_500}
          durationMs={7000}
          onClose={onClose}
        />,
      ),
    );
    // The button's accessible name comes from the aria-label
    // (= the localized "Close").
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("FullClipModal — dialog semantics", () => {
  it("uses role=dialog + aria-modal so screen readers trap focus", () => {
    render(
      withIntl(
        <FullClipModal
          clipUrl="https://example.com/clip.mp4"
          timestampMs={14_500}
          durationMs={7000}
          onClose={vi.fn()}
        />,
      ),
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "clip-modal-title");
  });
});

describe("ClipModal i18n catalog parity (AC-8)", () => {
  const REQUIRED_KEYS = [
    "title",
    "duration",
    "close",
    "unavailable",
    "controls",
  ] as const;

  it("EN catalog has every ClipModal key", () => {
    const en = enMessages.ClipModal as Record<string, string>;
    for (const k of REQUIRED_KEYS) {
      expect(en).toHaveProperty(k);
      expect(typeof en[k]).toBe("string");
      expect(en[k].length).toBeGreaterThan(0);
    }
  });

  it("FR catalog has every ClipModal key", () => {
    const fr = frMessages.ClipModal as Record<string, string>;
    for (const k of REQUIRED_KEYS) {
      expect(fr).toHaveProperty(k);
      expect(typeof fr[k]).toBe("string");
      expect(fr[k].length).toBeGreaterThan(0);
    }
  });

  it("EN and FR ClipModal keys are at parity (no English bleed in FR)", () => {
    const en = enMessages.ClipModal as Record<string, string>;
    const fr = frMessages.ClipModal as Record<string, string>;
    // Catalog parity: same key set both sides.
    expect(Object.keys(en).sort()).toEqual(Object.keys(fr).sort());
    // FR must not be the EN string verbatim — caught by spot-checking
    // a couple of distinctively-translated keys.
    expect(fr.close).not.toBe(en.close); // "Fermer" vs "Close"
    expect(fr.title).not.toBe(en.title); // "Clip vidéo" vs "Video clip"
  });
});
