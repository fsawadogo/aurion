"use client";

/**
 * Consultation-types editor for the web portal profile page (#259).
 *
 * Mirrors the iOS `PhysicianProfileSetupView.visitTypesStep` UI:
 *   - the four default keys ("new_patient", "follow_up", "pre_op",
 *     "post_op") render as toggleable chips that resolve through the
 *     i18n catalog;
 *   - clinician-authored custom labels render as chips below;
 *   - an "Add custom type" input + Add/Cancel pair lives below the
 *     chips, with client-side format gates that mirror the backend
 *     `validate_user_text` helper for instant feedback.
 *
 * The parent owns state — this component is a pure controlled-input,
 * same shape as `MultiSelect` higher up the page. The exported
 * `validateConsultationType` is the pure-function gate the tests pin.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";

const DEFAULT_KEYS = [
  "new_patient",
  "follow_up",
  "pre_op",
  "post_op",
] as const;

export const MAX_CUSTOM_CONSULTATION_TYPES = 20;
export const MAX_CONSULTATION_TYPE_LEN = 60;

const SSN_RAW = /^\d{9}$/;
const SSN_DASHED = /^\d{3}-\d{2}-\d{4}$/;

export type ValidationReason =
  | "empty"
  | "tooLong"
  | "ssn"
  | "email"
  | "name"
  | "duplicate"
  | null;

/**
 * Pure function that mirrors `backend/app/api/v1/profile.py::
 * _validate_consultation_type` (which in turn calls the shared
 * `validate_user_text` helper). Returns `null` on pass, otherwise a
 * translation-key suffix under
 * `Profile.consultationTypes.custom.validation.*`.
 *
 * `existing` carries the current custom-type list so we can flag the
 * "already in the list" case before the user hits Add. Defaults are
 * checked against the canonical 4 keys.
 */
/** Returns true when the token starts with an uppercase letter and
 * contains only letters (Latin + diacritics), apostrophes, or hyphens.
 * Matches the backend ``_looks_like_proper_noun_pair`` per-token check.
 */
function isProperNounToken(token: string): boolean {
  if (token.length === 0) return false;
  const first = token.charAt(0);
  // Uppercase letter — ASCII A-Z plus Latin-1 supplement uppercase
  // (À..Þ except ×).
  const isUpper = (c: string): boolean => {
    const code = c.charCodeAt(0);
    return (
      (code >= 0x41 && code <= 0x5a) ||
      (code >= 0xc0 && code <= 0xde && code !== 0xd7)
    );
  };
  if (!isUpper(first)) return false;
  // Every char letter / apostrophe / hyphen / curly apostrophe.
  for (let i = 0; i < token.length; i++) {
    const c = token.charAt(i);
    const code = c.charCodeAt(0);
    const isLetter =
      (code >= 0x41 && code <= 0x5a) ||
      (code >= 0x61 && code <= 0x7a) ||
      (code >= 0xc0 && code <= 0xff && code !== 0xd7 && code !== 0xf7);
    if (!isLetter && c !== "'" && c !== "-" && c !== "’") {
      return false;
    }
  }
  return true;
}

export function validateConsultationType(
  raw: string,
  existing: string[],
): ValidationReason {
  const trimmed = raw.trim();
  if (trimmed === "") return "empty";
  if (trimmed.length > MAX_CONSULTATION_TYPE_LEN) return "tooLong";
  if (SSN_RAW.test(trimmed) || SSN_DASHED.test(trimmed)) return "ssn";
  if (trimmed.includes("@")) return "email";
  // Two-token proper-noun shape — catches "Jane Doe" / "Marie
  // Gdalevitch" without rejecting legitimate clinician shorthand
  // like "LL fu" or "Breast visit". Mirrors the backend
  // `_looks_like_proper_noun_pair` heuristic exactly. Implemented
  // without the `u` flag so the TS config's default ES target is
  // happy. Accent + diacritic coverage handled via the Latin-1
  // supplement range.
  const tokens = trimmed.split(/\s+/).filter(Boolean);
  if (
    tokens.length >= 2 &&
    tokens.every((t) => isProperNounToken(t))
  ) {
    return "name";
  }
  if (
    existing.includes(trimmed) ||
    (DEFAULT_KEYS as readonly string[]).includes(trimmed)
  ) {
    return "duplicate";
  }
  return null;
}

interface ConsultationTypesEditorProps {
  /** Full canonical list as currently persisted — mix of default keys
   *  and clinician-authored custom strings. */
  value: string[];
  onChange: (next: string[]) => void;
}

export default function ConsultationTypesEditor({
  value,
  onChange,
}: ConsultationTypesEditorProps) {
  const t = useTranslations("Profile.consultationTypes");
  const tCustom = useTranslations("Profile.consultationTypes.custom");
  const tVal = useTranslations(
    "Profile.consultationTypes.custom.validation",
  );

  const selectedDefaults = new Set(
    value.filter((v) => (DEFAULT_KEYS as readonly string[]).includes(v)),
  );
  const customTypes = value.filter(
    (v) => !(DEFAULT_KEYS as readonly string[]).includes(v),
  );

  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState(false);

  const validation = adding
    ? validateConsultationType(draft, customTypes)
    : null;
  const showValidationError =
    adding && validation !== null && validation !== "empty";

  function toggleDefault(key: string) {
    const next = new Set(selectedDefaults);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange([
      ...DEFAULT_KEYS.filter((k) => next.has(k)),
      ...customTypes,
    ]);
  }

  function removeCustom(name: string) {
    onChange(value.filter((v) => v !== name));
  }

  function commitDraft() {
    const reason = validateConsultationType(draft, customTypes);
    if (reason !== null) return;
    onChange([
      ...DEFAULT_KEYS.filter((k) => selectedDefaults.has(k)),
      ...customTypes,
      draft.trim(),
    ]);
    setDraft("");
    setAdding(false);
  }

  function cancelAdd() {
    setDraft("");
    setAdding(false);
  }

  const atLimit = customTypes.length >= MAX_CUSTOM_CONSULTATION_TYPES;

  return (
    <fieldset className="block">
      <legend className="text-sm font-medium text-navy-800 mb-1.5">
        {t("label")}
      </legend>
      <div className="flex flex-wrap gap-2">
        {DEFAULT_KEYS.map((key) => {
          const active = selectedDefaults.has(key);
          return (
            <button
              key={key}
              type="button"
              onClick={() => toggleDefault(key)}
              aria-pressed={active}
              className={
                "rounded-full border px-3 py-1.5 text-sm transition-colors " +
                (active
                  ? "border-gold-500 bg-gold-50 text-navy-900 font-medium"
                  : "border-gray-200 text-gray-700 hover:border-gray-300")
              }
            >
              {t(key)}
            </button>
          );
        })}
        {customTypes.map((name) => (
          <span
            key={name}
            className="inline-flex items-center gap-1.5 rounded-full border border-gold-500 bg-gold-50 px-3 py-1.5 text-sm text-navy-900 font-medium"
          >
            {name}
            <button
              type="button"
              onClick={() => removeCustom(name)}
              aria-label={tCustom("delete", { name })}
              className="ml-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full text-navy-600 hover:bg-gold-100 hover:text-navy-900"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                className="h-3 w-3"
              >
                <path d="M18 6 6 18" />
                <path d="m6 6 12 12" />
              </svg>
            </button>
          </span>
        ))}
      </div>

      {/* Add affordance. Mirrors the iOS inline-add pattern — we keep
          the textbox + actions in the same row so the user doesn't
          have to switch contexts mid-add. */}
      <div className="mt-3">
        {adding ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitDraft();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    cancelAdd();
                  }
                }}
                placeholder={tCustom("placeholder")}
                aria-label={tCustom("inputLabel")}
                maxLength={MAX_CONSULTATION_TYPE_LEN + 1}
                autoFocus
                className="form-input flex-1"
              />
              <button
                type="button"
                onClick={commitDraft}
                disabled={validation !== null}
                className="rounded-md bg-gold-500 px-3 py-1.5 text-sm font-medium text-navy-900 hover:bg-gold-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {tCustom("add")}
              </button>
              <button
                type="button"
                onClick={cancelAdd}
                className="rounded-md px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
              >
                {tCustom("cancel")}
              </button>
            </div>
            {showValidationError && validation !== null && (
              <p className="text-xs text-red-600" role="alert">
                {tVal(validation)}
              </p>
            )}
          </div>
        ) : atLimit ? (
          <p className="text-xs text-gray-500">{tCustom("limit")}</p>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:border-gold-500 hover:text-navy-900"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className="h-4 w-4"
            >
              <path d="M5 12h14" />
              <path d="M12 5v14" />
            </svg>
            {tCustom("addCustom")}
          </button>
        )}
      </div>
    </fieldset>
  );
}
