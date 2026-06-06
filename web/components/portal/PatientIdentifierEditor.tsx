"use client";

import { IdCard, Pencil, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import Button from "@/components/ui/Button";
import {
  listMySessionsByPatientIdentifier,
  setSessionExternalReferenceId,
} from "@/lib/portal-api";
import type { PatientSessionMatch } from "@/types";

/**
 * Header chip for the patient identifier on the note review screen.
 *
 * Two modes:
 *   - **Set**: shows the identifier as a gold-tinted chip; clicking
 *     opens an inline modal to edit or clear, and surfaces a
 *     "Previous encounters with this patient" linkout when count > 0.
 *   - **Unset**: shows a "Add identifier" ghost button that opens the
 *     same modal pre-focused on the input.
 *
 * PHI-aware:
 *   - The displayed text comes from the parent's decrypted Session
 *     payload — never logged.
 *   - The previous-encounters count is calculated locally from the
 *     /me/patients/{id}/sessions response (already PHI-aware
 *     server-side).
 *   - Empty / whitespace input clears the identifier (backend handles
 *     this contract).
 *
 * Localized via the `NoteReview.identifier` next-intl namespace (EN +
 * FR per #257). Client-side format gates mirror the backend
 * `_check_identifier_format` rules from `app/api/v1/sessions.py` so
 * users see the rejection before the round trip; the server is the
 * source of truth.
 */
interface PatientIdentifierEditorProps {
  sessionId: string;
  /** Current identifier (decrypted by the backend) or null. */
  currentIdentifier: string | null | undefined;
  /** Called after a successful save with the new identifier (or null
   * after clear). Parent should refresh its session data. */
  onChange: (next: string | null) => void;
}

const MAX_IDENTIFIER_LEN = 64;
const SSN_RAW = /^\d{9}$/;
const SSN_DASHED = /^\d{3}-\d{2}-\d{4}$/;

/**
 * Mirror of `backend/app/api/v1/sessions.py::_check_identifier_format`.
 * Returns `null` when the value passes, otherwise a translation key
 * suffix under `NoteReview.identifier.validation.*`.
 */
function validateIdentifier(
  raw: string,
): "ssn" | "email" | "name" | "tooLong" | null {
  const value = raw.trim();
  if (value === "") return null; // blank is a "clear" — backend allows it
  if (value.length > MAX_IDENTIFIER_LEN) return "tooLong";
  if (SSN_RAW.test(value) || SSN_DASHED.test(value)) return "ssn";
  if (value.includes("@")) return "email";
  const tokens = value.split(/\s+/).filter(Boolean);
  if (
    tokens.length >= 2 &&
    tokens.every((t) => /[A-Za-zÀ-ÿ]/.test(t))
  ) {
    return "name";
  }
  return null;
}

export default function PatientIdentifierEditor({
  sessionId,
  currentIdentifier,
  onChange,
}: PatientIdentifierEditorProps) {
  const t = useTranslations("NoteReview.identifier");
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(currentIdentifier ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [encounters, setEncounters] = useState<PatientSessionMatch[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Re-sync the draft if the parent updates the identifier externally
  // (e.g. WebSocket-driven refresh or another tab).
  useEffect(() => {
    setDraft(currentIdentifier ?? "");
  }, [currentIdentifier]);

  // Fetch prior-encounter count whenever we have an identifier.
  useEffect(() => {
    if (!currentIdentifier) {
      setEncounters([]);
      return;
    }
    let cancelled = false;
    void listMySessionsByPatientIdentifier(currentIdentifier)
      .then((rows) => {
        if (!cancelled) {
          // Drop the current session from the "previous" list — it's
          // not previous if it's the one we're reading.
          setEncounters(rows.filter((r) => r.session_id !== sessionId));
        }
      })
      .catch(() => {
        // Quiet failure — the chip still renders without the count.
      });
    return () => {
      cancelled = true;
    };
  }, [currentIdentifier, sessionId]);

  // Auto-focus the input when the modal opens.
  useEffect(() => {
    if (open) {
      const handle = window.setTimeout(() => inputRef.current?.focus(), 50);
      return () => window.clearTimeout(handle);
    }
  }, [open]);

  // Document-level Escape so the modal closes even if focus is on a
  // button rather than the input. Mirrors the keyboard shortcut on
  // the input's onKeyDown handler.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && !saving) setOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, saving]);

  // Recompute the client-side gate every render — cheap, deterministic,
  // matches the Save-disabled state.
  const validationReason = useMemo(() => validateIdentifier(draft), [draft]);
  const validationMessage = validationReason
    ? t(`validation.${validationReason}`)
    : null;

  async function save(overrideValue?: string) {
    // overrideValue lets the Clear button bypass the closure-captured
    // `draft` state (which is still the prior value at click time
    // because setDraft is async). The Save button passes nothing and
    // we use the current draft.
    const valueToSend = overrideValue !== undefined ? overrideValue : draft;
    const cleaned = valueToSend.trim();
    // Re-run the gate against the value we're actually sending so a
    // Clear bypass can't smuggle an invalid value past the Save guard.
    const gateFailure = validateIdentifier(valueToSend);
    if (gateFailure) return;
    setSaving(true);
    setError(null);
    try {
      const result = await setSessionExternalReferenceId(
        sessionId,
        cleaned || null,
      );
      onChange(result.external_reference_id ?? null);
      setOpen(false);
    } catch (e) {
      // Never echo `draft` into the error string — it may be PHI.
      // Surface the server's message (which uses reason-only strings
      // via hide_input_in_errors) or a localized fallback.
      setError(e instanceof Error ? e.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  // Save is enabled when:
  //   - the draft is structurally valid
  //   - AND the draft differs from the current value (no-op blocker)
  const draftDiffers = draft.trim() !== (currentIdentifier?.trim() ?? "");
  const canSave = !saving && draftDiffers && validationReason === null;

  return (
    <>
      {currentIdentifier ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-full bg-gold-50 px-3 py-1 text-[12.5px] font-medium text-navy-700 ring-1 ring-inset ring-gold-600/20 hover:bg-gold-100 hover:ring-gold-600/30 transition-colors duration-short"
          aria-label={t("editAria")}
        >
          <IdCard className="h-3.5 w-3.5 text-gold-600" />
          <span className="font-mono">{currentIdentifier}</span>
          {encounters.length > 0 && (
            <span className="ml-1 inline-flex items-center rounded-full bg-gold-200 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-navy-800">
              +{encounters.length}
            </span>
          )}
          <Pencil className="h-3 w-3 text-navy-300" />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-aurion-md px-2.5 py-1.5 text-[12.5px] text-navy-500 hover:bg-canvas hover:text-navy-700 transition-colors duration-short"
        >
          <IdCard className="h-4 w-4" />
          {t("addCta")}
        </button>
      )}

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="identifier-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/30 backdrop-blur-sm animate-aurion-fade-in p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget && !saving) setOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded-aurion-xl bg-surface shadow-card-hover ring-1 ring-hairline animate-aurion-scale-in">
            <div className="flex items-center justify-between border-b border-hairline px-5 py-3.5">
              <h3
                id="identifier-modal-title"
                className="aurion-headline"
              >
                {t("modalTitle")}
              </h3>
              <button
                type="button"
                onClick={() => !saving && setOpen(false)}
                className="rounded-aurion-xs p-1 text-navy-400 hover:bg-canvas hover:text-navy-700"
                aria-label={t("closeAria")}
                disabled={saving}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="px-5 py-4 space-y-3">
              <p className="aurion-caption text-navy-500">
                {t("hint")}
              </p>
              <input
                ref={inputRef}
                className="form-input font-mono"
                placeholder={t("placeholder")}
                value={draft}
                maxLength={MAX_IDENTIFIER_LEN}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && canSave) void save();
                  if (e.key === "Escape" && !saving) setOpen(false);
                }}
                disabled={saving}
                aria-label={t("inputAria")}
                aria-invalid={validationReason !== null}
                aria-describedby={
                  validationMessage ? "identifier-validation" : undefined
                }
              />
              {validationMessage && (
                <p
                  id="identifier-validation"
                  className="aurion-caption text-amber-700"
                  role="alert"
                >
                  {validationMessage}
                </p>
              )}
              {error && (
                <p className="aurion-caption text-red-600">{error}</p>
              )}
              {encounters.length > 0 && (
                <div className="rounded-aurion-md bg-canvas px-3 py-2.5">
                  <p className="aurion-micro mb-1.5">
                    {t("previousEncounters.title", {
                      count: encounters.length,
                    })}
                  </p>
                  <ul className="space-y-0.5">
                    {encounters.slice(0, 5).map((m) => (
                      <li key={m.session_id} className="flex items-center justify-between gap-2">
                        <a
                          href={`/portal/notes/${m.session_id}`}
                          className="text-aurion-caption text-navy-700 hover:text-navy-900 hover:underline"
                        >
                          {prettySpecialty(m.specialty)}
                        </a>
                        <span className="aurion-caption text-navy-400 tabular-nums">
                          {prettyDate(m.created_at)}
                        </span>
                      </li>
                    ))}
                    {encounters.length > 5 && (
                      <li className="aurion-caption text-navy-400 italic">
                        {t("previousEncounters.more", {
                          count: encounters.length - 5,
                        })}
                      </li>
                    )}
                  </ul>
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 border-t border-hairline px-5 py-3 bg-canvas/40">
              {currentIdentifier && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={saving}
                  onClick={() => {
                    setDraft("");
                    // Pass "" explicitly — setDraft is async and
                    // save()'s closure still sees the prior draft.
                    void save("");
                  }}
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  {t("clear")}
                </Button>
              )}
              <div className="flex-1" />
              <Button
                size="sm"
                variant="secondary"
                disabled={saving}
                onClick={() => setOpen(false)}
              >
                {t("cancel")}
              </Button>
              <Button
                size="sm"
                variant="primary"
                loading={saving}
                disabled={!canSave}
                onClick={() => void save()}
              >
                {t("save")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function prettySpecialty(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function prettyDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// Exported for the test module — pure function, deterministic.
export { validateIdentifier };
