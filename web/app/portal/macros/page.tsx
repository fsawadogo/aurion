"use client";

import { useCallback, useEffect, useState } from "react";
import {
  PlusIcon,
  PencilIcon,
  TrashIcon,
  BoltIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import {
  createMyMacro,
  deleteMyMacro,
  listMyMacros,
  updateMyMacro,
} from "@/lib/portal-api";
import type { PhysicianMacro } from "@/types";

/**
 * /portal/macros — physician phrase shortcut library.
 *
 * Each row is a "type /foo, get the body text" pairing. Optional
 * specialty scope restricts a macro to one specialty's notes (handy
 * for physicians who practise across multiple). Plain text bodies —
 * formatting (bold, lists) is out of scope; the macro expands into
 * a textarea, so the value is the saved keystrokes, not styling.
 */

const SPECIALTIES = [
  { key: "", label: "All specialties" },
  { key: "orthopedic_surgery", label: "Orthopedic Surgery" },
  { key: "plastic_surgery", label: "Plastic Surgery" },
  { key: "musculoskeletal", label: "Musculoskeletal" },
  { key: "emergency_medicine", label: "Emergency Medicine" },
  { key: "general", label: "General" },
];

interface MacroDraft {
  shortcut: string;
  body: string;
  specialty: string; // "" = no scope
}

const EMPTY_DRAFT: MacroDraft = { shortcut: "/", body: "", specialty: "" };

export default function PortalMacrosPage() {
  const [list, setList] = useState<PhysicianMacro[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<PhysicianMacro | "new" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const xs = await listMyMacros();
      xs.sort((a, b) => a.shortcut.localeCompare(b.shortcut));
      setList(xs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load macros.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onDelete(m: PhysicianMacro) {
    if (
      !confirm(
        `Delete macro "${m.shortcut}"? This can't be undone (the audit log keeps a record).`,
      )
    )
      return;
    try {
      await deleteMyMacro(m.id);
      setList(list.filter((x) => x.id !== m.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    }
  }

  return (
    <div className="aurion-page-padded aurion-container-narrow">
      <PageHeader
        eyebrow="Clinician portal"
        title="Macros"
        description="Type a shortcut like /ros-cv during a note edit and it expands to the full phrase. Saves the boilerplate-typing tax."
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => setEditing("new")}
          >
            <PlusIcon className="h-4 w-4 mr-1" />
            New macro
          </Button>
        }
      />

      {error && (
        <div className="mb-4 rounded-aurion-md bg-red-50 border border-red-200 px-4 py-3 text-aurion-callout text-red-700">
          {error}
        </div>
      )}

      <Card>
        {loading ? (
          <LoadingSkeleton lines={6} />
        ) : list.length === 0 ? (
          <div className="py-8 text-center">
            <BoltIcon className="mx-auto h-10 w-10 text-gold-300 mb-2" />
            <p className="aurion-callout text-navy-500 mb-3">
              No macros yet. Add a few of your most-typed phrases to save
              real time during note review.
            </p>
            <Button
              variant="primary"
              size="sm"
              onClick={() => setEditing("new")}
            >
              Add your first macro
            </Button>
          </div>
        ) : (
          <ul className="divide-y divide-hairline">
            {list.map((m) => (
              <li
                key={m.id}
                className="py-3 flex items-start gap-4 hover:bg-canvas/40 -mx-2 px-2 rounded-md transition-colors duration-short"
              >
                <span className="font-mono text-[13px] font-semibold text-navy-700 bg-gold-50 px-2 py-0.5 rounded-aurion-xs ring-1 ring-inset ring-gold-600/20 shrink-0">
                  {m.shortcut}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-aurion-callout text-navy-800 line-clamp-2">
                    {m.body}
                  </p>
                  {m.specialty && (
                    <Badge variant="info" className="mt-1.5">
                      {prettySpecialty(m.specialty)}
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={() => setEditing(m)}
                    className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-canvas hover:text-navy-700"
                    aria-label="Edit"
                  >
                    <PencilIcon className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void onDelete(m)}
                    className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-red-50 hover:text-red-600"
                    aria-label="Delete"
                  >
                    <TrashIcon className="h-4 w-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {editing && (
        <MacroEditor
          initial={editing === "new" ? EMPTY_DRAFT : draftFromMacro(editing)}
          editingId={editing === "new" ? null : editing.id}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setEditing(null);
            setList((prev) => {
              const idx = prev.findIndex((x) => x.id === saved.id);
              const next = idx >= 0 ? [...prev] : [...prev, saved];
              if (idx >= 0) next[idx] = saved;
              next.sort((a, b) => a.shortcut.localeCompare(b.shortcut));
              return next;
            });
          }}
        />
      )}
    </div>
  );
}

/* ── Editor modal ─────────────────────────────────────────────────────── */

function MacroEditor({
  initial,
  editingId,
  onClose,
  onSaved,
}: {
  initial: MacroDraft;
  editingId: string | null;
  onClose: () => void;
  onSaved: (m: PhysicianMacro) => void;
}) {
  const [draft, setDraft] = useState<MacroDraft>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const payload = {
        shortcut: draft.shortcut.trim(),
        body: draft.body.trim(),
        specialty: draft.specialty || null,
      };
      const saved = editingId
        ? await updateMyMacro(editingId, {
            ...payload,
            clear_specialty: !draft.specialty,
          })
        : await createMyMacro(payload);
      onSaved(saved);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      // Surface the backend's 409 message verbatim — it's already
      // friendly ("Macro with shortcut '/ros' already exists").
      setError(msg.replace(/^API \d+:\s*/, "").replace(/^.*"detail":"?/, "").replace(/"?\}.*$/, ""));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/30 backdrop-blur-sm animate-aurion-fade-in p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !saving) onClose();
      }}
    >
      <div className="w-full max-w-lg rounded-aurion-xl bg-surface shadow-card-hover ring-1 ring-hairline animate-aurion-scale-in">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3.5">
          <h3 className="aurion-headline">
            {editingId ? "Edit macro" : "New macro"}
          </h3>
          <button
            type="button"
            onClick={() => !saving && onClose()}
            disabled={saving}
            className="rounded-aurion-xs p-1 text-navy-400 hover:bg-canvas hover:text-navy-700"
            aria-label="Close"
          >
            <XMarkIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block aurion-micro mb-1.5">Shortcut</label>
            <input
              className="form-input font-mono"
              value={draft.shortcut}
              onChange={(e) => setDraft({ ...draft, shortcut: e.target.value })}
              disabled={saving}
              autoFocus
              placeholder="/ros-cv"
              aria-label="Shortcut"
            />
            <p className="aurion-caption mt-1">
              Starts with <code>/</code>; letters, digits, dashes, and
              underscores only (max 32 chars after the slash).
            </p>
          </div>
          <div>
            <label className="block aurion-micro mb-1.5">Expansion</label>
            <textarea
              className="form-input min-h-[140px] leading-relaxed resize-y"
              value={draft.body}
              onChange={(e) => setDraft({ ...draft, body: e.target.value })}
              disabled={saving}
              placeholder="The full phrase this shortcut expands to…"
              aria-label="Macro body"
            />
            <p className="aurion-caption mt-1">
              Plain text. Max 4096 characters.
            </p>
          </div>
          <div>
            <label className="block aurion-micro mb-1.5">
              Specialty scope (optional)
            </label>
            <select
              className="form-select"
              value={draft.specialty}
              onChange={(e) =>
                setDraft({ ...draft, specialty: e.target.value })
              }
              disabled={saving}
              aria-label="Specialty scope"
            >
              {SPECIALTIES.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
            <p className="aurion-caption mt-1">
              Leave on &quot;All specialties&quot; to expand the macro in
              every kind of note. Pick one to restrict it.
            </p>
          </div>
          {error && (
            <p className="aurion-caption text-red-600">{error}</p>
          )}
        </div>

        <div className="flex items-center gap-2 border-t border-hairline px-5 py-3 bg-canvas/40">
          <div className="flex-1" />
          <Button
            size="sm"
            variant="secondary"
            disabled={saving}
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={saving}
            disabled={saving || !draft.shortcut.trim() || !draft.body.trim()}
            onClick={() => void save()}
          >
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}

function draftFromMacro(m: PhysicianMacro): MacroDraft {
  return {
    shortcut: m.shortcut,
    body: m.body,
    specialty: m.specialty ?? "",
  };
}

function prettySpecialty(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
