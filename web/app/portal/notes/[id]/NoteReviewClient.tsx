"use client";

import { AlertTriangle, ClipboardCheck, Copy, Download, Printer } from "lucide-react";
import {
  humanizeError,
  RegenerateDiscardError,
  regenerateNote,
  type RegenerateWouldDiscard,
} from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { useRouteSegment } from "@/lib/use-route-segment";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import CodingSuggestionsCard from "@/components/portal/CodingSuggestionsCard";
import CompletenessRing from "@/components/portal/CompletenessRing";
import EmrWriteBackCard from "@/components/portal/EmrWriteBackCard";
import LivePreviewCard from "@/components/portal/LivePreviewCard";
import NoteAssistChat from "@/components/portal/NoteAssistChat";
import NoteContextBadge from "@/components/portal/NoteContextBadge";
import NoteSectionCard from "@/components/portal/NoteSectionCard";
import OrdersCard from "@/components/portal/OrdersCard";
import PageHeader from "@/components/portal/PageHeader";
import PatientIdentifierEditor from "@/components/portal/PatientIdentifierEditor";
import PatientSummaryCard from "@/components/portal/PatientSummaryCard";
import PreviewVsFinalCard from "@/components/portal/PreviewVsFinalCard";
import StageTwoProgressBanner from "@/components/portal/StageTwoProgressBanner";
import { BUILT_IN_TEMPLATE_KEYS } from "@/components/portal/VisitTypeContextsEditor";
import {
  approveAll,
  assistNote,
  editNote,
  exportNote,
  getNoteDetail,
  getPortalFeatureFlags,
  getSession,
  listMyCustomTemplates,
  listMyMacros,
  resolveConflict,
} from "@/lib/portal-api";
import { filterForSpecialty } from "@/lib/portal-macros-expand";
import { humanSpecialty } from "@/lib/session-format";
import type {
  Claim,
  CustomTemplate,
  NoteAssistResponse,
  NoteDetail,
  PhysicianMacro,
  Session as SessionRow,
} from "@/types";

/**
 * /portal/notes/[id] — the note review screen (loop-4 redesign).
 *
 * Single continuous note document (centre) + an action rail (right). The
 * transcript/citation surface moved off the main screen (2026-07-15 weekly,
 * Marie) — citations are a super-user surface and return behind their flag in
 * loop-4b, so a day-1 note is clean. Copy to EHR is the primary action and is
 * deliberately NOT gated on approval (product decision) — copying is not
 * signing. Conflicts, per-section edit, and approve-blocked-on-conflicts are
 * preserved exactly from the prior layout.
 *
 * Template + language switch re-run Stage 1 via `regenerateNote`; on the
 * backend's 409 loss gate (#590) the physician confirms before work that
 * can't be rebuilt is dropped.
 */
export default function NoteReviewPage() {
  const t = useTranslations("NoteReview");
  const tTemplates = useTranslations("Profile.contexts.templates");
  const sessionId = useRouteSegment("id");

  const [detail, setDetail] = useState<NoteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [noNoteYet, setNoNoteYet] = useState(false);
  const [session, setSession] = useState<SessionRow | null>(null);
  const [macros, setMacros] = useState<PhysicianMacro[]>([]);
  const [customTemplates, setCustomTemplates] = useState<CustomTemplate[]>([]);
  const [chatEnabled, setChatEnabled] = useState(false);
  // Pending regenerate that hit the loss gate — holds the counts + the retry.
  const [discardPrompt, setDiscardPrompt] = useState<{
    counts: RegenerateWouldDiscard;
    onConfirm: () => void;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void listMyMacros()
      .then((xs) => !cancelled && setMacros(xs))
      .catch(() => {});
    void listMyCustomTemplates()
      .then((xs) => !cancelled && setCustomTemplates(xs))
      .catch(() => {});
    void getPortalFeatureFlags()
      .then((f) => !cancelled && setChatEnabled(f.note_review_chat_enabled))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNoNoteYet(false);
    try {
      const [d, s] = await Promise.allSettled([
        getNoteDetail(sessionId),
        getSession(sessionId),
      ]);
      if (d.status === "fulfilled") {
        setDetail(d.value);
      } else {
        const msg = d.reason instanceof Error ? d.reason.message : t("loadError");
        if (/\b404\b/.test(msg)) setNoNoteYet(true);
        else setError(msg);
      }
      if (s.status === "fulfilled") setSession(s.value);
    } finally {
      setLoading(false);
    }
  }, [sessionId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSaveEdit(sectionId: string, newText: string) {
    if (!detail) return;
    await editNote(sessionId, { [sectionId]: newText });
    await load();
  }

  async function onResolveConflict(
    claim: Claim,
    action: "accept_visual" | "reject_visual" | "edit",
    resolutionText?: string,
  ) {
    if (!detail) return;
    await resolveConflict(sessionId, claim.id, action, resolutionText);
    await load();
  }

  async function onAssist(message: string): Promise<NoteAssistResponse> {
    const res = await assistNote(sessionId, message);
    if (res.applied) await load();
    return res;
  }

  // Template + language both re-run Stage 1. One handler so both share the
  // loss-gate confirm: on a 409, stash the counts + a retry that carries
  // confirm_discard, and let the physician decide.
  const doRegenerate = useCallback(
    async (payload: {
      template_key?: string;
      custom_template_id?: string;
      output_language?: string;
      confirm_discard?: boolean;
    }) => {
      setError(null);
      setRegenerating(true);
      try {
        await regenerateNote(sessionId, payload);
        await load();
      } catch (e) {
        if (e instanceof RegenerateDiscardError) {
          setDiscardPrompt({
            counts: e.wouldDiscard,
            onConfirm: () => {
              setDiscardPrompt(null);
              void doRegenerate({ ...payload, confirm_discard: true });
            },
          });
        } else {
          setError(humanizeError(e, t("regenerateError")));
        }
      } finally {
        setRegenerating(false);
      }
    },
    [sessionId, load, t],
  );

  function onCopy() {
    if (!detail) return;
    // TODO(loop-3): replace client assembly with GET /notes/{id}/text so web,
    // DOCX and iOS share one canonical renderer.
    const text = buildNoteText(detail);
    void (navigator.clipboard?.writeText
      ? navigator.clipboard.writeText(text)
      : Promise.reject(new Error("clipboard unavailable"))
    ).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2400);
      },
      () => setError(t("copyError")),
    );
  }

  async function onApprove() {
    if (!detail) return;
    setApproving(true);
    setError(null);
    try {
      await approveAll(sessionId);
      await load();
    } catch (e) {
      setError(humanizeError(e, t("approvalError")));
    } finally {
      setApproving(false);
    }
  }

  async function onExport() {
    setExporting(true);
    setError(null);
    try {
      const blob = await exportNote(sessionId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aurion_note_${sessionId}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      await load();
    } catch (e) {
      setError(humanizeError(e, t("exportError")));
    } finally {
      setExporting(false);
    }
  }

  // Filter macros once per render, not once per section — the args are the
  // same for every card.
  const specialtyMacros = detail
    ? filterForSpecialty(macros, detail.note.specialty)
    : [];

  return (
    <div className="aurion-page-padded aurion-container">
      <PageHeader
        breadcrumb={[
          { label: t("breadcrumbNotes"), href: "/portal/notes" },
          { label: detail ? humanSpecialty(detail.note.specialty) : t("breadcrumbFallback") },
        ]}
        eyebrow={t("eyebrow")}
        title={detail ? humanSpecialty(detail.note.specialty) : t("breadcrumbFallback")}
        description={
          detail ? (
            <>
              {t("stageMetaPrefix")} <span className="font-semibold text-navy-700">{detail.note.stage}</span>
              {" · "}{t("stageVersion")}<span className="font-semibold text-navy-700">{detail.note.version}</span>
              {" · "}{t("stageProvider")} <span className="font-semibold text-navy-700">{detail.note.provider_used}</span>
            </>
          ) : undefined
        }
        actions={
          detail ? (
            <div className="flex items-center gap-2">
              <NoteContextBadge
                encountersReferenced={detail.note.prior_context_used?.encounters_referenced ?? 0}
                identifier={detail.export_metadata.external_reference_id}
              />
              <PatientIdentifierEditor
                sessionId={sessionId}
                currentIdentifier={detail.export_metadata.external_reference_id}
                onChange={() => void load()}
              />
            </div>
          ) : undefined
        }
      />

      {loading && !detail ? (
        <Card>
          <LoadingSkeleton lines={12} />
        </Card>
      ) : noNoteYet ? (
        <div className="space-y-4">
          {session && <LivePreviewCard sessionId={sessionId} sessionState={session.state} />}
          <Card>
            <div className="text-center py-10">
              <p className="aurion-headline text-navy-700 mb-1.5">{t("noNoteTitle")}</p>
              <p className="aurion-callout text-navy-500 max-w-md mx-auto">{t("noNoteHint")}</p>
              <Button variant="secondary" size="sm" className="mt-5" onClick={() => void load()}>
                {t("checkAgain")}
              </Button>
            </div>
          </Card>
        </div>
      ) : error && !detail ? (
        <Card>
          <p className="aurion-callout text-red-600">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void load()}>
            {t("retry")}
          </Button>
        </Card>
      ) : detail ? (
        <div className="space-y-4">
          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <StageTwoProgressBanner
            sessionId={sessionId}
            enabled={
              detail.export_metadata.session_state === "PROCESSING_STAGE2" ||
              detail.export_metadata.session_state === "AWAITING_REVIEW"
            }
            onCompleted={() => void load()}
          />

          {detail.conflict_state.has_unresolved && (
            <ConflictsBanner
              count={detail.conflict_state.unresolved_count}
              firstSectionId={detail.conflict_state.unresolved_section_ids[0]}
            />
          )}

          {discardPrompt && (
            <DiscardPrompt
              counts={discardPrompt.counts}
              onConfirm={discardPrompt.onConfirm}
              onCancel={() => setDiscardPrompt(null)}
            />
          )}

          {/* Note document (centre) + action rail (right). */}
          <div className="flex flex-col lg:flex-row gap-4 items-start">
            <div className="flex-1 min-w-0 w-full space-y-4">
              <Card>
                {/* Toolbar — template · language · print · export · copy. */}
                <div className="mb-5 flex flex-wrap items-center gap-2 border-b border-hairline pb-4">
                  <select
                    aria-label={t("toolbar.templateLabel")}
                    disabled={regenerating}
                    defaultValue=""
                    onChange={(e) => {
                      const v = e.target.value;
                      e.currentTarget.selectedIndex = 0;
                      if (!v) return;
                      if (v.startsWith("custom:")) {
                        void doRegenerate({ custom_template_id: v.slice("custom:".length) });
                      } else {
                        void doRegenerate({ template_key: v });
                      }
                    }}
                    className="form-input h-9 py-0 text-aurion-caption font-semibold"
                  >
                    <option value="">{t("toolbar.changeTemplate")}</option>
                    <optgroup label={t("toolbar.builtInGroup")}>
                      {BUILT_IN_TEMPLATE_KEYS.map((key) => (
                        <option key={key} value={key}>
                          {tTemplates(key)}
                        </option>
                      ))}
                    </optgroup>
                    {customTemplates.length > 0 && (
                      <optgroup label={t("toolbar.customGroup")}>
                        {customTemplates.map((c) => (
                          <option key={c.id} value={`custom:${c.id}`}>
                            {c.display_name}
                          </option>
                        ))}
                      </optgroup>
                    )}
                  </select>

                  <div className="inline-flex rounded-aurion-md bg-canvas p-0.5">
                    {(["en", "fr"] as const).map((lng) => (
                      <button
                        key={lng}
                        type="button"
                        disabled={regenerating}
                        onClick={() => void doRegenerate({ output_language: lng })}
                        className="rounded-aurion-sm px-3 py-1 text-aurion-caption font-semibold text-navy-600 hover:bg-white disabled:opacity-50"
                      >
                        {t(`toolbar.lang_${lng}`)}
                      </button>
                    ))}
                  </div>

                  <div className="flex-1" />
                  {regenerating && (
                    <span className="text-aurion-caption text-navy-400">{t("toolbar.regenerating")}</span>
                  )}

                  <button
                    type="button"
                    onClick={() => window.print()}
                    aria-label={t("toolbar.print")}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-hairline text-navy-600 hover:border-navy-200"
                  >
                    <Printer className="h-4 w-4" />
                  </button>
                  <Button variant="secondary" size="sm" onClick={() => void onExport()} loading={exporting} disabled={exporting || !detail.export_metadata.can_export}>
                    <Download className="h-4 w-4 mr-1" />
                    {t("actions.exportDocx")}
                  </Button>
                  <Button variant="primary" size="sm" onClick={onCopy}>
                    {copied ? <ClipboardCheck className="h-4 w-4 mr-1" /> : <Copy className="h-4 w-4 mr-1" />}
                    {copied ? t("toolbar.copied") : t("toolbar.copy")}
                  </Button>
                </div>

                {/* The note document — one continuous block, format-neutral. */}
                <div className="max-w-[720px]">
                  <div className="mb-4 flex items-center justify-between">
                    <h2 className="text-aurion-headline font-semibold text-navy-800">{t("noteLabel")}</h2>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-navy-500">
                        {t("completenessCaption", {
                          populated: detail.note.sections.filter((s) => s.status === "populated").length,
                          total: detail.note.sections.length,
                        })}
                      </span>
                      <CompletenessRing sections={detail.note.sections} />
                    </div>
                  </div>
                  <div className="space-y-6">
                    {detail.note.sections.map((section) => (
                      <NoteSectionCard
                        key={section.id}
                        section={section}
                        citations={detail.citations}
                        variant="document"
                        showCitations={false}
                        onSaveEdit={(text) => onSaveEdit(section.id, text)}
                        onResolveConflict={onResolveConflict}
                        macros={specialtyMacros}
                        busy={approving || regenerating || detail.export_metadata.session_state === "PROCESSING_STAGE2"}
                      />
                    ))}
                  </div>
                </div>
              </Card>

              {chatEnabled && <NoteAssistChat onAssist={onAssist} />}
            </div>

            <ActionRail
              detail={detail}
              approving={approving}
              copied={copied}
              onApprove={() => void onApprove()}
              onCopy={onCopy}
            />
          </div>

          {/* Approval-gated add-on surfaces — only render post-approval. */}
          <OrdersCard sessionId={sessionId} noteApproved={detail.export_metadata.is_approved} />
          <PatientSummaryCard sessionId={sessionId} noteApproved={detail.export_metadata.is_approved} />
          <CodingSuggestionsCard sessionId={sessionId} noteApproved={detail.export_metadata.is_approved} />
          <EmrWriteBackCard sessionId={sessionId} noteApproved={detail.export_metadata.is_approved} />
          <PreviewVsFinalCard
            sessionId={sessionId}
            finalSections={detail.note.sections}
            noteApproved={detail.export_metadata.is_approved}
          />
        </div>
      ) : null}
    </div>
  );
}

/** Plain-text note for the clipboard. Interim client-side assembly until
 * loop-3's GET /notes/{id}/text. Mirrors what's on screen. */
function buildNoteText(detail: NoteDetail): string {
  const lines: string[] = [];
  for (const section of detail.note.sections) {
    lines.push((section.title || section.id).toUpperCase());
    if (section.claims.length === 0) {
      lines.push("  [Not captured]");
    } else {
      for (const claim of section.claims) lines.push(claim.text);
    }
    lines.push("");
  }
  return lines.join("\n").trimEnd();
}

function ConflictsBanner({
  count,
  firstSectionId,
}: {
  count: number;
  firstSectionId: string | undefined;
}) {
  const t = useTranslations("NoteReview.conflicts");
  return (
    <div
      className="flex items-center gap-3 rounded-lg border border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-900 shadow-sm"
      role="status"
    >
      <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
      <div className="flex-1">
        <span className="font-semibold">{t("summary", { count })}</span> {t("blockedHint")}
      </div>
      {firstSectionId && (
        <a
          href={`#section-${firstSectionId}`}
          className="shrink-0 rounded-md border border-amber-400 bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900 hover:bg-amber-200 transition-colors"
        >
          {t("showFirst")}
        </a>
      )}
    </div>
  );
}

/** Loss-gate confirm (#590). The regenerate would drop work that can't be
 * rebuilt — show the PHI-free counts and let the physician decide. */
function DiscardPrompt({
  counts,
  onConfirm,
  onCancel,
}: {
  counts: RegenerateWouldDiscard;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations("NoteReview.discard");
  const total = Math.max(0, ...Object.values(counts));
  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-900 shadow-sm"
      role="alertdialog"
      aria-label={t("title")}
    >
      <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
      <div className="min-w-0 flex-1">
        <span className="font-semibold">{t("title")}</span> {t("body", { count: total })}
      </div>
      <button
        type="button"
        onClick={onCancel}
        className="shrink-0 rounded-md border border-amber-400 bg-white px-3 py-1 text-xs font-semibold text-amber-900 hover:bg-amber-100"
      >
        {t("cancel")}
      </button>
      <button
        type="button"
        onClick={onConfirm}
        className="shrink-0 rounded-md border border-amber-500 bg-amber-500 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-600"
      >
        {t("confirm")}
      </button>
    </div>
  );
}

function ActionRail({
  detail,
  approving,
  copied,
  onApprove,
  onCopy,
}: {
  detail: NoteDetail;
  approving: boolean;
  copied: boolean;
  onApprove: () => void;
  onCopy: () => void;
}) {
  const t = useTranslations("NoteReview.actions");
  const isApproved = detail.export_metadata.is_approved;
  const state = detail.export_metadata.session_state;
  const blocked =
    detail.conflict_state.has_unresolved ||
    state === "PROCESSING_STAGE1" ||
    state === "PROCESSING_STAGE2";

  return (
    <aside className="w-full lg:w-[300px] lg:flex-none lg:sticky lg:top-4">
      <Card>
        <div className="space-y-3">
          {isApproved ? (
            <div className="rounded-aurion-md bg-green-50 border border-green-200 px-3 py-2.5">
              <div className="text-aurion-caption font-semibold text-green-700">{t("signedTitle")}</div>
              <div className="text-aurion-caption text-green-800 mt-0.5">
                {state === "EXPORTED" ? t("approvedExported") : t("approvedReady")}
              </div>
            </div>
          ) : (
            <>
              <Button
                variant="primary"
                className="w-full"
                onClick={onApprove}
                loading={approving}
                disabled={approving || blocked}
              >
                {blocked ? t("resolveToApprove") : t("approveAndSign")}
              </Button>
              {blocked && detail.conflict_state.has_unresolved && (
                <p className="text-aurion-caption text-amber-700">{t("blockedHint")}</p>
              )}
            </>
          )}

          <Button variant={isApproved ? "primary" : "secondary"} className="w-full" onClick={onCopy}>
            {copied ? <ClipboardCheck className="h-4 w-4 mr-1" /> : <Copy className="h-4 w-4 mr-1" />}
            {copied ? t("copied") : t("copyToEhr")}
          </Button>

          <div className="h-px bg-hairline" />
          <p className="text-aurion-caption text-navy-400 text-center">{t("copyHint")}</p>
        </div>
      </Card>
    </aside>
  );
}
