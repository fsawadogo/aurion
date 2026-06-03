"use client";

import { AlertTriangle, RotateCcw, Save, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Modal from "@/components/ui/Modal";
import {
  deleteMyPromptOverride,
  patchMyPromptOverride,
} from "@/lib/portal-api";
import type { AIPrompt, PromptOverlayValidationError } from "@/types";

/**
 * Per-physician overlay editor for an AI Prompt (AI-PROMPTS-B).
 *
 * Three-pane layout, top to bottom:
 *   1. Base prompt — read-only `<pre>` block, distinct visual
 *      treatment so the physician understands this is the
 *      descriptive-mode boundary they CANNOT modify.
 *   2. Your preferences — textarea bound to local state, with
 *      char count toward the 1000-char cap.
 *   3. Live preview of the assembled prompt — re-renders on every
 *      keystroke; this is exactly what the LLM would receive on
 *      the next call. No round-trip.
 *
 * Save button calls PATCH. On 400 the matched_phrase is echoed
 * back from the server and we surface it inline; the textarea
 * stays focused so the physician can edit without re-opening.
 *
 * Reset button calls DELETE behind a confirm dialog (a single
 * physician usually has at most one overlay per prompt; deleting
 * is destructive and irreversible). Cancel discards local edits.
 *
 * Owned state:
 *   - draft text (separate from the prop so cancel is a no-op)
 *   - error banner (cleared on every change)
 *   - submitting / resetting flags (disable buttons + spinners)
 *   - showing-reset-confirm flag
 */

const OVERLAY_MAX_LENGTH = 1000;
const OVERLAY_SEPARATOR = "--- Physician preferences ---";

interface PromptOverrideEditorProps {
  prompt: AIPrompt;
  isOpen: boolean;
  onClose: () => void;
  /** Called with the updated AIPrompt on a successful save or reset. */
  onSaved: (next: AIPrompt) => void;
}

interface ServerErrorDetail {
  message?: string;
  code?: PromptOverlayValidationError["code"];
  matched_phrase?: string | null;
}

export default function PromptOverrideEditor({
  prompt,
  isOpen,
  onClose,
  onSaved,
}: PromptOverrideEditorProps) {
  const t = useTranslations("AIPrompts");
  const [draft, setDraft] = useState<string>(prompt.overlay_text ?? "");
  const [error, setError] = useState<PromptOverlayValidationError | string | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);

  // Re-seed draft when a different prompt opens or the modal toggles —
  // the parent reuses the same editor for each card, so we have to
  // sync on prop change.
  const promptKey = `${prompt.id}:${isOpen ? "open" : "closed"}`;
  const lastSeenKey = useMemo(() => promptKey, [promptKey]);
  if (lastSeenKey !== promptKey) {
    // No-op: React handles via key prop in parent. Kept as a sanity
    // anchor in case parents forget to re-key.
  }

  // Live preview — pure function on the base + draft. The server
  // computes the canonical assembled_preview on save; while editing
  // we mirror the join here so the physician sees what they're
  // building character-by-character.
  const livePreview = useMemo(() => {
    const trimmed = draft.trim();
    if (!trimmed) return prompt.system_prompt;
    return `${prompt.system_prompt}\n\n${OVERLAY_SEPARATOR}\n${trimmed}`;
  }, [draft, prompt.system_prompt]);

  const charCount = draft.length;
  const overLimit = charCount > OVERLAY_MAX_LENGTH;

  function handleChange(next: string) {
    setDraft(next);
    if (error) setError(null);
  }

  async function handleSave() {
    setSubmitting(true);
    setError(null);
    try {
      const updated = await patchMyPromptOverride(prompt.id, draft);
      onSaved(updated);
      onClose();
    } catch (e) {
      // fetchWithAuth surfaces non-2xx as Error with a JSON body when
      // available. Try to parse the detail; fall back to a generic
      // message.
      const parsed = parseServerError(e);
      setError(parsed);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReset() {
    setResetting(true);
    setError(null);
    try {
      const updated = await deleteMyPromptOverride(prompt.id);
      onSaved(updated);
      setConfirmingReset(false);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("editor.errorSaving"));
    } finally {
      setResetting(false);
    }
  }

  // Translate server validation codes to localised banners with the
  // matched_phrase highlighted when applicable. Errors that aren't
  // codes (network failures, etc.) come through as plain strings.
  function renderError() {
    if (!error) return null;
    if (typeof error === "string") {
      return (
        <div
          className="rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
          data-testid="prompt-editor-error-banner"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        </div>
      );
    }
    let body: React.ReactNode;
    switch (error.code) {
      case "too_long":
        body = t("errors.tooLong", {
          count: charCount,
          max: OVERLAY_MAX_LENGTH,
        });
        break;
      case "empty":
        body = t("errors.empty");
        break;
      case "banned_phrase":
        body = (
          <>
            {t("errors.bannedPhrase", { phrase: error.matched_phrase ?? "" })}
            {error.matched_phrase && (
              <span
                className="mt-1 inline-block rounded bg-red-100 px-1.5 py-0.5 font-mono text-aurion-micro"
                data-testid="prompt-editor-matched-phrase"
              >
                {error.matched_phrase}
              </span>
            )}
          </>
        );
        break;
      default:
        body = t("errors.unknown");
    }
    return (
      <div
        className="rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
        role="alert"
        data-testid="prompt-editor-error-banner"
      >
        <div className="flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>{body}</div>
        </div>
      </div>
    );
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`${t("editor.title")} — ${prompt.name}`}
      size="2xl"
      footer={
        <div className="flex w-full items-center justify-between gap-3">
          {prompt.is_overridden && (
            <button
              type="button"
              onClick={() => setConfirmingReset(true)}
              disabled={submitting || resetting}
              className="inline-flex items-center gap-1.5 rounded-aurion-md border border-hairline px-3 py-2 text-aurion-callout text-navy-700 hover:bg-canvas/60 transition-colors duration-short disabled:opacity-50"
              data-testid="prompt-editor-reset-button"
            >
              <RotateCcw className="h-4 w-4" />
              {t("override.resetButton")}
            </button>
          )}
          <div className="flex flex-1 items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting || resetting}
              className="rounded-aurion-md px-3 py-2 text-aurion-callout text-navy-700 hover:bg-canvas/60 transition-colors duration-short disabled:opacity-50"
              data-testid="prompt-editor-cancel-button"
            >
              {t("editor.cancelButton")}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={submitting || resetting || overLimit}
              className="inline-flex items-center gap-1.5 rounded-aurion-md bg-navy-700 px-4 py-2 text-aurion-callout text-white hover:bg-navy-800 transition-colors duration-short disabled:opacity-50"
              data-testid="prompt-editor-save-button"
            >
              <Save className="h-4 w-4" />
              {t("editor.saveButton")}
            </button>
          </div>
        </div>
      }
    >
      <div className="space-y-5">
        {renderError()}

        {/* Section 1 — base prompt (read-only, the safety boundary) */}
        <section>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="aurion-micro text-gold-600">
              {t("editor.basePromptLabel")}
            </p>
            <span className="text-aurion-micro text-navy-400">
              {t("editor.basePromptHint")}
            </span>
          </div>
          <pre
            data-testid="prompt-editor-base"
            className="whitespace-pre-wrap break-words rounded-aurion-sm bg-navy-50 px-3 py-2 text-aurion-caption text-navy-700 font-mono leading-relaxed ring-1 ring-inset ring-navy-100 max-h-48 overflow-y-auto"
          >
            {prompt.system_prompt}
          </pre>
        </section>

        {/* Section 2 — your preferences (textarea) */}
        <section>
          <div className="mb-1.5 flex items-center justify-between">
            <label
              htmlFor="prompt-editor-overlay-textarea"
              className="aurion-micro text-gold-600"
            >
              {t("editor.yourPreferencesLabel")}
            </label>
            <span
              data-testid="prompt-editor-char-count"
              className={
                "text-aurion-micro " +
                (overLimit ? "text-red-600 font-semibold" : "text-navy-400")
              }
            >
              {t("editor.charCount", {
                used: charCount,
                max: OVERLAY_MAX_LENGTH,
              })}
            </span>
          </div>
          <textarea
            id="prompt-editor-overlay-textarea"
            data-testid="prompt-editor-textarea"
            value={draft}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={t("editor.yourPreferencesPlaceholder")}
            rows={4}
            className="w-full rounded-aurion-sm border border-hairline bg-white px-3 py-2 text-aurion-caption text-navy-800 placeholder:text-navy-300 focus:outline-none focus:ring-2 focus:ring-gold-300/40 font-mono"
          />
        </section>

        {/* Section 3 — live preview of the assembled prompt */}
        <section>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="aurion-micro text-gold-600">
              {t("editor.previewLabel")}
            </p>
            <span className="text-aurion-micro text-navy-400">
              {t("editor.previewHint")}
            </span>
          </div>
          <pre
            data-testid="prompt-editor-preview"
            className="whitespace-pre-wrap break-words rounded-aurion-sm bg-gold-50 px-3 py-2 text-aurion-caption text-navy-800 font-mono leading-relaxed ring-1 ring-inset ring-gold-200 max-h-56 overflow-y-auto"
          >
            {livePreview}
          </pre>
        </section>

        {/* Section 4 — tips */}
        <section
          className="rounded-aurion-md border border-emerald-200 bg-emerald-50 px-4 py-3"
          data-testid="prompt-editor-tips"
        >
          <div className="mb-2 flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-emerald-700" />
            <p className="aurion-micro text-emerald-700">
              {t("editor.tipsLabel")}
            </p>
          </div>
          <ul className="space-y-1 text-aurion-caption text-navy-700 list-disc pl-5">
            <li>{t("editor.tip1")}</li>
            <li>{t("editor.tip2")}</li>
            <li>{t("editor.tip3")}</li>
            <li>{t("editor.tip4")}</li>
          </ul>
        </section>

        {/* Reset confirmation overlay — appears in-modal rather than
           nesting a second Modal (avoids portal stacking issues). */}
        {confirmingReset && (
          <div
            className="rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3"
            data-testid="prompt-editor-reset-confirm"
            role="alertdialog"
          >
            <p className="text-aurion-callout text-navy-700 font-semibold">
              {t("override.confirmResetTitle")}
            </p>
            <p className="mt-1 text-aurion-caption text-navy-600">
              {t("override.confirmResetMessage")}
            </p>
            <div className="mt-3 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmingReset(false)}
                disabled={resetting}
                className="rounded-aurion-md px-3 py-1.5 text-aurion-callout text-navy-700 hover:bg-canvas/60 transition-colors duration-short disabled:opacity-50"
                data-testid="prompt-editor-reset-cancel"
              >
                {t("override.resetCancel")}
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={resetting}
                className="rounded-aurion-md bg-red-600 px-3 py-1.5 text-aurion-callout text-white hover:bg-red-700 transition-colors duration-short disabled:opacity-50"
                data-testid="prompt-editor-reset-confirm-button"
              >
                {t("override.resetConfirm")}
              </button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}


/**
 * Best-effort parse of the server's 400 detail body. The backend
 * sends `{detail: {message, code, matched_phrase}}` on validation
 * failures; the `fetchWithAuth` wrapper raises an Error whose
 * message is shaped `API <status>: <body>` — we strip that prefix
 * before attempting to parse the JSON. Anything that isn't a
 * structured validation error returns the original message so the
 * banner still has something to show.
 */
function parseServerError(
  e: unknown,
): PromptOverlayValidationError | string {
  if (!(e instanceof Error)) {
    return "Unknown error";
  }
  // `API 400: {"detail":{"code":"banned_phrase",...}}`. The body can
  // be multi-line on some errors, so we strip the documented prefix
  // explicitly rather than relying on the `s` regex dotAll flag (which
  // requires ES2018+ and trips the TS check on older targets).
  const PREFIX_RE = /^API \d+:\s*/;
  const bodyRaw = PREFIX_RE.test(e.message)
    ? e.message.replace(PREFIX_RE, "")
    : e.message;
  try {
    const parsed = JSON.parse(bodyRaw) as { detail?: ServerErrorDetail };
    const detail = parsed.detail;
    if (detail?.code) {
      return {
        code: detail.code,
        message: detail.message ?? "",
        matched_phrase: detail.matched_phrase ?? null,
      };
    }
  } catch {
    // Fall through to plain-message return.
  }
  return e.message;
}
