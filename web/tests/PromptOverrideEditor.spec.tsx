import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PromptOverrideEditor from "@/components/portal/PromptOverrideEditor";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { AIPrompt } from "@/types";
import { withIntl } from "./helpers/intl";

/**
 * AI-PROMPTS-B — PromptOverrideEditor modal.
 *
 * Validates:
 *   - opens empty when no overlay exists / pre-filled when present
 *   - live preview updates as the textarea changes
 *   - char count updates
 *   - save success closes the modal + invokes onSaved
 *   - save with banned phrase shows the error banner with matched_phrase
 *   - reset shows the confirm dialog → confirm calls DELETE → closes
 *   - cancel discards local changes (doesn't call API)
 *   - i18n parity: every editor key in EN has a FR sibling
 *
 * The API client is mocked at the module boundary.
 */

vi.mock("@/lib/portal-api", () => ({
  patchMyPromptOverride: vi.fn(),
  deleteMyPromptOverride: vi.fn(),
}));

import {
  deleteMyPromptOverride,
  patchMyPromptOverride,
} from "@/lib/portal-api";

const BASE_TEXT =
  "You are a clinical documentation assistant. Describe only what was directly captured. Do not interpret.";

const PROMPT_BASE: AIPrompt = {
  id: "note_generation",
  name: "Note generation",
  purpose: "Drafts the SOAP note.",
  category: "note",
  runs_when: "After recording stops.",
  provider_field: "note_generation",
  system_prompt: BASE_TEXT,
  schema_note: null,
  overlay_text: null,
  is_overridden: false,
  assembled_preview: BASE_TEXT,
};

const PROMPT_OVERRIDDEN: AIPrompt = {
  ...PROMPT_BASE,
  overlay_text: "Always note bilateral comparison when applicable.",
  is_overridden: true,
  assembled_preview:
    BASE_TEXT +
    "\n\n--- Physician preferences ---\n" +
    "Always note bilateral comparison when applicable.",
};

beforeEach(() => {
  vi.mocked(patchMyPromptOverride).mockReset();
  vi.mocked(deleteMyPromptOverride).mockReset();
});

describe("PromptOverrideEditor — open state", () => {
  it("opens with an empty textarea when no overlay exists", () => {
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const textarea = screen.getByTestId(
      "prompt-editor-textarea",
    ) as HTMLTextAreaElement;
    expect(textarea.value).toBe("");
  });

  it("opens with the current overlay pre-filled when overridden", () => {
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_OVERRIDDEN}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const textarea = screen.getByTestId(
      "prompt-editor-textarea",
    ) as HTMLTextAreaElement;
    expect(textarea.value).toBe(PROMPT_OVERRIDDEN.overlay_text);
  });

  it("shows the base prompt verbatim in the locked pane", () => {
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const base = screen.getByTestId("prompt-editor-base");
    expect(base.textContent).toBe(BASE_TEXT);
  });

  it("does not render when isOpen=false", () => {
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={false}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    expect(
      screen.queryByTestId("prompt-editor-textarea"),
    ).toBeNull();
  });
});

describe("PromptOverrideEditor — live preview", () => {
  it("updates the assembled preview as the user types", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const textarea = screen.getByTestId("prompt-editor-textarea");
    const preview = screen.getByTestId("prompt-editor-preview");
    // Initial preview is bare base.
    expect(preview.textContent).toBe(BASE_TEXT);
    await user.type(textarea, "Use mm not cm.");
    // Preview re-renders: base + separator + draft.
    await waitFor(() => {
      expect(preview.textContent).toContain("Use mm not cm.");
      expect(preview.textContent).toContain("--- Physician preferences ---");
      expect(preview.textContent?.startsWith(BASE_TEXT)).toBe(true);
    });
  });

  it("updates the character counter as the user types", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const counter = screen.getByTestId("prompt-editor-char-count");
    expect(counter.textContent).toContain("0/1000");
    await user.type(screen.getByTestId("prompt-editor-textarea"), "Hello");
    expect(counter.textContent).toContain("5/1000");
  });
});

describe("PromptOverrideEditor — save path", () => {
  it("calls patchMyPromptOverride + invokes onSaved + closes on success", async () => {
    const updated: AIPrompt = {
      ...PROMPT_BASE,
      overlay_text: "Bilateral comparison.",
      is_overridden: true,
      assembled_preview:
        BASE_TEXT + "\n\n--- Physician preferences ---\nBilateral comparison.",
    };
    vi.mocked(patchMyPromptOverride).mockResolvedValue(updated);
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={true}
          onClose={onClose}
          onSaved={onSaved}
        />,
      ),
    );
    await user.type(
      screen.getByTestId("prompt-editor-textarea"),
      "Bilateral comparison.",
    );
    await user.click(screen.getByTestId("prompt-editor-save-button"));
    await waitFor(() => {
      expect(patchMyPromptOverride).toHaveBeenCalledWith(
        "note_generation",
        "Bilateral comparison.",
      );
      expect(onSaved).toHaveBeenCalledWith(updated);
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("surfaces the banned-phrase error with matched_phrase on 400", async () => {
    // fetchWithAuth throws `Error("API 400: <body>")` on non-2xx.
    vi.mocked(patchMyPromptOverride).mockRejectedValue(
      new Error(
        'API 400: {"detail":{"code":"banned_phrase","message":"banned","matched_phrase":"you may diagnose"}}',
      ),
    );
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={true}
          onClose={onClose}
          onSaved={onSaved}
        />,
      ),
    );
    await user.type(
      screen.getByTestId("prompt-editor-textarea"),
      "Hey: you may diagnose now",
    );
    await user.click(screen.getByTestId("prompt-editor-save-button"));
    await waitFor(() => {
      const banner = screen.getByTestId("prompt-editor-error-banner");
      expect(banner.textContent).toContain("you may diagnose");
    });
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // Modal stays open so the physician can edit.
    expect(
      screen.getByTestId("prompt-editor-textarea"),
    ).toBeInTheDocument();
  });
});

describe("PromptOverrideEditor — reset path", () => {
  it("shows the reset button only when overridden", () => {
    const { rerender } = render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    expect(screen.queryByTestId("prompt-editor-reset-button")).toBeNull();
    rerender(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_OVERRIDDEN}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    expect(
      screen.getByTestId("prompt-editor-reset-button"),
    ).toBeInTheDocument();
  });

  it("shows the confirm dialog when Reset is clicked", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_OVERRIDDEN}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    await user.click(screen.getByTestId("prompt-editor-reset-button"));
    expect(
      screen.getByTestId("prompt-editor-reset-confirm"),
    ).toBeInTheDocument();
  });

  it("Confirm Reset calls deleteMyPromptOverride + invokes onSaved + closes", async () => {
    vi.mocked(deleteMyPromptOverride).mockResolvedValue(PROMPT_BASE);
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_OVERRIDDEN}
          isOpen={true}
          onClose={onClose}
          onSaved={onSaved}
        />,
      ),
    );
    await user.click(screen.getByTestId("prompt-editor-reset-button"));
    await user.click(
      screen.getByTestId("prompt-editor-reset-confirm-button"),
    );
    await waitFor(() => {
      expect(deleteMyPromptOverride).toHaveBeenCalledWith("note_generation");
      expect(onSaved).toHaveBeenCalledWith(PROMPT_BASE);
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("Cancel on the reset confirm closes the inline dialog without calling DELETE", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_OVERRIDDEN}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    await user.click(screen.getByTestId("prompt-editor-reset-button"));
    await user.click(screen.getByTestId("prompt-editor-reset-cancel"));
    expect(deleteMyPromptOverride).not.toHaveBeenCalled();
    expect(
      screen.queryByTestId("prompt-editor-reset-confirm"),
    ).toBeNull();
  });
});

describe("PromptOverrideEditor — cancel path", () => {
  it("Cancel button doesn't call PATCH and triggers onClose", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptOverrideEditor
          prompt={PROMPT_BASE}
          isOpen={true}
          onClose={onClose}
          onSaved={() => {}}
        />,
      ),
    );
    await user.type(
      screen.getByTestId("prompt-editor-textarea"),
      "Discarded local change",
    );
    await user.click(screen.getByTestId("prompt-editor-cancel-button"));
    expect(patchMyPromptOverride).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});

describe("PromptOverrideEditor — i18n parity", () => {
  function collectKeys(obj: unknown, prefix: string = ""): string[] {
    if (typeof obj !== "object" || obj === null) return [prefix];
    return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
      collectKeys(v, prefix ? `${prefix}.${k}` : k),
    );
  }

  it("EN contains every new editor + override + errors key", () => {
    const en = (enMessages as Record<string, Record<string, Record<string, string>>>).AIPrompts;
    expect(en.editor.title).toBeTruthy();
    expect(en.editor.basePromptLabel).toBeTruthy();
    expect(en.editor.yourPreferencesLabel).toBeTruthy();
    expect(en.editor.previewLabel).toBeTruthy();
    expect(en.editor.saveButton).toBeTruthy();
    expect(en.override.activeBadge).toBeTruthy();
    expect(en.override.editButton).toBeTruthy();
    expect(en.override.resetButton).toBeTruthy();
    expect(en.errors.tooLong).toBeTruthy();
    expect(en.errors.bannedPhrase).toBeTruthy();
    expect(en.errors.empty).toBeTruthy();
  });

  it("FR contains every new editor + override + errors key", () => {
    const fr = (frMessages as Record<string, Record<string, Record<string, string>>>).AIPrompts;
    expect(fr.editor.title).toBeTruthy();
    expect(fr.editor.basePromptLabel).toBeTruthy();
    expect(fr.editor.yourPreferencesLabel).toBeTruthy();
    expect(fr.editor.previewLabel).toBeTruthy();
    expect(fr.editor.saveButton).toBeTruthy();
    expect(fr.override.activeBadge).toBeTruthy();
    expect(fr.override.editButton).toBeTruthy();
    expect(fr.override.resetButton).toBeTruthy();
    expect(fr.errors.tooLong).toBeTruthy();
    expect(fr.errors.bannedPhrase).toBeTruthy();
    expect(fr.errors.empty).toBeTruthy();
  });

  it("EN and FR AIPrompts namespaces have the same key set", () => {
    const enKeys = collectKeys(
      (enMessages as Record<string, unknown>).AIPrompts,
    ).sort();
    const frKeys = collectKeys(
      (frMessages as Record<string, unknown>).AIPrompts,
    ).sort();
    expect(frKeys).toEqual(enKeys);
  });
});
