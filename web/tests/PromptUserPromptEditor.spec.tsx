import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PromptUserPromptEditor from "@/components/portal/PromptUserPromptEditor";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { AIPrompt } from "@/types";
import { withIntl } from "./helpers/intl";

/**
 * AI-PROMPTS-B — PromptUserPromptEditor modal (replacement semantics).
 *
 * Validates:
 *   - editor shows the system default as read-only (the fallback)
 *   - textarea is empty when no user prompt set / pre-filled when set
 *   - "Start from system default" button copies system_prompt into
 *     the textarea
 *   - active prompt preview shows the textarea content VERBATIM when
 *     non-empty (NOT base + textarea — replacement, not concat)
 *   - empty textarea → preview shows the "system default will be used"
 *     message
 *   - char count updates as user types
 *   - save success closes the modal + invokes onSaved
 *   - save with banned phrase → 400 → banner with matched_phrase
 *   - save with missing descriptive anchor → 400 → banner naming
 *     which anchor group
 *   - reset shows the confirm dialog → confirm calls DELETE → closes
 *   - cancel discards local changes (doesn't call API)
 *   - i18n parity: every editor key in EN has a FR sibling
 *
 * The API client is mocked at the module boundary.
 */

vi.mock("@/lib/portal-api", () => ({
  patchMyUserPrompt: vi.fn(),
  deleteMyUserPrompt: vi.fn(),
}));

import { deleteMyUserPrompt, patchMyUserPrompt } from "@/lib/portal-api";

const SYSTEM_DEFAULT =
  "You are a clinical documentation assistant. Describe only what was " +
  "directly captured. Do not interpret.";

const WELL_FORMED_USER_PROMPT =
  "You are a clinical documentation assistant. Describe what was " +
  "captured during the encounter. Document the patient's complaints. " +
  "Do not interpret findings, do not diagnose, do not infer clinical " +
  "meaning.";

const PROMPT_DEFAULT_ONLY: AIPrompt = {
  id: "note_generation",
  name: "Note generation",
  purpose: "Drafts the SOAP note.",
  category: "note",
  runs_when: "After recording stops.",
  provider_field: "note_generation",
  system_prompt: SYSTEM_DEFAULT,
  system_prompt_is_fallback: true,
  schema_note: null,
  user_prompt_text: null,
  is_overridden: false,
  active_prompt: SYSTEM_DEFAULT, // replacement: fallback to default
};

const PROMPT_WITH_USER_PROMPT: AIPrompt = {
  ...PROMPT_DEFAULT_ONLY,
  user_prompt_text: WELL_FORMED_USER_PROMPT,
  is_overridden: true,
  active_prompt: WELL_FORMED_USER_PROMPT, // replacement: user prompt verbatim
};

beforeEach(() => {
  vi.mocked(patchMyUserPrompt).mockReset();
  vi.mocked(deleteMyUserPrompt).mockReset();
});

describe("PromptUserPromptEditor — open state", () => {
  it("opens with an empty textarea when no user prompt exists", () => {
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
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

  it("opens with the current user prompt pre-filled when set", () => {
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_WITH_USER_PROMPT}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const textarea = screen.getByTestId(
      "prompt-editor-textarea",
    ) as HTMLTextAreaElement;
    expect(textarea.value).toBe(WELL_FORMED_USER_PROMPT);
  });

  it("shows the system default verbatim in the read-only pane", () => {
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const sysDefault = screen.getByTestId("prompt-editor-system-default");
    expect(sysDefault.textContent).toBe(SYSTEM_DEFAULT);
  });

  it("does not render when isOpen=false", () => {
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={false}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    expect(screen.queryByTestId("prompt-editor-textarea")).toBeNull();
  });
});

describe("PromptUserPromptEditor — copy from system default", () => {
  it("Start-from-system-default button copies system_prompt into textarea", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
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
    await user.click(screen.getByTestId("prompt-editor-copy-default-button"));
    expect(textarea.value).toBe(SYSTEM_DEFAULT);
  });
});

describe("PromptUserPromptEditor — active prompt preview (REPLACEMENT)", () => {
  it("empty textarea → preview shows the 'system default will be used' message", () => {
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const preview = screen.getByTestId("prompt-editor-active-preview");
    // The localised "system default will be used" text.
    expect(preview.textContent).toBe(
      enMessages.AIPrompts.editor.activePromptIsDefault,
    );
  });

  it("non-empty textarea → preview shows the textarea content VERBATIM (NOT base + textarea)", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const textarea = screen.getByTestId("prompt-editor-textarea");
    const preview = screen.getByTestId("prompt-editor-active-preview");

    const customPrompt =
      "Describe what was observed. Do not interpret findings.";
    await user.type(textarea, customPrompt);

    await waitFor(() => {
      expect(preview.textContent).toBe(customPrompt);
    });
    // CRITICAL — the system default is NOT prepended under the user
    // prompt. Replacement semantics: the user prompt is what the LLM
    // sees, alone.
    expect(preview.textContent).not.toContain(SYSTEM_DEFAULT);
  });

  it("updates the character counter as the user types", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    const counter = screen.getByTestId("prompt-editor-char-count");
    expect(counter.textContent).toContain("0/5000");
    await user.type(screen.getByTestId("prompt-editor-textarea"), "Hello");
    expect(counter.textContent).toContain("5/5000");
  });
});

describe("PromptUserPromptEditor — save path", () => {
  it("calls patchMyUserPrompt + invokes onSaved + closes on success", async () => {
    const updated: AIPrompt = {
      ...PROMPT_DEFAULT_ONLY,
      user_prompt_text: WELL_FORMED_USER_PROMPT,
      is_overridden: true,
      active_prompt: WELL_FORMED_USER_PROMPT,
    };
    vi.mocked(patchMyUserPrompt).mockResolvedValue(updated);
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={onClose}
          onSaved={onSaved}
        />,
      ),
    );
    // Paste via fireEvent-style direct value set to avoid character-
    // by-character timing on a 1000-char prompt. We model this by
    // typing a short prompt; the API mock returns the expected shape
    // regardless of input length.
    await user.type(
      screen.getByTestId("prompt-editor-textarea"),
      "Describe. Do not diagnose.",
    );
    await user.click(screen.getByTestId("prompt-editor-save-button"));
    await waitFor(() => {
      expect(patchMyUserPrompt).toHaveBeenCalledWith(
        "note_generation",
        "Describe. Do not diagnose.",
      );
      expect(onSaved).toHaveBeenCalledWith(updated);
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("surfaces the banned-phrase error with matched_phrase on 400", async () => {
    // fetchWithAuth throws `Error("API 400: <body>")` on non-2xx.
    vi.mocked(patchMyUserPrompt).mockRejectedValue(
      new Error(
        'API 400: {"detail":{"code":"banned_phrase","message":"banned","matched_phrase":"you may diagnose","missing_anchor_group":null}}',
      ),
    );
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={onClose}
          onSaved={onSaved}
        />,
      ),
    );
    await user.type(
      screen.getByTestId("prompt-editor-textarea"),
      "Describe. You may diagnose now.",
    );
    await user.click(screen.getByTestId("prompt-editor-save-button"));
    await waitFor(() => {
      const banner = screen.getByTestId("prompt-editor-error-banner");
      expect(banner.textContent).toContain("you may diagnose");
    });
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // Modal stays open so the physician can edit.
    expect(screen.getByTestId("prompt-editor-textarea")).toBeInTheDocument();
  });

  it("surfaces the missing-anchor-DESCRIBE error (group 0) on 400", async () => {
    vi.mocked(patchMyUserPrompt).mockRejectedValue(
      new Error(
        'API 400: {"detail":{"code":"missing_descriptive_anchor","message":"missing","matched_phrase":null,"missing_anchor_group":0}}',
      ),
    );
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    await user.type(
      screen.getByTestId("prompt-editor-textarea"),
      "Do not interpret. Do not diagnose.",
    );
    await user.click(screen.getByTestId("prompt-editor-save-button"));
    await waitFor(() => {
      const banner = screen.getByTestId("prompt-editor-error-banner");
      // Localised message for group 0 names the describe / document /
      // record requirement.
      expect(banner.textContent).toContain(
        enMessages.AIPrompts.errors.missingAnchorDescribe.slice(0, 25),
      );
    });
  });

  it("surfaces the missing-anchor-NO-INTERPRET error (group 1) on 400", async () => {
    vi.mocked(patchMyUserPrompt).mockRejectedValue(
      new Error(
        'API 400: {"detail":{"code":"missing_descriptive_anchor","message":"missing","matched_phrase":null,"missing_anchor_group":1}}',
      ),
    );
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    await user.type(
      screen.getByTestId("prompt-editor-textarea"),
      "Describe. Document. Record.",
    );
    await user.click(screen.getByTestId("prompt-editor-save-button"));
    await waitFor(() => {
      const banner = screen.getByTestId("prompt-editor-error-banner");
      expect(banner.textContent).toContain(
        enMessages.AIPrompts.errors.missingAnchorNoInterpret.slice(0, 25),
      );
    });
  });
});

describe("PromptUserPromptEditor — reset path", () => {
  it("shows the reset button only when overridden", () => {
    const { rerender } = render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    expect(screen.queryByTestId("prompt-editor-reset-button")).toBeNull();
    rerender(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_WITH_USER_PROMPT}
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

  it("Confirm Reset calls deleteMyUserPrompt + invokes onSaved + closes", async () => {
    vi.mocked(deleteMyUserPrompt).mockResolvedValue(PROMPT_DEFAULT_ONLY);
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_WITH_USER_PROMPT}
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
      expect(deleteMyUserPrompt).toHaveBeenCalledWith("note_generation");
      expect(onSaved).toHaveBeenCalledWith(PROMPT_DEFAULT_ONLY);
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("Cancel on the reset confirm closes the inline dialog without calling DELETE", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_WITH_USER_PROMPT}
          isOpen={true}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      ),
    );
    await user.click(screen.getByTestId("prompt-editor-reset-button"));
    await user.click(screen.getByTestId("prompt-editor-reset-cancel"));
    expect(deleteMyUserPrompt).not.toHaveBeenCalled();
    expect(screen.queryByTestId("prompt-editor-reset-confirm")).toBeNull();
  });
});

describe("PromptUserPromptEditor — cancel path", () => {
  it("Cancel button doesn't call PATCH and triggers onClose", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptUserPromptEditor
          prompt={PROMPT_DEFAULT_ONLY}
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
    expect(patchMyUserPrompt).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});

describe("PromptUserPromptEditor — i18n parity", () => {
  function collectKeys(obj: unknown, prefix: string = ""): string[] {
    if (typeof obj !== "object" || obj === null) return [prefix];
    return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
      collectKeys(v, prefix ? `${prefix}.${k}` : k),
    );
  }

  it("EN contains every new editor + userPrompt + errors key", () => {
    const en = (
      enMessages as Record<string, Record<string, Record<string, string>>>
    ).AIPrompts;
    expect(en.editor.title).toBeTruthy();
    expect(en.editor.systemDefaultLabel).toBeTruthy();
    expect(en.editor.yourPromptLabel).toBeTruthy();
    expect(en.editor.activePromptLabel).toBeTruthy();
    expect(en.editor.copyFromSystemDefault).toBeTruthy();
    expect(en.editor.requirementDescribe).toBeTruthy();
    expect(en.editor.requirementNoInterpret).toBeTruthy();
    expect(en.editor.saveButton).toBeTruthy();
    expect(en.userPrompt.activeBadge).toBeTruthy();
    expect(en.userPrompt.editButton).toBeTruthy();
    expect(en.userPrompt.resetButton).toBeTruthy();
    expect(en.errors.tooLong).toBeTruthy();
    expect(en.errors.bannedPhrase).toBeTruthy();
    expect(en.errors.missingAnchorDescribe).toBeTruthy();
    expect(en.errors.missingAnchorNoInterpret).toBeTruthy();
    expect(en.errors.empty).toBeTruthy();
  });

  it("FR contains every new editor + userPrompt + errors key", () => {
    const fr = (
      frMessages as Record<string, Record<string, Record<string, string>>>
    ).AIPrompts;
    expect(fr.editor.title).toBeTruthy();
    expect(fr.editor.systemDefaultLabel).toBeTruthy();
    expect(fr.editor.yourPromptLabel).toBeTruthy();
    expect(fr.editor.activePromptLabel).toBeTruthy();
    expect(fr.editor.copyFromSystemDefault).toBeTruthy();
    expect(fr.editor.requirementDescribe).toBeTruthy();
    expect(fr.editor.requirementNoInterpret).toBeTruthy();
    expect(fr.editor.saveButton).toBeTruthy();
    expect(fr.userPrompt.activeBadge).toBeTruthy();
    expect(fr.userPrompt.editButton).toBeTruthy();
    expect(fr.userPrompt.resetButton).toBeTruthy();
    expect(fr.errors.tooLong).toBeTruthy();
    expect(fr.errors.bannedPhrase).toBeTruthy();
    expect(fr.errors.missingAnchorDescribe).toBeTruthy();
    expect(fr.errors.missingAnchorNoInterpret).toBeTruthy();
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
