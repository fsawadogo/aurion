"use client";

/**
 * Per-visit-type context editor for the web portal profile page
 * (#313/W1). The companion to `ConsultationTypesEditor` — that one owns
 * the visit-type chips; this one nests an accordion under each visit
 * type for the contexts that live beneath it.
 *
 * Mirrors the iOS context editor (I1) and the B1 backend contract:
 *   - one collapsible section per `consultation_types` entry (default
 *     key or custom label);
 *   - each context row = a label input + a built-in-template `<select>`
 *     ("Use my specialty default" + the 8 built-ins, localized) + a
 *     delete button;
 *   - an inline "Add context" affordance reusing the exact
 *     `validateConsultationType` rules (60 chars, no SSN / email /
 *     proper-noun-pair) the visit-type editor already pins;
 *   - a 30-contexts-per-visit-type soft cap.
 *
 * The parent owns state — this is a pure controlled-input, same shape
 * as `ConsultationTypesEditor`. Context labels can be PHI: they never
 * leave this component except inside the parent's PUT body.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";

import type { VisitTypeContext } from "@/types";
import {
  MAX_CONSULTATION_TYPE_LEN,
  validateConsultationType,
  type ValidationReason,
} from "@/components/portal/ConsultationTypesEditor";

/* The four built-in visit-type keys resolve through the i18n catalog;
 * anything else in `visitTypes` is a clinician-authored custom label
 * rendered verbatim. Kept in lockstep with `ConsultationTypesEditor`'s
 * own `DEFAULT_KEYS`. */
const DEFAULT_VISIT_TYPE_KEYS = [
  "new_patient",
  "follow_up",
  "pre_op",
  "post_op",
] as const;

/** The 8 built-in specialty templates a context can pin to (B1
 * contract). `null` template_key = inherit the physician's specialty
 * default — surfaced as the leading "Use my specialty default" option. */
export const BUILT_IN_TEMPLATE_KEYS = [
  "general",
  "emergency_medicine",
  "family_medicine",
  "internal_medicine",
  "musculoskeletal",
  "orthopedic_surgery",
  "pediatrics",
  "plastic_surgery",
] as const;

/** Per-visit-type soft cap. Mirrors backend
 * `_MAX_CONTEXTS_PER_VISIT_TYPE`. */
export const MAX_CONTEXTS_PER_VISIT_TYPE = 30;

/** Mint a well-formed `ctx_<8 hex>` id for a new row. Matches the
 * backend `_CONTEXT_ID_RE` so the server PRESERVES it on round-trip —
 * which keeps React keys stable across save/reload instead of churning
 * when the server would otherwise re-mint a blank id. */
export function newContextId(): string {
  const bytes = new Uint8Array(4);
  crypto.getRandomValues(bytes);
  return (
    "ctx_" +
    Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
  );
}

interface VisitTypeContextsEditorProps {
  /** The current `consultation_types` — one accordion per entry. */
  visitTypes: string[];
  /** Visit-type → context list map (`contexts_per_visit_type`). */
  value: Record<string, VisitTypeContext[]>;
  onChange: (next: Record<string, VisitTypeContext[]>) => void;
}

export default function VisitTypeContextsEditor({
  visitTypes,
  value,
  onChange,
}: VisitTypeContextsEditorProps) {
  const t = useTranslations("Profile.contexts");
  const tTemplates = useTranslations("Profile.contexts.templates");
  const tTypes = useTranslations("Profile.consultationTypes");
  const tVal = useTranslations(
    "Profile.consultationTypes.custom.validation",
  );

  // Accordion open state + the single "add context" form (one open at a
  // time across all sections keeps the surface calm).
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  // Built-in template options, localized + sorted by display name so the
  // list reads naturally in either locale.
  const templateOptions = BUILT_IN_TEMPLATE_KEYS.map((key) => ({
    key,
    label: tTemplates(key),
  })).sort((a, b) => a.label.localeCompare(b.label));

  function visitTypeLabel(vt: string): string {
    return (DEFAULT_VISIT_TYPE_KEYS as readonly string[]).includes(vt)
      ? tTypes(vt)
      : vt;
  }

  function toggleOpen(vt: string) {
    const next = new Set(open);
    if (next.has(vt)) next.delete(vt);
    else next.add(vt);
    setOpen(next);
  }

  /** Replace one visit type's context list. An empty list drops the
   * key entirely so an untouched visit type never bloats the map (and
   * never shows up as a spurious dirty diff). */
  function setContexts(vt: string, next: VisitTypeContext[]) {
    const map: Record<string, VisitTypeContext[]> = { ...value };
    if (next.length === 0) delete map[vt];
    else map[vt] = next;
    onChange(map);
  }

  function updateContext(
    vt: string,
    id: string,
    patch: Partial<VisitTypeContext>,
  ) {
    const list = value[vt] ?? [];
    setContexts(
      vt,
      list.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    );
  }

  function removeContext(vt: string, id: string) {
    const list = value[vt] ?? [];
    setContexts(
      vt,
      list.filter((c) => c.id !== id),
    );
  }

  function startAdd(vt: string) {
    setAddingFor(vt);
    setDraft("");
    if (!open.has(vt)) toggleOpen(vt);
  }

  function cancelAdd() {
    setAddingFor(null);
    setDraft("");
  }

  function commitAdd(vt: string) {
    const list = value[vt] ?? [];
    const reason = validateConsultationType(
      draft,
      list.map((c) => c.label),
    );
    if (reason !== null) return;
    setContexts(vt, [
      ...list,
      {
        id: newContextId(),
        label: draft.trim(),
        template_key: null,
        template_ref: null,
      },
    ]);
    setDraft("");
    setAddingFor(null);
  }

  if (visitTypes.length === 0) {
    return (
      <fieldset className="block">
        <legend className="text-sm font-medium text-navy-800 mb-1.5">
          {t("label")}
        </legend>
        <p className="text-xs text-gray-500">{t("noVisitTypes")}</p>
      </fieldset>
    );
  }

  return (
    <fieldset className="block">
      <legend className="text-sm font-medium text-navy-800 mb-1.5">
        {t("label")}
      </legend>
      <p className="text-xs text-gray-500 mb-3">{t("description")}</p>

      <div className="space-y-2">
        {visitTypes.map((vt) => {
          const contexts = value[vt] ?? [];
          const isOpen = open.has(vt);
          const adding = addingFor === vt;
          const atLimit = contexts.length >= MAX_CONTEXTS_PER_VISIT_TYPE;
          const validation: ValidationReason = adding
            ? validateConsultationType(
                draft,
                contexts.map((c) => c.label),
              )
            : null;
          const showValidationError =
            adding && validation !== null && validation !== "empty";
          const panelId = `ctx-panel-${vt}`;

          return (
            <div
              key={vt}
              className="rounded-aurion-md border border-gray-200 bg-white"
            >
              <button
                type="button"
                onClick={() => toggleOpen(vt)}
                aria-expanded={isOpen}
                aria-controls={panelId}
                className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left"
              >
                <span className="flex items-center gap-2">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                    className={
                      "h-4 w-4 text-gray-500 transition-transform duration-150 " +
                      (isOpen ? "rotate-90" : "")
                    }
                  >
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                  <span className="text-sm font-medium text-navy-900">
                    {visitTypeLabel(vt)}
                  </span>
                </span>
                {contexts.length > 0 && (
                  <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-gold-50 px-1.5 text-xs font-medium text-navy-800">
                    {contexts.length}
                  </span>
                )}
              </button>

              {isOpen && (
                <div
                  id={panelId}
                  className="border-t border-gray-100 px-3 py-3 space-y-2"
                >
                  {contexts.length === 0 && !adding && (
                    <p className="text-xs text-gray-500">{t("empty")}</p>
                  )}

                  {contexts.map((ctx) => (
                    <div
                      key={ctx.id}
                      className="flex flex-col gap-2 sm:flex-row sm:items-center"
                    >
                      <input
                        type="text"
                        value={ctx.label}
                        onChange={(e) =>
                          updateContext(vt, ctx.id, {
                            label: e.target.value,
                          })
                        }
                        aria-label={t("labelAria", {
                          label: ctx.label,
                        })}
                        maxLength={MAX_CONSULTATION_TYPE_LEN + 1}
                        className="form-input flex-1"
                      />
                      <select
                        value={ctx.template_key ?? ""}
                        onChange={(e) =>
                          updateContext(vt, ctx.id, {
                            template_key:
                              e.target.value === ""
                                ? null
                                : e.target.value,
                          })
                        }
                        aria-label={t("templateAria", {
                          label: ctx.label,
                        })}
                        className="form-select sm:w-56"
                      >
                        <option value="">{t("defaultTemplate")}</option>
                        {templateOptions.map((o) => (
                          <option key={o.key} value={o.key}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => removeContext(vt, ctx.id)}
                        aria-label={t("delete", { label: ctx.label })}
                        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-gray-500 hover:bg-red-50 hover:text-red-600"
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
                          <path d="M18 6 6 18" />
                          <path d="m6 6 12 12" />
                        </svg>
                      </button>
                    </div>
                  ))}

                  {/* Add affordance — mirrors ConsultationTypesEditor. */}
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
                              commitAdd(vt);
                            } else if (e.key === "Escape") {
                              e.preventDefault();
                              cancelAdd();
                            }
                          }}
                          placeholder={t("placeholder")}
                          aria-label={t("inputLabel")}
                          maxLength={MAX_CONSULTATION_TYPE_LEN + 1}
                          autoFocus
                          className="form-input flex-1"
                        />
                        <button
                          type="button"
                          onClick={() => commitAdd(vt)}
                          disabled={validation !== null}
                          className="rounded-md bg-gold-500 px-3 py-1.5 text-sm font-medium text-navy-900 hover:bg-gold-600 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {t("add")}
                        </button>
                        <button
                          type="button"
                          onClick={cancelAdd}
                          className="rounded-md px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
                        >
                          {t("cancel")}
                        </button>
                      </div>
                      {showValidationError && validation !== null && (
                        <p className="text-xs text-red-600" role="alert">
                          {tVal(validation)}
                        </p>
                      )}
                    </div>
                  ) : atLimit ? (
                    <p className="text-xs text-gray-500">{t("limit")}</p>
                  ) : (
                    <button
                      type="button"
                      onClick={() => startAdd(vt)}
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
                      {t("addContext")}
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}
