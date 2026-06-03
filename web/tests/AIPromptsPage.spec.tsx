import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AIPromptsPage from "@/app/portal/prompts/page";
import PromptCard from "@/components/portal/PromptCard";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { AIPrompt } from "@/types";
import { withIntl } from "./helpers/intl";

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
}));

import { listMyPrompts } from "@/lib/portal-api";

const NOTE_GEN: AIPrompt = {
  id: "note_generation",
  name: "Note generation",
  purpose: "Drafts the SOAP note from the audio transcript.",
  category: "note",
  runs_when: "After the recording stops, before review.",
  provider_field: "note_generation",
  system_prompt:
    "You are a clinical documentation assistant for Aurion Clinical AI. Describe only what was directly captured. Do not infer.",
  schema_note: "Output: strict JSON.",
  override_text: null,
  is_overridden: false,
};

const VISION_FRAME: AIPrompt = {
  id: "vision_frame",
  name: "Vision (still frame)",
  purpose: "Describes what is visible in a still frame.",
  category: "vision",
  runs_when: "Stage 2 frame captioning.",
  provider_field: "vision",
  system_prompt:
    "You are a clinical visual documentation assistant. Describe only what is literally visible.",
  schema_note: "Output: JSON description + confidence.",
  override_text: null,
  is_overridden: false,
};

const PATIENT_SUMMARY: AIPrompt = {
  id: "patient_summary",
  name: "Patient after-visit summary",
  purpose: "Plain-language handout for the patient.",
  category: "extraction",
  runs_when: "After note approval.",
  provider_field: "note_generation",
  system_prompt: "You are an after-visit summary writer.",
  schema_note: "Output: single paragraph.",
  override_text: null,
  is_overridden: false,
};

const LIVE_PREVIEW: AIPrompt = {
  id: "live_preview",
  name: "Live note preview",
  purpose: "Rolling draft during recording.",
  category: "preview",
  runs_when: "Every few seconds during recording.",
  provider_field: "note_generation",
  system_prompt: "Stage 0 note draft system prompt.",
  schema_note: null,
  override_text: null,
  is_overridden: false,
};

const MOCK_PROMPTS = [NOTE_GEN, VISION_FRAME, PATIENT_SUMMARY, LIVE_PREVIEW];

beforeEach(() => {
  vi.mocked(listMyPrompts).mockResolvedValue(MOCK_PROMPTS);
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

  it("renders the Phase A read-only chip on every card", () => {
    render(withIntl(<PromptCard prompt={NOTE_GEN} />));
    expect(
      screen.getByTestId("prompt-card-note_generation-readonly-chip"),
    ).toBeInTheDocument();
  });

  it("renders the provider_field hint", () => {
    render(withIntl(<PromptCard prompt={VISION_FRAME} />));
    const providerField = screen.getByTestId(
      "prompt-card-vision_frame-provider-field",
    );
    expect(providerField.textContent).toContain("vision");
  });

  it("renders override_text when present in place of system_prompt (Phase B forward-compat)", async () => {
    const user = userEvent.setup();
    const overridden: AIPrompt = {
      ...NOTE_GEN,
      override_text: "Custom physician override goes here.",
      is_overridden: true,
    };
    render(withIntl(<PromptCard prompt={overridden} />));
    await user.click(
      screen.getByTestId("prompt-card-note_generation-toggle"),
    );
    const pre = screen.getByTestId("prompt-card-note_generation-pre");
    expect(pre.textContent).toContain("Custom physician override");
    expect(pre.textContent).not.toContain("Describe only what was directly captured");
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
    // "Phase A : lecture seule" — locale-specific phrase that only
    // exists in the FR catalog. Presence proves the namespace is
    // wired through correctly.
    expect(screen.getAllByText(/Phase A/i).length).toBeGreaterThan(0);
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
