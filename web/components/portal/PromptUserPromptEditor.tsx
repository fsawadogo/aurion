"use client";

import { AlertTriangle, Copy, RotateCcw, Save, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Modal from "@/components/ui/Modal";
import {
  deleteMyUserPrompt,
  patchMyUserPrompt,
} from "@/lib/portal-api";
import type { AIPrompt, PromptUserPromptValidationError } from "@/types";

/**
 * Per-physician REPLACEMENT user-prompt editor for one AI Prompt
 * card (AI-PROMPTS-B, replacement semantics).
 *
 * Four-pane layout, top to bottom:
 *   1. System default — read-only `<pre>` of the registry prompt
 *      with muted styling. Header makes clear this is the FALLBACK,
 *      used only when the physician hasn't saved their own prompt.
 *      A "Start from system default" button copies its text into the
 *      textarea so physicians can edit FROM the safe baseline rather
 *      than write from scratch — the recommended UX path.
 *   2. Your prompt — textarea bound to local state, with char count
 *      toward the 5000-char cap. Empty textarea = the system default
 *      will run.
 *   3. Active prompt preview — what the LLM will receive on save.
 *      Empty textarea → "System default will be used" message; non-
 *      empty → the textarea content verbatim (NOT base + textarea).
 *   4. Requirements — bulleted checklist of what the validator
 *      requires (descriptive anchors, 5000-char cap, no banned
 *      phrases).
 *
 * Save calls PATCH. On 400 the matched_phrase / missing_anchor_group
 * is echoed back from the server and we surface it inline; the
 * textarea stays focused so the physician can edit without
 * re-opening.
 *
 * Reset calls DELETE behind a confirm dialog (destructive: the
 * physician loses their saved text and falls back to the system
 * default). Cancel discards local edits.
 *
 * Owned state:
 *   - draft text (separate from the prop so cancel is a no-op)
 *   - error banner (cleared on every change)
 *   - submitting / resetting flags (disable buttons + spinners)
 *   - showing-reset-confirm flag
 */

const USER_PROMPT_MAX_LENGTH = 5000;

interface PromptUserPromptEditorProps {
  prompt: AIPrompt;
  isOpen: boolean;
  onClose: () => void;
  /** Called with the updated AIPrompt on a successful save or reset. */
  onSaved: (next: AIPrompt) => void;
}

interface ServerErrorDetail {
  message?: string;
  code?: PromptUserPromptValidationError["code"];
  matched_phrase?: string | null;
  missing_anchor_group?: number | null;
}

export default function PromptUserPromptEditor({
  prompt,
  isOpen,
  onClose,
  onSaved,
}: PromptUserPromptEditorProps) {
  const t = useTranslations("AIPrompts");
  const [draft, setDraft] = useState<string>(prompt.user_prompt_text ?? "");
  const [error, setError] = useState<
    PromptUserPromptValidationError | string | null
  >(null);
  const [submitting, setSubmitting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);

  // Active-prompt preview — pure selection on the draft. Replacement
  // semantics: when the textarea is empty the system default runs;
  // otherwise the textarea content is what the LLM will receive
  // verbatim. NO concatenation here. The server returns the same
  // selection in `active_prompt` on save; while editing we mirror it
  // locally so the physician sees what they're committing to.
  const trimmedDraft = useMemo(() => draft.trim(), [draft]);
  const activePromptIsDefault = trimmedDraft.length === 0;
  const livePreview = activePromptIsDefault ? prompt.system_prompt : draft;

  const charCount = draft.length;
  const overLimit = charCount > USER_PROMPT_MAX_LENGTH;

  function handleChange(next: string) {
    setDraft(next);
    if (error) setError(null);
  }

  /** "Start from system default" — copies the system prompt into the
   *  textarea so the physician edits FROM a passing baseline rather
   *  than writing from scratch. Doesn't save; just seeds the draft. */
  function handleCopyFromSystemDefault() {
    setDraft(prompt.system_prompt);
    if (error) setError(null);
  }

  async function handleSave() {
    setSubmitting(true);
    setError(null);
    try {
      const updated = await patchMyUserPrompt(prompt.id, draft);
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
      const updated = await deleteMyUserPrompt(prompt.id);
      onSaved(updated);
      setConfirmingReset(false);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("editor.errorSaving"));
    } finally {
      setResetting(false);
    }
  }

  // Translate server validation codes to localised banners. Errors
  // that aren't codes (network failures, etc.) come through as plain
  // strings.
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
          max: USER_PROMPT_MAX_LENGTH,
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
      case "missing_descriptive_anchor":
        body =
          error.missing_anchor_group === 1
            ? t("errors.missingAnchorNoInterpret")
            : t("errors.missingAnchorDescribe");
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
              {t("userPrompt.resetButton")}
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

        {/* Section 1 — system default (read-only, the fallback) */}
        <section>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="aurion-micro text-gold-600">
              {t("editor.systemDefaultLabel")}
            </p>
            <span className="text-aurion-micro text-navy-400">
              {t("editor.systemDefaultHint")}
            </span>
          </div>
          <pre
            data-testid="prompt-editor-system-default"
            className="whitespace-pre-wrap break-words rounded-aurion-sm bg-navy-50/60 px-3 py-2 text-aurion-caption text-navy-500 font-mono leading-relaxed ring-1 ring-inset ring-navy-100 max-h-48 overflow-y-auto"
          >
            {prompt.system_prompt}
          </pre>
          <button
            type="button"
            onClick={handleCopyFromSystemDefault}
            className="mt-2 inline-flex items-center gap-1.5 rounded-aurion-sm border border-hairline px-2.5 py-1 text-aurion-micro text-navy-700 hover:bg-canvas/60 transition-colors duration-short"
            data-testid="prompt-editor-copy-default-button"
          >
            <Copy className="h-3 w-3" />
            {t("editor.copyFromSystemDefault")}
          </button>
        </section>

        {/* Section 2 — your prompt (textarea) */}
        <section>
          <div className="mb-1.5 flex items-center justify-between">
            <label
              htmlFor="prompt-editor-user-prompt-textarea"
              className="aurion-micro text-gold-600"
            >
              {t("editor.yourPromptLabel")}
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
                max: USER_PROMPT_MAX_LENGTH,
              })}
            </span>
          </div>
          <textarea
            id="prompt-editor-user-prompt-textarea"
            data-testid="prompt-editor-textarea"
            value={draft}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={t("editor.yourPromptPlaceholder")}
            rows={8}
            className="w-full rounded-aurion-sm border border-hairline bg-white px-3 py-2 text-aurion-caption text-navy-800 placeholder:text-navy-300 focus:outline-none focus:ring-2 focus:ring-gold-300/40 font-mono"
          />
        </section>

        {/* Section 3 — active prompt preview (replacement, not concat) */}
        <section>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="aurion-micro text-gold-600">
              {t("editor.activePromptLabel")}
            </p>
            <span className="text-aurion-micro text-navy-400">
              {t("editor.activePromptHint")}
            </span>
          </div>
          <pre
            data-testid="prompt-editor-active-preview"
            className="whitespace-pre-wrap break-words rounded-aurion-sm bg-gold-50 px-3 py-2 text-aurion-caption text-navy-800 font-mono leading-relaxed ring-1 ring-inset ring-gold-200 max-h-56 overflow-y-auto"
          >
            {activePromptIsDefault
              ? t("editor.activePromptIsDefault")
              : livePreview}
          </pre>
        </section>

        {/* Section 4 — requirements */}
        <section
          className="rounded-aurion-md border border-emerald-200 bg-emerald-50 px-4 py-3"
          data-testid="prompt-editor-requirements"
        >
          <div className="mb-2 flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-emerald-700" />
            <p className="aurion-micro text-emerald-700">
              {t("editor.requirementsLabel")}
            </p>
          </div>
          <ul className="space-y-1 text-aurion-caption text-navy-700 list-disc pl-5">
            <li>{t("editor.requirementDescribe")}</li>
            <li>{t("editor.requirementNoInterpret")}</li>
            <li>
              {t("editor.requirementMaxLength", {
                max: USER_PROMPT_MAX_LENGTH,
              })}
            </li>
            <li>{t("editor.requirementNoBannedPhrases")}</li>
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
              {t("userPrompt.confirmResetTitle")}
            </p>
            <p className="mt-1 text-aurion-caption text-navy-600">
              {t("userPrompt.confirmResetMessage")}
            </p>
            <div className="mt-3 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmingReset(false)}
                disabled={resetting}
                className="rounded-aurion-md px-3 py-1.5 text-aurion-callout text-navy-700 hover:bg-canvas/60 transition-colors duration-short disabled:opacity-50"
                data-testid="prompt-editor-reset-cancel"
              >
                {t("userPrompt.resetCancel")}
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={resetting}
                className="rounded-aurion-md bg-red-600 px-3 py-1.5 text-aurion-callout text-white hover:bg-red-700 transition-colors duration-short disabled:opacity-50"
                data-testid="prompt-editor-reset-confirm-button"
              >
                {t("userPrompt.resetConfirm")}
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
 * sends `{detail: {message, code, matched_phrase, missing_anchor_group}}`
 * on validation failures; the `fetchWithAuth` wrapper raises an Error
 * whose message is shaped `API <status>: <body>` — we strip that
 * prefix before attempting to parse the JSON. Anything that isn't a
 * structured validation error returns the original message so the
 * banner still has something to show.
 */
function parseServerError(
  e: unknown,
): PromptUserPromptValidationError | string {
  if (!(e instanceof Error)) {
    return "Unknown error";
  }
  // `API 400: {"detail":{"code":"banned_phrase",...}}`. The body can
  // be multi-line on some errors, so we strip the documented prefix
  // explicitly rather than relying on the `s` regex dotAll flag
  // (which requires ES2018+ and trips the TS check on older targets).
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
        missing_anchor_group: detail.missing_anchor_group ?? null,
      };
    }
  } catch {
    // Fall through to plain-message return.
  }
  return e.message;
}
