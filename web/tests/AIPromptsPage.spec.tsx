import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AIPromptsPage from "@/app/portal/prompts/page";
import PromptCard from "@/components/portal/PromptCard";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { AIPrompt } from "@/types";
import { withIntl } from "./helpers/intl";
import { ApiError } from "@/lib/api";

/**
 * AI-PROMPTS-A — Transparency page.
 *
 * Validates the read-only page renders the registry contents the
 * backend returns, supports search filtering, and exposes the system
 * prompt text on demand. Also catches FR/EN catalog drift so a future
 * sidebar entry can't ship in one locale and not the other.
 *
 * The API client is mocked at the module boundary; the page should
 * be deterministic regardless of network state.
 */

vi.mock("@/lib/portal-api", () => ({
  listMyPrompts: vi.fn(),
  getSpecialtyPrompts: vi.fn(),
  saveSpecialtyGuidance: vi.fn(),
  clearSpecialtyGuidance: vi.fn(),
}));

import {
  clearSpecialtyGuidance,
  getSpecialtyPrompts,
  listMyPrompts,
  saveSpecialtyGuidance,
} from "@/lib/portal-api";
import type { SpecialtyPrompt } from "@/types";

// Helper — every default-only fixture has active_prompt == system_prompt
// (the server contract when no user prompt is set — replacement
// semantics: system_prompt is the fallback).
function basePrompt<
  T extends Omit<
    AIPrompt,
    | "user_prompt_text"
    | "is_overridden"
    | "active_prompt"
    | "system_prompt_is_fallback"
  >,
>(p: T): AIPrompt {
  return {
    ...p,
    user_prompt_text: null,
    is_overridden: false,
    system_prompt_is_fallback: true,
    active_prompt: p.system_prompt,
  };
}

const NOTE_GEN: AIPrompt = basePrompt({
  id: "note_generation",
  name: "Note generation",
  purpose: "Drafts the SOAP note from the audio transcript.",
  category: "note",
  runs_when: "After the recording stops, before review.",
  provider_field: "note_generation",
  system_prompt:
    "You are a clinical documentation assistant for Aurion Clinical AI. Describe only what was directly captured. Do not infer.",
  schema_note: "Output: strict JSON.",
});

const VISION_FRAME: AIPrompt = basePrompt({
  id: "vision_frame",
  name: "Vision (still frame)",
  purpose: "Describes what is visible in a still frame.",
  category: "vision",
  runs_when: "Stage 2 frame captioning.",
  provider_field: "vision",
  system_prompt:
    "You are a clinical visual documentation assistant. Describe only what is literally visible.",
  schema_note: "Output: JSON description + confidence.",
});

const PATIENT_SUMMARY: AIPrompt = basePrompt({
  id: "patient_summary",
  name: "Patient after-visit summary",
  purpose: "Plain-language handout for the patient.",
  category: "extraction",
  runs_when: "After note approval.",
  provider_field: "note_generation",
  system_prompt: "You are an after-visit summary writer.",
  schema_note: "Output: single paragraph.",
});

const LIVE_PREVIEW: AIPrompt = basePrompt({
  id: "live_preview",
  name: "Live note preview",
  purpose: "Rolling draft during recording.",
  category: "preview",
  runs_when: "Every few seconds during recording.",
  provider_field: "note_generation",
  system_prompt: "Stage 0 note draft system prompt.",
  schema_note: null,
});

const MOCK_PROMPTS = [NOTE_GEN, VISION_FRAME, PATIENT_SUMMARY, LIVE_PREVIEW];

const DEFAULT_GUIDANCE =
  "Style: document the exam in the order the physician follows.";

function specialtyFixture(
  over: Partial<SpecialtyPrompt> = {},
): SpecialtyPrompt {
  return {
    key: "orthopedic_surgery",
    display_name: "Orthopedic Surgery",
    guidance: DEFAULT_GUIDANCE,
    user_guidance: null,
    is_overridden: false,
    active_guidance: DEFAULT_GUIDANCE,
    enabled: true,
    sections: [
      {
        id: "physical_exam",
        title: "Physical Examination",
        required: true,
        description: "ROM in degrees, 0-5 strength, named special tests.",
        visual_trigger_keywords: ["Lachman", "McMurray"],
      },
    ],
    examples: [
      { description: "right knee pain", populated_sections: ["physical_exam"] },
    ],
    examples_count: 1,
    ...over,
  };
}

const MOCK_SPECIALTIES: SpecialtyPrompt[] = [specialtyFixture()];

beforeEach(() => {
  vi.mocked(listMyPrompts).mockResolvedValue(MOCK_PROMPTS);
  vi.mocked(getSpecialtyPrompts).mockResolvedValue(MOCK_SPECIALTIES);
  vi.mocked(saveSpecialtyGuidance).mockReset();
  vi.mocked(clearSpecialtyGuidance).mockReset();
});

describe("AIPromptsPage — page shell + load (AC-7)", () => {
  it("renders the page title + descriptive-mode callout", async () => {
    render(withIntl(<AIPromptsPage />));
    expect(screen.getByText("AI Prompts")).toBeInTheDocument();
    expect(
      screen.getByTestId("descriptive-mode-callout"),
    ).toBeInTheDocument();
  });

  it("loads prompts from the API and renders one card per entry", async () => {
    render(withIntl(<AIPromptsPage />));
    await waitFor(() => {
      expect(
        screen.getByTestId("prompt-card-note_generation-name"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("prompt-card-vision_frame-name"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("prompt-card-patient_summary-name"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("prompt-card-live_preview-name"),
    ).toBeInTheDocument();
  });

  it("groups cards into category sections", async () => {
    render(withIntl(<AIPromptsPage />));
    await waitFor(() => {
      expect(
        screen.getByTestId("prompts-category-note"),
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId("prompts-category-vision")).toBeInTheDocument();
    expect(
      screen.getByTestId("prompts-category-extraction"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("prompts-category-preview"),
    ).toBeInTheDocument();
  });
});

describe("AIPromptsPage — search filter (AC-7)", () => {
  it("narrows the visible cards when the filter matches a prompt name", async () => {
    const user = userEvent.setup();
    render(withIntl(<AIPromptsPage />));
    await waitFor(() =>
      expect(
        screen.getByTestId("prompt-card-note_generation-name"),
      ).toBeInTheDocument(),
    );

    await user.type(
      screen.getByTestId("prompts-filter-input"),
      "vision",
    );

    expect(
      screen.queryByTestId("prompt-card-note_generation-name"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("prompt-card-vision_frame-name"),
    ).toBeInTheDocument();
  });

  it("filters by purpose text, not just name", async () => {
    const user = userEvent.setup();
    render(withIntl(<AIPromptsPage />));
    await waitFor(() =>
      expect(
        screen.getByTestId("prompt-card-patient_summary-name"),
      ).toBeInTheDocument(),
    );

    await user.type(
      screen.getByTestId("prompts-filter-input"),
      "handout",
    );

    expect(
      screen.getByTestId("prompt-card-patient_summary-name"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("prompt-card-note_generation-name"),
    ).not.toBeInTheDocument();
  });

  it("shows a no-results state when nothing matches", async () => {
    const user = userEvent.setup();
    render(withIntl(<AIPromptsPage />));
    await waitFor(() =>
      expect(
        screen.getByTestId("prompt-card-note_generation-name"),
      ).toBeInTheDocument(),
    );

    await user.type(
      screen.getByTestId("prompts-filter-input"),
      "completely-bogus-needle-xyz",
    );

    expect(screen.getByTestId("prompts-no-results")).toBeInTheDocument();
  });
});

describe("AIPromptsPage — by-specialty view (AC-7)", () => {
  it("switches to the specialty view and renders one card per specialty", async () => {
    const user = userEvent.setup();
    render(withIntl(<AIPromptsPage />));
    await waitFor(() =>
      expect(
        screen.getByTestId("prompt-card-note_generation-name"),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("prompts-view-specialty"));

    expect(screen.getByTestId("prompts-by-specialty")).toBeInTheDocument();
    expect(
      screen.getByTestId("specialty-card-orthopedic_surgery"),
    ).toBeInTheDocument();
    // Global category sections are no longer mounted in this view.
    expect(
      screen.queryByTestId("prompts-category-note"),
    ).not.toBeInTheDocument();
  });

  it("surfaces the specialty guidance, sections, and example summaries", async () => {
    const user = userEvent.setup();
    render(withIntl(<AIPromptsPage />));
    await waitFor(() =>
      expect(
        screen.getByTestId("prompt-card-note_generation-name"),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("prompts-view-specialty"));

    expect(screen.getByText("Orthopedic Surgery")).toBeInTheDocument();
    expect(
      screen.getByText(/document the exam in the order/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Physical Examination")).toBeInTheDocument();
    expect(screen.getByText("Lachman")).toBeInTheDocument();
    expect(screen.getByText(/right knee pain/i)).toBeInTheDocument();
  });

  it("filters specialties by display name", async () => {
    const user = userEvent.setup();
    render(withIntl(<AIPromptsPage />));
    await waitFor(() =>
      expect(
        screen.getByTestId("prompt-card-note_generation-name"),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("prompts-view-specialty"));
    await user.type(
      screen.getByTestId("prompts-filter-input"),
      "completely-bogus-needle-xyz",
    );

    expect(screen.getByTestId("prompts-no-results")).toBeInTheDocument();
    expect(
      screen.queryByTestId("specialty-card-orthopedic_surgery"),
    ).not.toBeInTheDocument();
  });
});

describe("AIPromptsPage — by-specialty guidance editing", () => {
  async function gotoSpecialtyView() {
    const user = userEvent.setup();
    render(withIntl(<AIPromptsPage />));
    await waitFor(() =>
      expect(
        screen.getByTestId("prompt-card-note_generation-name"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("prompts-view-specialty"));
    return user;
  }

  it("opens an editor pre-filled with the active guidance", async () => {
    const user = await gotoSpecialtyView();
    await user.click(
      screen.getByTestId("specialty-card-orthopedic_surgery-edit"),
    );
    const box = screen.getByTestId(
      "specialty-guidance-input-orthopedic_surgery",
    ) as HTMLTextAreaElement;
    expect(box.value).toBe(DEFAULT_GUIDANCE);
  });

  it("saves an edited guidance and reflects the override", async () => {
    vi.mocked(saveSpecialtyGuidance).mockResolvedValue(
      specialtyFixture({
        user_guidance: "Lead with the chief complaint as stated.",
        is_overridden: true,
        active_guidance: "Lead with the chief complaint as stated.",
      }),
    );
    const user = await gotoSpecialtyView();
    await user.click(
      screen.getByTestId("specialty-card-orthopedic_surgery-edit"),
    );
    const box = screen.getByTestId(
      "specialty-guidance-input-orthopedic_surgery",
    );
    await user.clear(box);
    await user.type(box, "Lead with the chief complaint as stated.");
    await user.click(
      screen.getByTestId("specialty-guidance-save-orthopedic_surgery"),
    );

    await waitFor(() =>
      expect(saveSpecialtyGuidance).toHaveBeenCalledWith(
        "orthopedic_surgery",
        "Lead with the chief complaint as stated.",
      ),
    );
    expect(
      screen.getByTestId("specialty-card-orthopedic_surgery-override-badge"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Lead with the chief complaint as stated."),
    ).toBeInTheDocument();
  });

  it("surfaces a banlist 400 inline without losing the draft", async () => {
    vi.mocked(saveSpecialtyGuidance).mockRejectedValue(
      new ApiError(
        400,
        JSON.stringify({
          detail: {
            message: "Your guidance contains a banned phrase.",
            code: "banned_phrase",
            matched_phrase: "interpret the findings",
          },
        }),
      ),
    );
    const user = await gotoSpecialtyView();
    await user.click(
      screen.getByTestId("specialty-card-orthopedic_surgery-edit"),
    );
    const box = screen.getByTestId(
      "specialty-guidance-input-orthopedic_surgery",
    );
    await user.clear(box);
    await user.type(box, "Interpret the findings.");
    await user.click(
      screen.getByTestId("specialty-guidance-save-orthopedic_surgery"),
    );

    const err = await screen.findByTestId(
      "specialty-guidance-error-orthopedic_surgery",
    );
    expect(err.textContent).toContain("interpret the findings");
    // Editor stays open with the draft preserved.
    expect(
      (screen.getByTestId(
        "specialty-guidance-input-orthopedic_surgery",
      ) as HTMLTextAreaElement).value,
    ).toBe("Interpret the findings.");
  });

  it("clears an override back to the default", async () => {
    vi.mocked(getSpecialtyPrompts).mockResolvedValue([
      specialtyFixture({
        user_guidance: "My custom text.",
        is_overridden: true,
        active_guidance: "My custom text.",
      }),
    ]);
    vi.mocked(clearSpecialtyGuidance).mockResolvedValue(specialtyFixture());
    const user = await gotoSpecialtyView();
    await user.click(
      screen.getByTestId("specialty-card-orthopedic_surgery-edit"),
    );
    await user.click(
      screen.getByTestId("specialty-guidance-clear-orthopedic_surgery"),
    );
    await waitFor(() =>
      expect(clearSpecialtyGuidance).toHaveBeenCalledWith("orthopedic_surgery"),
    );
    expect(
      screen.queryByTestId(
        "specialty-card-orthopedic_surgery-override-badge",
      ),
    ).not.toBeInTheDocument();
  });

  it("warns when the specialty layer is not wired into live notes", async () => {
    vi.mocked(getSpecialtyPrompts).mockResolvedValue([
      specialtyFixture({ enabled: false }),
    ]);
    await gotoSpecialtyView();
    expect(
      screen.getByTestId("specialty-card-orthopedic_surgery-inactive"),
    ).toBeInTheDocument();
  });
});

describe("PromptCard — expand toggle exposes the exact system prompt (AC-7)", () => {
  it("hides the system prompt by default", () => {
    render(withIntl(<PromptCard prompt={NOTE_GEN} />));
    expect(
      screen.queryByTestId("prompt-card-note_generation-pre"),
    ).not.toBeInTheDocument();
  });

  it("shows the system prompt text after toggling expand", async () => {
    const user = userEvent.setup();
    render(withIntl(<PromptCard prompt={NOTE_GEN} />));
    await user.click(
      screen.getByTestId("prompt-card-note_generation-toggle"),
    );
    const pre = screen.getByTestId("prompt-card-note_generation-pre");
    expect(pre).toBeInTheDocument();
    expect(pre.textContent).toContain("Describe only what was directly captured");
  });

  it("renders the Edit preferences button on every card (Phase B)", () => {
    render(withIntl(<PromptCard prompt={NOTE_GEN} />));
    expect(
      screen.getByTestId("prompt-card-note_generation-edit-button"),
    ).toBeInTheDocument();
  });

  it("renders the override-active badge ONLY when is_overridden=true", () => {
    const { unmount } = render(withIntl(<PromptCard prompt={NOTE_GEN} />));
    expect(
      screen.queryByTestId("prompt-card-note_generation-override-badge"),
    ).toBeNull();
    unmount();
    // Under replacement semantics: when a user prompt is set, the
    // active_prompt is the user prompt VERBATIM — no concatenation.
    const overridden: AIPrompt = {
      ...NOTE_GEN,
      user_prompt_text: "anything",
      is_overridden: true,
      active_prompt: "anything",
    };
    render(withIntl(<PromptCard prompt={overridden} />));
    expect(
      screen.getByTestId("prompt-card-note_generation-override-badge"),
    ).toBeInTheDocument();
  });

  it("renders the provider_field hint", () => {
    render(withIntl(<PromptCard prompt={VISION_FRAME} />));
    const providerField = screen.getByTestId(
      "prompt-card-vision_frame-provider-field",
    );
    expect(providerField.textContent).toContain("vision");
  });

  it("renders the active_prompt (user prompt VERBATIM, NOT concatenation) in the expanded view when overridden", async () => {
    const user = userEvent.setup();
    // Replacement semantics: active_prompt is the user prompt alone —
    // the registry default is NOT concatenated below it. The expanded
    // view should show the user prompt and ONLY the user prompt.
    const customPrompt =
      "Custom physician documentation prompt. Describe what was " +
      "observed. Do not interpret findings.";
    const overridden: AIPrompt = {
      ...NOTE_GEN,
      user_prompt_text: customPrompt,
      is_overridden: true,
      active_prompt: customPrompt,
    };
    render(withIntl(<PromptCard prompt={overridden} />));
    await user.click(
      screen.getByTestId("prompt-card-note_generation-toggle"),
    );
    const pre = screen.getByTestId("prompt-card-note_generation-pre");
    // The user prompt is present verbatim.
    expect(pre.textContent).toContain(customPrompt);
    // CRITICAL: the registry default ("Describe only what was directly
    // captured") is NOT present under it — replacement, not append.
    expect(pre.textContent).not.toContain(
      "Describe only what was directly captured",
    );
  });
});

describe("AIPrompts i18n parity (AC-8)", () => {
  it("EN catalog contains the AIPrompts namespace", () => {
    expect(enMessages).toHaveProperty("AIPrompts");
  });

  it("FR catalog contains the AIPrompts namespace", () => {
    expect(frMessages).toHaveProperty("AIPrompts");
  });

  it("EN and FR AIPrompts namespaces have the same key set", () => {
    const enKeys = collectKeys((enMessages as Record<string, unknown>).AIPrompts);
    const frKeys = collectKeys((frMessages as Record<string, unknown>).AIPrompts);
    expect(frKeys).toEqual(enKeys);
  });

  it("Sidebar.nav.aiPrompts exists in both catalogs", () => {
    expect(
      (enMessages as Record<string, Record<string, Record<string, string>>>)
        .Sidebar.nav.aiPrompts,
    ).toBeTruthy();
    expect(
      (frMessages as Record<string, Record<string, Record<string, string>>>)
        .Sidebar.nav.aiPrompts,
    ).toBeTruthy();
  });

  it("renders the FR locale without missing-key warnings", async () => {
    render(withIntl(<AIPromptsPage />, "fr"));
    await waitFor(() =>
      expect(
        screen.getByTestId("prompt-card-note_generation-name"),
      ).toBeInTheDocument(),
    );
    // "Invites IA" — the FR title. Presence proves the namespace is
    // wired through correctly and no key is missing.
    expect(screen.getAllByText(/Invites IA/i).length).toBeGreaterThan(0);
  });
});

/**
 * Recursively collect dotted-path keys from a nested message object.
 * Used to compare EN / FR key sets so a future PR can't add a key in
 * one locale without the other.
 */
function collectKeys(node: unknown, prefix = ""): string[] {
  if (node === null || typeof node !== "object") return [prefix];
  const out: string[] = [];
  for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
    const child = prefix ? `${prefix}.${k}` : k;
    out.push(...collectKeys(v, child));
  }
  return out.sort();
}
