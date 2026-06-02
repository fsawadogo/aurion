"use client";

import { CheckCircle2, SquarePen, XCircle } from "lucide-react";
import { useState } from "react";
import Button from "@/components/ui/Button";
import type { Claim } from "@/types";

/**
 * Three-action conflict resolution panel — mirrors iOS NoteReviewView
 * lines 557-613:
 *
 *   accept_visual  → keep the Stage 2 visual-derived claim
 *   reject_visual  → discard the visual claim, keep the audio version
 *   edit           → physician writes their own resolution text
 *
 * Surfaces an amber banner styling so the physician can't miss it.
 * Approval is blocked at the parent level when any conflict is
 * unresolved (matching iOS NoteReviewView lines 714-715).
 */

interface ConflictResolverProps {
  claim: Claim;
  onResolve: (
    action: "accept_visual" | "reject_visual" | "edit",
    resolutionText?: string,
  ) => Promise<void> | void;
  busy?: boolean;
}

export default function ConflictResolver({
  claim,
  onResolve,
  busy = false,
}: ConflictResolverProps) {
  const [editMode, setEditMode] = useState(false);
  const [draft, setDraft] = useState(claim.text);

  return (
    <div className="my-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-amber-800 mb-1.5">
        Conflict — needs review
      </p>
      <p className="text-sm text-gray-800 mb-2">
        <span className="italic">{claim.text}</span>
      </p>
      {claim.original_text && claim.original_text !== claim.text && (
        <p className="text-xs text-gray-600 mb-2">
          <span className="font-medium">Original:</span>{" "}
          <span className="italic">{claim.original_text}</span>
        </p>
      )}

      {!editMode ? (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void onResolve("accept_visual")}
            disabled={busy}
          >
            <CheckCircle2 className="h-4 w-4 mr-1" />
            Accept visual
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void onResolve("reject_visual")}
            disabled={busy}
          >
            <XCircle className="h-4 w-4 mr-1" />
            Reject visual
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setEditMode(true)}
            disabled={busy}
          >
            <SquarePen className="h-4 w-4 mr-1" />
            Edit
          </Button>
        </div>
      ) : (
        <div>
          <textarea
            className="form-input w-full min-h-[64px] resize-y mb-2"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={busy}
            placeholder="Write the resolution text…"
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                void Promise.resolve(onResolve("edit", draft)).then(() =>
                  setEditMode(false),
                );
              }}
              disabled={busy || draft.trim().length === 0}
              loading={busy}
            >
              Save resolution
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setEditMode(false);
                setDraft(claim.text);
              }}
              disabled={busy}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
