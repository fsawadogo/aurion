"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeftIcon,
  ArrowDownTrayIcon,
  ExclamationTriangleIcon,
  CheckBadgeIcon,
} from "@heroicons/react/24/outline";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import CompletenessRing from "@/components/portal/CompletenessRing";
import NoteSectionCard from "@/components/portal/NoteSectionCard";
import StageTwoProgressBanner from "@/components/portal/StageTwoProgressBanner";
import TranscriptPane, {
  TranscriptPaneHandle,
} from "@/components/portal/TranscriptPane";
import {
  approveAll,
  editNote,
  exportNote,
  getNoteDetail,
  resolveConflict,
} from "@/lib/portal-api";
import type { Claim, NoteDetail } from "@/types";

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
  const params = useParams<{ id: string }>();
  const sessionId = params.id;

  const [detail, setDetail] = useState<NoteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [highlightedSourceId, setHighlightedSourceId] = useState<string | null>(
    null,
  );
  const transcriptRef = useRef<TranscriptPaneHandle>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await getNoteDetail(sessionId);
      setDetail(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load note.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

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
      setError(e instanceof Error ? e.message : "Approval failed.");
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
      setError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto">
      <div className="mb-4 flex items-center justify-between">
        <Link
          href="/portal/notes"
          className="inline-flex items-center gap-1.5 text-sm text-navy-700 hover:text-navy-900"
        >
          <ArrowLeftIcon className="h-4 w-4" />
          Back to notes
        </Link>
        {detail && (
          <div className="hidden sm:flex items-center gap-3 text-xs text-gray-500">
            <span>
              Stage <span className="font-semibold">{detail.note.stage}</span>
            </span>
            <span>·</span>
            <span>
              v<span className="font-semibold">{detail.note.version}</span>
            </span>
            <span>·</span>
            <span>
              Provider:{" "}
              <span className="font-semibold">{detail.note.provider_used}</span>
            </span>
            <span>·</span>
            <Badge variant="neutral">
              {humanSpecialty(detail.note.specialty)}
            </Badge>
          </div>
        )}
      </div>

      {loading && !detail ? (
        <Card>
          <LoadingSkeleton lines={12} />
        </Card>
      ) : error && !detail ? (
        <Card>
          <p className="text-sm text-red-600">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void load()}>
            Retry
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

          {/* Two-column layout: transcript ↔ note */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-[600px]">
            <div className="lg:sticky lg:top-4 h-[70vh] lg:h-[calc(100vh-200px)]">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                  Transcript
                </h2>
                <span className="text-[11px] text-gray-400">
                  {Object.keys(detail.citations).length} cited segments
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
                  Note
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
  return (
    <div
      className="flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
      role="status"
    >
      <ExclamationTriangleIcon className="h-5 w-5 shrink-0 text-amber-600" />
      <div className="flex-1">
        <span className="font-medium">
          {count} unresolved conflict{count === 1 ? "" : "s"}.
        </span>{" "}
        Approval is blocked until every conflict is resolved.
      </div>
      {firstSectionId && (
        <a
          href={`#section-${firstSectionId}`}
          className="rounded-md border border-amber-400 px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100 transition-colors"
        >
          Show first
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
          <CheckBadgeIcon className="h-5 w-5" />
          Approved ·{" "}
          {state === "EXPORTED" ? "exported" : "ready to export"}
        </span>
      ) : (
        <Button
          variant="primary"
          onClick={onApprove}
          loading={approving}
          disabled={approving || blocked}
        >
          {blocked ? "Resolve conflicts to approve" : "Approve & sign"}
        </Button>
      )}

      <Button
        variant="secondary"
        onClick={onExport}
        loading={exporting}
        disabled={exporting || !canExport}
      >
        <ArrowDownTrayIcon className="h-4 w-4 mr-1" />
        Export DOCX
      </Button>

      <span className="ml-auto text-xs text-gray-500">
        State: <span className="font-medium">{state}</span>
      </span>
    </div>
  );
}

function humanSpecialty(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
