import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import FeatureFlagsPage from "@/app/portal/admin/feature-flags/page";
import { FLAG_GROUPS } from "@/app/portal/admin/feature-flags/flagGroups";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import { withIntl } from "./helpers/intl";

/**
 * /portal/admin/feature-flags — TE-3b.
 *
 * TE-2 (#663) and TE-3 (#664) shipped the template engine behind
 * `template_engine_enabled`, which defaults to false and had no portal
 * control — so the engine was merged and unreachable. This covers the
 * toggle that makes it reachable, plus the drift class that would have
 * shipped it broken.
 *
 * The page's `FLAG_GROUPS` is a deliberate ALLOWLIST, not an incomplete
 * rendering of FeatureFlagsConfig: most flags are read-only here because
 * they gate pipeline behaviour or aren't booleans. So the fix for a
 * missing flag is a data entry, and the guard against forgetting one of
 * its four coordinated edits is the catalog test below.
 */

vi.mock("@/lib/api", () => ({
  getFeatureFlags: vi.fn(),
  updateFeatureFlags: vi.fn(),
  humanizeError: (_e: unknown, fallback: string) => fallback,
}));

import { getFeatureFlags, updateFeatureFlags } from "@/lib/api";

/** A full snapshot — the page round-trips every key it doesn't own. */
const FLAGS = {
  screen_capture_enabled: true,
  note_versioning_enabled: true,
  session_pause_resume_enabled: true,
  per_session_provider_override: true,
  orders_card_enabled: false,
  coding_card_enabled: false,
  patient_summary_card_enabled: false,
  emr_writeback_card_enabled: false,
  media_review_retention_enabled: false,
  measurement_enabled: false,
  video_import_enabled: true,
  multi_clip_import_enabled: false,
  note_options_enabled: false,
  video_import_drop_zero_face_frames: false,
  specialty_style_in_prompt_enabled: false,
  grounded_synthesis_enabled: false,
  template_engine_enabled: false,
  prompt_studio_enabled: true,
  prompt_studio_roles: ["ADMIN"],
  clinician_prompts_note_only: false,
  template_authoring_chat_enabled: false,
  note_review_chat_enabled: false,
} as const;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getFeatureFlags).mockResolvedValue({ ...FLAGS } as never);
  vi.mocked(updateFeatureFlags).mockResolvedValue({
    feature_flags: { ...FLAGS, template_engine_enabled: true },
    appconfig_version: 42,
  } as never);
});

describe("Feature Flags page — template engine toggle", () => {
  it("renders the template engine toggle reflecting the loaded value", async () => {
    render(withIntl(<FeatureFlagsPage />));

    const toggle = await screen.findByRole("switch", {
      name: /Template engine/i,
    });
    // AC-1 — loaded value is false, so the switch reads off.
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("warns that the engine is unproven rather than reading as a neutral switch", async () => {
    render(withIntl(<FeatureFlagsPage />));
    await screen.findByRole("switch", { name: /Template engine/i });

    // AC-4 — an admin flipping this must know what they're opting into.
    // `grounded_synthesis_enabled` sets the precedent for this copy.
    expect(
      screen.getByText(/Unproven/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Leave OFF until the eval receipt is green/i),
    ).toBeInTheDocument();
  });

  it("saves the template engine flag without disturbing the others", async () => {
    render(withIntl(<FeatureFlagsPage />));

    const toggle = await screen.findByRole("switch", {
      name: /Template engine/i,
    });
    fireEvent.click(toggle);

    const save = screen.getByRole("button", { name: /^Save/i });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);

    await waitFor(() => expect(updateFeatureFlags).toHaveBeenCalledTimes(1));

    // AC-2 — the flipped flag goes up…
    const sent = vi.mocked(updateFeatureFlags).mock.calls[0][0] as Record<
      string,
      unknown
    >;
    expect(sent.template_engine_enabled).toBe(true);

    // …and every other key round-trips verbatim, including the non-boolean
    // `prompt_studio_roles` the page never owns.
    for (const [key, value] of Object.entries(FLAGS)) {
      if (key === "template_engine_enabled") continue;
      expect(sent[key]).toEqual(value);
    }
  });

  it("renders at FR parity", async () => {
    render(withIntl(<FeatureFlagsPage />, "fr"));

    expect(
      await screen.findByRole("switch", { name: /Moteur de modèles/i }),
    ).toBeInTheDocument();
  });
});

describe("Feature Flags page — catalog drift guard", () => {
  /**
   * Adding a backend flag needs four coordinated edits (type, FLAG_GROUPS,
   * en.json, fr.json) and nothing enforced it. A group added without its
   * strings does NOT crash — next-intl resolves a missing key to the key
   * path — so the card would have shipped reading "FeatureFlags.templateEngine"
   * in the UI. The existing i18n parity test catches EN-only drift but not
   * a key missing from BOTH catalogs.
   */
  it("every FLAG_GROUPS key resolves in both catalogs", async () => {
    // Imports the REAL FLAG_GROUPS. An earlier draft of this test kept its
    // own copy of the list, which would have tracked nothing — a group added
    // to the page but not to the test would pass while shipping a card
    // titled "FeatureFlags.newGroup".
    expect(FLAG_GROUPS.length).toBeGreaterThan(0);

    for (const catalog of [enMessages, frMessages]) {
      const ff = catalog.FeatureFlags as Record<string, unknown> & {
        flags: Record<string, { name: string; description: string }>;
      };
      for (const group of FLAG_GROUPS) {
        expect(ff[group.titleKey], `group title ${group.titleKey}`).toBeTruthy();
        expect(ff[`${group.titleKey}Hint`], `group hint ${group.titleKey}Hint`).toBeTruthy();
        for (const flag of group.flags) {
          expect(ff.flags[flag]?.name, `${flag}.name`).toBeTruthy();
          expect(ff.flags[flag]?.description, `${flag}.description`).toBeTruthy();
        }
      }
    }
  });

  it("the page renders one card per group, with no unresolved i18n keys", async () => {
    const { container } = render(withIntl(<FeatureFlagsPage />));
    await screen.findByRole("switch", { name: /Template engine/i });

    // A missing key renders as the literal path — the failure mode this
    // whole guard exists for.
    expect(container.textContent).not.toMatch(/FeatureFlags\./);
  });
});
