"use client";

import { useEffect, useRef, useState } from "react";
import {
  IdentificationIcon,
  PencilIcon,
  TrashIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";

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
 * Stays PHI-aware:
 *   - The displayed text comes from the parent's decrypted Session
 *     payload — never logged.
 *   - The previous-encounters count is calculated locally from the
 *     /me/patients/{id}/sessions response (already PHI-aware
 *     server-side).
 *   - Empty / whitespace input clears the identifier (backend handles
 *     this contract).
 */
interface PatientIdentifierEditorProps {
  sessionId: string;
  /** Current identifier (decrypted by the backend) or null. */
  currentIdentifier: string | null | undefined;
  /** Called after a successful save with the new identifier (or null
   * after clear). Parent should refresh its session data. */
  onChange: (next: string | null) => void;
}

export default function PatientIdentifierEditor({
  sessionId,
  currentIdentifier,
  onChange,
}: PatientIdentifierEditorProps) {
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
      const t = window.setTimeout(() => inputRef.current?.focus(), 50);
      return () => window.clearTimeout(t);
    }
  }, [open]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const cleaned = draft.trim();
      const result = await setSessionExternalReferenceId(
        sessionId,
        cleaned || null,
      );
      onChange(result.external_reference_id ?? null);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {currentIdentifier ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-full bg-gold-50 px-3 py-1 text-[12.5px] font-medium text-navy-700 ring-1 ring-inset ring-gold-600/20 hover:bg-gold-100 hover:ring-gold-600/30 transition-colors duration-short"
          aria-label="Edit patient identifier"
        >
          <IdentificationIcon className="h-3.5 w-3.5 text-gold-600" />
          <span className="font-mono">{currentIdentifier}</span>
          {encounters.length > 0 && (
            <span className="ml-1 inline-flex items-center rounded-full bg-gold-200 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-navy-800">
              +{encounters.length}
            </span>
          )}
          <PencilIcon className="h-3 w-3 text-navy-300" />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-aurion-md px-2.5 py-1.5 text-[12.5px] text-navy-500 hover:bg-canvas hover:text-navy-700 transition-colors duration-short"
        >
          <IdentificationIcon className="h-4 w-4" />
          Add patient identifier
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
                Patient identifier
              </h3>
              <button
                type="button"
                onClick={() => !saving && setOpen(false)}
                className="rounded-aurion-xs p-1 text-navy-400 hover:bg-canvas hover:text-navy-700"
                aria-label="Close"
                disabled={saving}
              >
                <XMarkIcon className="h-4 w-4" />
              </button>
            </div>
            <div className="px-5 py-4 space-y-3">
              <p className="aurion-caption text-navy-500">
                Stored encrypted at rest, decrypted only for you. Use
                whatever scheme your clinic uses — MRN, encounter id,
                free text — so you can link this session back to the
                patient&apos;s prior visits.
              </p>
              <input
                ref={inputRef}
                className="form-input font-mono"
                placeholder="e.g. MRN_1042 or 2026-06-01-AB"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void save();
                  if (e.key === "Escape" && !saving) setOpen(false);
                }}
                disabled={saving}
                aria-label="Patient identifier"
              />
              {error && (
                <p className="aurion-caption text-red-600">{error}</p>
              )}
              {encounters.length > 0 && (
                <div className="rounded-aurion-md bg-canvas px-3 py-2.5">
                  <p className="aurion-micro mb-1.5">
                    Previous encounters ({encounters.length})
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
                        … and {encounters.length - 5} more
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
                    void save();
                  }}
                >
                  <TrashIcon className="h-4 w-4 mr-1" />
                  Clear
                </Button>
              )}
              <div className="flex-1" />
              <Button
                size="sm"
                variant="secondary"
                disabled={saving}
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                loading={saving}
                disabled={saving || draft === (currentIdentifier ?? "")}
                onClick={() => void save()}
              >
                Save
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
