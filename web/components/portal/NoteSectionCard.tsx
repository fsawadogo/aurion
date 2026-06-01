"use client";

import { useEffect, useRef, useState } from "react";
import {
  PencilIcon,
  CheckIcon,
  XMarkIcon,
  BoltIcon,
} from "@heroicons/react/24/outline";

import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import ClaimChip from "@/components/portal/ClaimChip";
import ConflictResolver from "@/components/portal/ConflictResolver";
import { tryExpand } from "@/lib/portal-macros-expand";
import type {
  CitationExpansion,
  Claim,
  NoteSection,
  PhysicianMacro,
} from "@/types";

/**
 * One section of a note in the review pane.
 *
 * Default view is full-prose: section title + claims joined into a
 * single paragraph with citation chips inline. Edit mode swaps to a
 * `<textarea>` of the joined text and reports back via `onSave`
 * (parent calls `editNote(sessionId, {section_id: text})`).
 *
 * Any claim whose id starts with `conflict_` and isn't physician-
 * edited shows a `ConflictResolver` row above the section body —
 * matching iOS NoteReviewView convention. Parent blocks approval
 * while any are unresolved.
 */

interface NoteSectionCardProps {
  section: NoteSection;
  citations: Record<string, CitationExpansion>;
  /** Highlight a specific source id (transcript pane click). */
  highlightedSourceId?: string | null;
  /** Set when the parent clicked a chip — drives the transcript pane
   * scroll-and-highlight via a callback. */
  onClaimClick?: (claim: Claim) => void;
  /** Save edited section text. Resolves when persisted. */
  onSaveEdit: (text: string) => Promise<void>;
  /** Conflict resolution callback. */
  onResolveConflict: (
    claim: Claim,
    action: "accept_visual" | "reject_visual" | "edit",
    resolutionText?: string,
  ) => Promise<void>;
  /** Globally disable interaction (e.g. during Stage 2 processing). */
  busy?: boolean;
  /** Macros available for inline expansion. Filtered upstream by
   * specialty; this component just hands them to tryExpand. */
  macros?: PhysicianMacro[];
}

export default function NoteSectionCard({
  section,
  citations,
  highlightedSourceId,
  onClaimClick,
  onSaveEdit,
  onResolveConflict,
  busy = false,
  macros = [],
}: NoteSectionCardProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => joinClaims(section.claims));
  const [saving, setSaving] = useState(false);
  const [expandedHint, setExpandedHint] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Reset draft if the underlying section text changes outside of edit
  // mode (e.g. parent re-fetched after a conflict resolve elsewhere).
  useEffect(() => {
    if (!editing) setDraft(joinClaims(section.claims));
  }, [section.claims, editing]);

  const unresolvedConflicts = section.claims.filter(isUnresolvedConflict);
  const statusBadge = sectionBadge(section.status);

  return (
    <div
      id={`section-${section.id}`}
      className="rounded-lg border border-gray-200 bg-white p-4"
    >
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-navy-700">
          {section.title || section.id}
        </h3>
        {statusBadge}
        {section.status === "populated" && !editing && !busy && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="ml-auto inline-flex items-center gap-1 text-xs text-gray-500 hover:text-navy-700"
            aria-label="Edit section"
          >
            <PencilIcon className="h-3.5 w-3.5" />
            Edit
          </button>
        )}
      </div>

      {unresolvedConflicts.map((c) => (
        <ConflictResolver
          key={c.id}
          claim={c}
          onResolve={(action, text) => onResolveConflict(c, action, text)}
          busy={busy || saving}
        />
      ))}

      {editing ? (
        <div>
          <textarea
            ref={textareaRef}
            className="form-input w-full min-h-[120px] resize-y mb-2"
            value={draft}
            onChange={(e) => {
              const newText = e.target.value;
              const caret = e.target.selectionStart ?? newText.length;
              // Only try expansion when text grew — pure deletes /
              // pastes shouldn't fire.
              if (macros.length > 0 && newText.length > draft.length) {
                const result = tryExpand(newText, caret, macros);
                if (result) {
                  setDraft(result.text);
                  setExpandedHint(result.macro.shortcut);
                  window.setTimeout(() => setExpandedHint(null), 1500);
                  // Restore the caret on the next tick, after React
                  // has painted the new value.
                  window.setTimeout(() => {
                    if (textareaRef.current) {
                      textareaRef.current.selectionStart = result.caret;
                      textareaRef.current.selectionEnd = result.caret;
                    }
                  }, 0);
                  return;
                }
              }
              setDraft(newText);
            }}
            disabled={saving}
          />
          {expandedHint && (
            <p className="aurion-caption text-gold-700 mb-2 flex items-center gap-1.5 animate-aurion-fade-in">
              <BoltIcon className="h-3.5 w-3.5" />
              Expanded <span className="font-mono">{expandedHint}</span>
            </p>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="primary"
              loading={saving}
              disabled={saving || draft.trim().length === 0}
              onClick={async () => {
                setSaving(true);
                try {
                  await onSaveEdit(draft);
                  setEditing(false);
                } finally {
                  setSaving(false);
                }
              }}
            >
              <CheckIcon className="h-4 w-4 mr-1" />
              Save
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={saving}
              onClick={() => {
                setEditing(false);
                setDraft(joinClaims(section.claims));
              }}
            >
              <XMarkIcon className="h-4 w-4 mr-1" />
              Cancel
            </Button>
          </div>
        </div>
      ) : section.claims.length === 0 ? (
        <p className="text-sm text-gray-500 italic">Not captured.</p>
      ) : (
        <p className="text-sm leading-relaxed text-gray-800">
          {section.claims.map((claim, idx) => (
            <span key={claim.id} className="inline">
              {claim.text}
              <span className="ml-1 align-middle">
                <ClaimChip
                  claim={claim}
                  citation={citations[claim.id]}
                  onClick={() => onClaimClick?.(claim)}
                />
              </span>
              {idx < section.claims.length - 1 && " "}
              {/* Subtle highlight when the matching transcript source is selected */}
              {claim.source_id === highlightedSourceId && (
                <span className="sr-only">selected source</span>
              )}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

function joinClaims(claims: Claim[]): string {
  return claims.map((c) => c.text).join(" ");
}

function isUnresolvedConflict(c: Claim): boolean {
  return c.id.startsWith("conflict_") && !c.physician_edited;
}

function sectionBadge(status: NoteSection["status"]) {
  switch (status) {
    case "populated":
      return <Badge variant="success" dot>Populated</Badge>;
    case "pending_video":
      return <Badge variant="warning" dot>Pending visual</Badge>;
    case "processing_failed":
      return <Badge variant="error" dot>Failed</Badge>;
    case "not_captured":
    default:
      return <Badge variant="neutral">Not captured</Badge>;
  }
}
