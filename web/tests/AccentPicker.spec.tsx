import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { withIntl } from "./helpers/intl";

/**
 * #418 accent visual slice.
 *
 *   AC-1  picker renders 5 swatches; clicking one persists the palette
 *         key (updateMyProfile) and swaps the live DOM (data-accent).
 *   AC-2  the apply mechanism (used by the Sidebar profile-sync on load)
 *         sets data-accent for a stored non-default accent.
 *   AC-3  the default "gold" renders with NO data-accent override, so an
 *         existing user's DOM is byte-identical to before this slice.
 */

vi.mock("@/lib/portal-api", () => ({
  updateMyProfile: vi.fn(),
}));

import AccentPicker from "@/components/portal/AccentPicker";
import { applyAccent, ACCENT_KEYS, ACCENT_SWATCH } from "@/lib/accent";
import { updateMyProfile } from "@/lib/portal-api";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(updateMyProfile).mockResolvedValue({} as never);
  delete document.documentElement.dataset.accent;
});

afterEach(() => {
  delete document.documentElement.dataset.accent;
});

describe("applyAccent — DOM mechanism (AC-2 / AC-3)", () => {
  it("clears data-accent for the gold default (byte-identical render)", () => {
    document.documentElement.dataset.accent = "teal"; // stale value
    applyAccent("gold");
    expect(document.documentElement.dataset.accent).toBeUndefined();
  });

  it("sets data-accent for a stored non-default accent", () => {
    applyAccent("indigo");
    expect(document.documentElement.dataset.accent).toBe("indigo");
  });

  it("falls back to clearing for unknown / nullish values", () => {
    document.documentElement.dataset.accent = "rose";
    applyAccent("chartreuse"); // not in the curated palette
    expect(document.documentElement.dataset.accent).toBeUndefined();
    document.documentElement.dataset.accent = "rose";
    applyAccent(null);
    expect(document.documentElement.dataset.accent).toBeUndefined();
  });
});

describe("AccentPicker (AC-1)", () => {
  it("renders one swatch per curated palette key", () => {
    render(withIntl(<AccentPicker value="gold" />));
    for (const key of ACCENT_KEYS) {
      expect(screen.getByTestId(`accent-swatch-${key}`)).toBeInTheDocument();
    }
    expect(ACCENT_KEYS).toHaveLength(5);
  });

  it("marks the current value as the checked swatch", () => {
    render(withIntl(<AccentPicker value="gold" />));
    expect(screen.getByTestId("accent-swatch-gold")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByTestId("accent-swatch-teal")).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("persists the picked key and swaps the live DOM", async () => {
    const onChange = vi.fn();
    render(withIntl(<AccentPicker value="gold" onChange={onChange} />));

    fireEvent.click(screen.getByTestId("accent-swatch-teal"));

    await waitFor(() =>
      expect(updateMyProfile).toHaveBeenCalledWith({ accent_color: "teal" }),
    );
    expect(document.documentElement.dataset.accent).toBe("teal");
    expect(onChange).toHaveBeenCalledWith("teal");
  });

  it("clears the override when the user picks gold back", async () => {
    render(withIntl(<AccentPicker value="rose" />));
    // rose is the seeded selection; the DOM starts with no attr (the
    // picker only flips on click), so apply gold explicitly via a click.
    fireEvent.click(screen.getByTestId("accent-swatch-rose")); // no-op (same)
    fireEvent.click(screen.getByTestId("accent-swatch-gold"));

    await waitFor(() =>
      expect(updateMyProfile).toHaveBeenCalledWith({ accent_color: "gold" }),
    );
    expect(document.documentElement.dataset.accent).toBeUndefined();
  });

  it("does not persist when re-picking the already-selected swatch", () => {
    render(withIntl(<AccentPicker value="gold" />));
    fireEvent.click(screen.getByTestId("accent-swatch-gold"));
    expect(updateMyProfile).not.toHaveBeenCalled();
  });
});

describe("AccentPicker — FR catalog parity", () => {
  it("renders with the FR swatch labels", () => {
    render(withIntl(<AccentPicker value="gold" />, "fr"));
    // "Or" is the FR label for gold; assert it resolved (no MISSING_MESSAGE).
    expect(screen.getByTestId("accent-swatch-gold")).toHaveAttribute(
      "title",
      "Or",
    );
  });
});

describe("palette parity across layers", () => {
  // Guards against the key list drifting between ACCENT_KEYS, the swatch
  // hex map, and the EN/FR i18n catalogs (the CSS data-accent blocks and
  // backend _ACCENT_PALETTE are separate trust boundaries, asserted
  // elsewhere). If a key is added to ACCENT_KEYS, this fails until every
  // layer here has a matching entry.
  it("every ACCENT_KEY has a swatch hex + EN/FR label", () => {
    const enSwatch = (enMessages as Record<string, any>).Profile.accent.swatch;
    const frSwatch = (frMessages as Record<string, any>).Profile.accent.swatch;
    for (const key of ACCENT_KEYS) {
      expect(ACCENT_SWATCH[key]).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(enSwatch[key]).toBeTruthy();
      expect(frSwatch[key]).toBeTruthy();
    }
  });

  it("has no orphan swatch labels beyond the curated keys", () => {
    const enSwatch = (enMessages as Record<string, any>).Profile.accent.swatch;
    expect(Object.keys(enSwatch).sort()).toEqual([...ACCENT_KEYS].sort());
  });
});
