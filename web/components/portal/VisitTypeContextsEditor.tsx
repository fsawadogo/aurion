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
 *   - a "Default template" select at the top of each panel (TE-4h) — the
 *     visit type's `is_default` context (#577), i.e. the template used when
 *     no context is picked on the device. Rendered as a dedicated control,
 *     never as a context row, and summarized on the collapsed header;
 *   - each context row = a label input + a template `<select>`
 *     ("Use my specialty default" + a "Custom templates" optgroup of the
 *     caller's OWNED custom templates, all localized) + a delete button.
 *     Specialty is a profile property, not a per-context pick (TE-4e), so
 *     the flat built-in list is gone; a context pins only the default or a
 *     custom `template_ref` (they clear each other, mirroring the backend
 *     `VisitTypeContext` validator #318/B3, #320/W2);
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

/** The 8 built-in specialty template keys (B1 contract). Still consumed by
 * the upload flow + the Templates → Visit-Types tab; TE-4e removed them from
 * THIS editor's picker (specialty is a profile property, not a per-context
 * pick), leaving only the "Use my specialty default" option + the caller's
 * custom templates. */
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

/** Per-context description cap. Mirrors the backend `validate_user_text`
 * ≤500-char limit on `VisitTypeContext.description` (#576). The server
 * re-validates; this is just a kind client-side guardrail. */
export const MAX_CONTEXT_DESCRIPTION_LEN = 500;

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

/** Slim custom-template option for the per-context picker (#320/W2).
 *
 * The parent fetches `GET /me/custom-templates` and passes ONLY the
 * caller's OWNED rows mapped to `{id, display_name}`. A community-shared
 * row the caller doesn't own would 422 on the PUT (the backend binds a
 * `template_ref` via the owner-scoped `get_owned`), so the parent
 * filters to owned before handing them down. `id` is the value written
 * into a context's `template_ref`. Display names can be PHI — they ride
 * this prop only, never a client log. */
export interface ContextCustomTemplate {
  id: string;
  display_name: string;
}

/** The two nullable pin pointers of a context row (or a panel's default).
 * `null` = the row doesn't exist — an unset default. */
type TemplateBinding = Pick<
  VisitTypeContext,
  "template_key" | "template_ref"
> | null;

interface VisitTypeContextsEditorProps {
  /** The current `consultation_types` — one accordion per entry. */
  visitTypes: string[];
  /** Visit-type → context list map (`contexts_per_visit_type`). */
  value: Record<string, VisitTypeContext[]>;
  onChange: (next: Record<string, VisitTypeContext[]>) => void;
  /** Caller's OWNED custom templates → the "Custom templates" optgroup
   * (#320/W2). Defaults to `[]` so the empty-library case (and the W1
   * call sites / tests that don't pass it) render just the "Use my
   * specialty default" option (TE-4e removed the built-in list). */
  customTemplates?: ContextCustomTemplate[];
}

export default function VisitTypeContextsEditor({
  visitTypes,
  value,
  onChange,
  customTemplates = [],
}: VisitTypeContextsEditorProps) {
  const t = useTranslations("Profile.contexts");
  const tTypes = useTranslations("Profile.consultationTypes");
  const tVal = useTranslations(
    "Profile.consultationTypes.custom.validation",
  );

  // Accordion open state + the single "add context" form (one open at a
  // time across all sections keeps the surface calm).
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  // Custom-template options for the "Custom templates" optgroup (#320/W2).
  // Sorted by display name for a stable, readable order. The display name
  // can be PHI, so it never leaves this render path — no logging.
  const customOptions = customTemplates
    .map((c) => ({ id: c.id, label: c.display_name }))
    .sort((a, b) => a.label.localeCompare(b.label));

  // Membership set the change handler uses to route a selected option to
  // the right field. TE-4e: only custom templates are selectable now, so a
  // built-in key can no longer be picked — no built-in set needed.
  const customIdSet = new Set(customTemplates.map((c) => c.id));

  /** The select value for a binding: a custom `template_ref` wins over a
   * built-in `template_key` — the two are mutually exclusive, but reading
   * both defends against a half-applied row. "" = specialty default. */
  function bindingValue(b: TemplateBinding): string {
    return b?.template_ref ?? b?.template_key ?? "";
  }

  /** The ONE option list both template selects render (context rows + the
   * panel's default): specialty default + the customs optgroup, plus two
   * guards against a silent blank <select> — a legacy built-in pin
   * (pre-TE-4e, or iOS) and a stale custom ref each stay visible as a
   * placeholder whose value equals the pin, so the binding round-trips and
   * the physician can re-pick. (Retiring stored built-in pins server-side is
   * a separate backend task.) */
  function templateOptions(b: TemplateBinding) {
    return (
      <>
        <option value="">{t("defaultTemplate")}</option>
        {b && b.template_ref === null && b.template_key !== null && (
          <option value={b.template_key}>
            {t("legacySpecialtyTemplate")}
          </option>
        )}
        {customOptions.length > 0 && (
          <optgroup label={t("customGroup")}>
            {customOptions.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </optgroup>
        )}
        {b?.template_ref != null && !customIdSet.has(b.template_ref) && (
          <option value={b.template_ref}>{t("customUnavailable")}</option>
        )}
      </>
    );
  }

  /** Collapsed-summary name for a default binding — derived from the same
   * guards as `templateOptions`, so the header can never disagree with what
   * the expanded select shows. */
  function defaultTemplateName(b: TemplateBinding): string {
    if (b?.template_ref != null) {
      return (
        customOptions.find((o) => o.id === b.template_ref)?.label ??
        t("customUnavailable")
      );
    }
    if (b?.template_key != null) return t("legacySpecialtyTemplate");
    return t("default.summarySpecialty");
  }

  /** Apply a template `<select>` choice to one context. TE-4e: specialty is
   * a profile property, so a context pins ONLY the default or a custom
   * template:
   *   - "" (default) → clear BOTH pointers (inherit specialty default);
   *   - custom id    → set `template_ref`, clear `template_key`.
   * A value matching neither (a stale ref re-selected, or a legacy built-in
   * `template_key` with no matching option) leaves the binding untouched —
   * `onChange` only fires on a real change. */
  function selectTemplate(vt: string, id: string, optionValue: string) {
    if (optionValue === "") {
      updateContext(vt, id, { template_key: null, template_ref: null });
    } else if (customIdSet.has(optionValue)) {
      updateContext(vt, id, {
        template_ref: optionValue,
        template_key: null,
      });
    }
  }

  function visitTypeLabel(vt: string): string {
    return (DEFAULT_VISIT_TYPE_KEYS as readonly string[]).includes(vt)
      ? tTypes(vt)
      : vt;
  }

  /** Apply the panel's "Default template" pick (TE-4h). "" drops the
   * `is_default` row — inherit the specialty default; a custom id upserts it,
   * preserving the row's id/label/description so a re-pick round-trips. A
   * value matching neither (re-selecting the legacy or stale placeholder)
   * never reaches here — a `<select>` only fires onChange on a real change. */
  function setDefaultTemplate(vt: string, optionValue: string) {
    const list = value[vt] ?? [];
    const rest = list.filter((c) => !c.is_default);
    if (optionValue === "") {
      setContexts(vt, rest);
    } else if (customIdSet.has(optionValue)) {
      const prev = list.find((c) => c.is_default);
      setContexts(vt, [
        ...rest,
        {
          id: prev?.id ?? newContextId(),
          label: prev?.label || visitTypeLabel(vt),
          template_key: null,
          template_ref: optionValue,
          is_default: true,
          description: prev?.description ?? null,
        },
      ]);
    }
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
        description: null,
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
          // TE-4h: the `is_default` row is the visit type's DEFAULT — shown
          // as the panel's dedicated select, never as a context row. The cap
          // and duplicate-label validation run on the FULL list because the
          // backend validates the full list.
          const list = value[vt] ?? [];
          const defaultCtx = list.find((c) => c.is_default) ?? null;
          const contexts = list.filter((c) => !c.is_default);
          const isOpen = open.has(vt);
          const adding = addingFor === vt;
          const atLimit = list.length >= MAX_CONTEXTS_PER_VISIT_TYPE;
          const validation: ValidationReason = adding
            ? validateConsultationType(
                draft,
                list.map((c) => c.label),
              )
            : null;
          const defaultName = defaultTemplateName(defaultCtx);
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
                <span className="flex min-w-0 items-center gap-2">
                  {/* Collapsed summary (TE-4h): the whole mapping is
                      scannable without expanding. Display names can be PHI —
                      render-only, never logged. */}
                  <span className="truncate text-xs text-gray-500">
                    {t("default.summary", { name: defaultName })}
                  </span>
                  {contexts.length > 0 && (
                    <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-gold-50 px-1.5 text-xs font-medium text-navy-800">
                      {contexts.length}
                    </span>
                  )}
                </span>
              </button>

              {isOpen && (
                <div
                  id={panelId}
                  className="border-t border-gray-100 px-3 py-3 space-y-2"
                >
                  {/* TE-4h: the visit type's default template — a dedicated
                      control over the `is_default` row, so it can never be
                      mistaken for (or deleted as) a context. */}
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                    <span className="shrink-0 text-sm font-medium text-navy-800 sm:w-40">
                      {t("default.label")}
                    </span>
                    <select
                      value={bindingValue(defaultCtx)}
                      onChange={(e) => setDefaultTemplate(vt, e.target.value)}
                      aria-label={t("default.aria", {
                        visit: visitTypeLabel(vt),
                      })}
                      className="form-select flex-1"
                    >
                      {templateOptions(defaultCtx)}
                    </select>
                  </div>
                  <p className="pb-1 text-xs text-gray-500">
                    {t("default.hint")}
                  </p>

                  {contexts.length === 0 && !adding && (
                    <p className="text-xs text-gray-500">{t("empty")}</p>
                  )}

                  {contexts.map((ctx) => (
                    <div key={ctx.id} className="space-y-2">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
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
                          value={bindingValue(ctx)}
                          onChange={(e) =>
                            selectTemplate(vt, ctx.id, e.target.value)
                          }
                          aria-label={t("templateAria", {
                            label: ctx.label,
                          })}
                          className="form-select sm:w-56"
                        >
                          {templateOptions(ctx)}
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
                      <textarea
                        value={ctx.description ?? ""}
                        onChange={(e) =>
                          updateContext(vt, ctx.id, {
                            description:
                              e.target.value === "" ? null : e.target.value,
                          })
                        }
                        placeholder={t("descriptionPlaceholder")}
                        aria-label={t("descriptionAria", { label: ctx.label })}
                        maxLength={MAX_CONTEXT_DESCRIPTION_LEN}
                        rows={2}
                        className="form-input w-full text-sm resize-y"
                      />
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
