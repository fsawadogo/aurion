"use client";

import { AlertTriangle, BadgeCheck, Download } from "lucide-react";
import { humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouteSegment } from "@/lib/use-route-segment";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import CodingSuggestionsCard from "@/components/portal/CodingSuggestionsCard";
import CompletenessRing from "@/components/portal/CompletenessRing";
import EmrWriteBackCard from "@/components/portal/EmrWriteBackCard";
import EncounterAudioCard from "@/components/portal/EncounterAudioCard";
import LivePreviewCard from "@/components/portal/LivePreviewCard";
import NoteContextBadge from "@/components/portal/NoteContextBadge";
import NoteSectionCard from "@/components/portal/NoteSectionCard";
import OrdersCard from "@/components/portal/OrdersCard";
import PageHeader from "@/components/portal/PageHeader";
import PatientIdentifierEditor from "@/components/portal/PatientIdentifierEditor";
import PatientSummaryCard from "@/components/portal/PatientSummaryCard";
import PreviewVsFinalCard from "@/components/portal/PreviewVsFinalCard";
import StageTwoProgressBanner from "@/components/portal/StageTwoProgressBanner";
import TranscriptPane, {
  TranscriptPaneHandle,
} from "@/components/portal/TranscriptPane";
import {
  approveAll,
  editNote,
  exportNote,
  getNoteDetail,
  getSession,
  listMyMacros,
  resolveConflict,
} from "@/lib/portal-api";
import { filterForSpecialty } from "@/lib/portal-macros-expand";
import { humanSpecialty } from "@/lib/session-format";
import type { Claim, NoteDetail, PhysicianMacro, Session as SessionRow } from "@/types";

/**
 * /portal/notes/[id] — the note review screen.
 *
 * Two-column layout: transcript pane (left) with the cited sources,
 * note sections (right) with citation chips. Clicking a chip scrolls
 * the transcript pane to its source and highlights it. Per-section
 * edit mode + three-action conflict resolver. Single-tap approve
 * fires approve-stage1 then approve sequentially (mirroring iOS
 * NoteReviewView).
 *
 * Stage 2 progress is wired to the existing /ws/notes/{id} WebSocket
 * channel — banner stays visible while running, refetches the note on
 * `stage2_delivered`. Approval is blocked while conflicts remain
 * unresolved (iOS NoteReviewView lines 714-715).
 */
export default function NoteReviewPage() {
  const t = useTranslations("NoteReview");
  const tActions = useTranslations("NoteReview.actions");
  // Static-export gotcha — see web/lib/use-route-segment.ts. `useParams()`
  // returns the build-time "_" sentinel under `output: "export"`; the
  // hook reads from `usePathname()` so the real URL wins at runtime.
  const sessionId = useRouteSegment("id");

  const [detail, setDetail] = useState<NoteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [highlightedSourceId, setHighlightedSourceId] = useState<string | null>(
    null,
  );
  const [noNoteYet, setNoNoteYet] = useState(false);
  // Session row is fetched alongside the note detail so the live
  // preview card (#64) can gate on session state — the card is only
  // useful while the encounter is mid-flight, and we need to know
  // that even when the note doesn't exist yet.
  const [session, setSession] = useState<SessionRow | null>(null);
  const [macros, setMacros] = useState<PhysicianMacro[]>([]);
  const transcriptRef = useRef<TranscriptPaneHandle>(null);

  // Pull the user's macros once. Re-fetching on every render would
  // burn API calls — physicians rarely tweak their macro library
  // mid-review.
  useEffect(() => {
    let cancelled = false;
    void listMyMacros()
      .then((xs) => {
        if (!cancelled) setMacros(xs);
      })
      .catch(() => {
        // Quiet failure — the review still works without macros.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNoNoteYet(false);
    try {
      // Fetch both in parallel — session row gives us state (for the
      // live preview card gating) even when the note detail 404s on
      // an in-flight recording session.
      const [d, s] = await Promise.allSettled([
        getNoteDetail(sessionId),
        getSession(sessionId),
      ]);
      if (d.status === "fulfilled") {
        setDetail(d.value);
      } else {
        const msg = d.reason instanceof Error ? d.reason.message : t("loadError");
        // /detail 404s when the session exists but has no note yet —
        // typical for CONSENT_PENDING / RECORDING / freshly-discarded
        // sessions. Surface a friendly empty state instead of a raw
        // error.
        if (/\b404\b/.test(msg)) {
          setNoNoteYet(true);
        } else {
          setError(msg);
        }
      }
      if (s.status === "fulfilled") {
        setSession(s.value);
      }
    } finally {
      setLoading(false);
    }
  }, [sessionId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function focusSource(claim: Claim) {
    setHighlightedSourceId(claim.source_id);
    transcriptRef.current?.scrollToSource(claim.source_id);
  }

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
      // Browser download trick.
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
          detail
            ? <>
                {t("stageMetaPrefix")} <span className="font-semibold text-navy-700">{detail.note.stage}</span>
                {" · "}{t("stageVersion")}<span className="font-semibold text-navy-700">{detail.note.version}</span>
                {" · "}{t("stageProvider")} <span className="font-semibold text-navy-700">{detail.note.provider_used}</span>
              </>
            : undefined
        }
        actions={
          detail ? (
            <div className="flex items-center gap-2">
              {/* #61 full slice — "Context-aware" badge surfaces when
                  Stage 1 actually consumed prior encounters into the
                  LLM prompt. Hidden when prior_context_used is null
                  (cold-start session, pre-#61 backend) or its count
                  is zero. Clicking routes to the patient timeline. */}
              <NoteContextBadge
                encountersReferenced={
                  detail.note.prior_context_used?.encounters_referenced ?? 0
                }
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
          {/* Live preview (#64) — visible only while the session is
              RECORDING / PAUSED / PROCESSING_STAGE1. The card gates
              internally on the session state we just fetched. */}
          {session && (
            <LivePreviewCard
              sessionId={sessionId}
              sessionState={session.state}
            />
          )}
          <Card>
            <div className="text-center py-10">
              <p className="aurion-headline text-navy-700 mb-1.5">
                {t("noNoteTitle")}
              </p>
              <p className="aurion-callout text-navy-500 max-w-md mx-auto">
                {t("noNoteHint")}
              </p>
              <Button
                variant="secondary"
                size="sm"
                className="mt-5"
                onClick={() => void load()}
              >
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

          {/* Encounter audio replay (#338) — physician replays the raw
              audio of their OWN session in-browser. Fetches the presigned
              URL only on the explicit "Play recording" click (each call
              writes an EVIDENCE_REPLAYED audit row), and never offers a
              download. The button always renders; the endpoint's 403
              gracefully covers the media_review_retention_enabled flag-off
              case since the portal can't read that backend flag directly. */}
          <EncounterAudioCard sessionId={sessionId} />

          {/* Two-column layout: transcript ↔ note */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-[600px]">
            <div className="lg:sticky lg:top-4 h-[70vh] lg:h-[calc(100vh-200px)]">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                  {t("transcriptLabel")}
                </h2>
                <span className="text-[11px] text-gray-400">
                  {t("transcriptCount", {
                    count: Object.keys(detail.citations).length,
                  })}
                </span>
              </div>
              <TranscriptPane
                ref={transcriptRef}
                citations={detail.citations}
                highlightedSourceId={highlightedSourceId}
              />
            </div>
            <div>
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                  {t("noteLabel")}
                </h2>
                <CompletenessRing sections={detail.note.sections} />
              </div>
              <div className="space-y-3">
                {detail.note.sections.map((section) => (
                  <NoteSectionCard
                    key={section.id}
                    section={section}
                    citations={detail.citations}
                    highlightedSourceId={highlightedSourceId}
                    onClaimClick={focusSource}
                    onSaveEdit={(text) => onSaveEdit(section.id, text)}
                    onResolveConflict={onResolveConflict}
                    macros={filterForSpecialty(macros, detail.note.specialty)}
                    busy={
                      approving ||
                      detail.export_metadata.session_state ===
                        "PROCESSING_STAGE2"
                    }
                  />
                ))}
              </div>
            </div>
          </div>

          {/* Orders card — extracted structured imaging/lab/referral/
              prescription orders awaiting physician confirmation.
              Same approval gate as the summary card (orders go to the
              EMR; can't come from a draft note). */}
          <OrdersCard
            sessionId={sessionId}
            noteApproved={detail.export_metadata.is_approved}
          />

          {/* Patient summary card — only visible after the note is
              approved, since patient-facing output must come from a
              physician-signed source. */}
          <PatientSummaryCard
            sessionId={sessionId}
            noteApproved={detail.export_metadata.is_approved}
          />

          {/* Coding & billing suggestions — #69 strategic SEPARATE
              inference surface. Approval-gated; never written back into
              the clinical note's sections. The card itself carries the
              "Assistive — physician must confirm" framing inline. */}
          <CodingSuggestionsCard
            sessionId={sessionId}
            noteApproved={detail.export_metadata.is_approved}
          />

          {/* EMR write-back — #57 foundation. Approval-gated.
              Foundation deployment only ships the `stub` connector;
              real Oscar / Epic / generic-FHIR backends land in
              follow-ups. The card surfaces the "Pilot mode" banner
              when only stub is available, so the physician doesn't
              think the note actually went to a chart system. */}
          <EmrWriteBackCard
            sessionId={sessionId}
            noteApproved={detail.export_metadata.is_approved}
          />

          {/* Preview-vs-final diff (#64 follow-up). Approval-gated.
              Collapsed-by-default evaluation surface: shows how the
              last live preview compared to the canonical Stage 1
              note. Read-only — eval team uses this to tune preview
              cadence and compare providers. Doesn't render if no
              previews exist for this session. */}
          <PreviewVsFinalCard
            sessionId={sessionId}
            finalSections={detail.note.sections}
            noteApproved={detail.export_metadata.is_approved}
          />

          <ActionBar
            detail={detail}
            approving={approving}
            exporting={exporting}
            onApprove={() => void onApprove()}
            onExport={() => void onExport()}
          />
        </div>
      ) : null}
    </div>
  );
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
        <span className="font-semibold">{t("summary", { count })}</span>{" "}
        {t("blockedHint")}
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

function ActionBar({
  detail,
  approving,
  exporting,
  onApprove,
  onExport,
}: {
  detail: NoteDetail;
  approving: boolean;
  exporting: boolean;
  onApprove: () => void;
  onExport: () => void;
}) {
  const t = useTranslations("NoteReview.actions");
  const isApproved = detail.export_metadata.is_approved;
  const canExport = detail.export_metadata.can_export;
  const state = detail.export_metadata.session_state;
  const blocked =
    detail.conflict_state.has_unresolved ||
    state === "PROCESSING_STAGE1" ||
    state === "PROCESSING_STAGE2";

  return (
    <div className="sticky bottom-4 z-10 flex items-center gap-3 rounded-lg border border-gray-200 bg-white/95 backdrop-blur px-4 py-3 shadow-sm">
      {isApproved ? (
        <span className="inline-flex items-center gap-1.5 text-sm text-emerald-700">
          <BadgeCheck className="h-5 w-5" />
          {state === "EXPORTED" ? t("approvedExported") : t("approvedReady")}
        </span>
      ) : (
        <Button
          variant="primary"
          onClick={onApprove}
          loading={approving}
          disabled={approving || blocked}
        >
          {blocked ? t("resolveToApprove") : t("approveAndSign")}
        </Button>
      )}

      <Button
        variant="secondary"
        onClick={onExport}
        loading={exporting}
        disabled={exporting || !canExport}
      >
        <Download className="h-4 w-4 mr-1" />
        {t("exportDocx")}
      </Button>

      <span className="ml-auto text-xs text-gray-500">
        {t("stateLabel", { state })}
      </span>
    </div>
  );
}
