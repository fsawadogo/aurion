"use client";

import { Pencil, Plus, Trash2, X, Zap } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
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

/* Specialty option keys — labels resolve via the shared `Specialties`
 * catalog so the dropdown stays in lockstep with the rest of the
 * portal (templates list, profile picker, etc.). Empty key = no
 * specialty scope. */
const SPECIALTY_KEYS = [
  "",
  "orthopedic_surgery",
  "plastic_surgery",
  "musculoskeletal",
  "emergency_medicine",
  "general",
] as const;

interface MacroDraft {
  shortcut: string;
  body: string;
  specialty: string; // "" = no scope
}

const EMPTY_DRAFT: MacroDraft = { shortcut: "/", body: "", specialty: "" };

export default function PortalMacrosPage() {
  const t = useTranslations("Macros");
  const tSpecialties = useTranslations("Specialties");
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
      setError(e instanceof Error ? e.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onDelete(m: PhysicianMacro) {
    if (!confirm(t("deleteConfirm", { shortcut: m.shortcut }))) return;
    try {
      await deleteMyMacro(m.id);
      setList(list.filter((x) => x.id !== m.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("deleteError"));
    }
  }

  return (
    <div className="aurion-page-padded aurion-container-narrow">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => setEditing("new")}
          >
            <Plus className="h-4 w-4 mr-1" />
            {t("newMacro")}
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
            <Zap className="mx-auto h-10 w-10 text-gold-300 mb-2" />
            <p className="aurion-callout text-navy-500 mb-3">
              {t("emptyTitle")}
            </p>
            <Button
              variant="primary"
              size="sm"
              onClick={() => setEditing("new")}
            >
              {t("addFirst")}
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
                      {tSpecialties(m.specialty as Parameters<typeof tSpecialties>[0])}
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={() => setEditing(m)}
                    className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-canvas hover:text-navy-700"
                    aria-label={t("editAria")}
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void onDelete(m)}
                    className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-red-50 hover:text-red-600"
                    aria-label={t("deleteAria")}
                  >
                    <Trash2 className="h-4 w-4" />
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
  const t = useTranslations("Macros");
  const tEditor = useTranslations("Macros.editor");
  const tSpecialties = useTranslations("Specialties");
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
      const msg = e instanceof Error ? e.message : tEditor("saveError");
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
            {editingId ? tEditor("editTitle") : tEditor("newTitle")}
          </h3>
          <button
            type="button"
            onClick={() => !saving && onClose()}
            disabled={saving}
            className="rounded-aurion-xs p-1 text-navy-400 hover:bg-canvas hover:text-navy-700"
            aria-label={tEditor("closeAria")}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block aurion-micro mb-1.5">{tEditor("shortcutLabel")}</label>
            <input
              className="form-input font-mono"
              value={draft.shortcut}
              onChange={(e) => setDraft({ ...draft, shortcut: e.target.value })}
              disabled={saving}
              autoFocus
              placeholder={tEditor("shortcutPlaceholder")}
              aria-label={tEditor("shortcutAria")}
            />
            <p className="aurion-caption mt-1">{tEditor("shortcutHint")}</p>
          </div>
          <div>
            <label className="block aurion-micro mb-1.5">{tEditor("bodyLabel")}</label>
            <textarea
              className="form-input min-h-[140px] leading-relaxed resize-y"
              value={draft.body}
              onChange={(e) => setDraft({ ...draft, body: e.target.value })}
              disabled={saving}
              placeholder={tEditor("bodyPlaceholder")}
              aria-label={tEditor("bodyAria")}
            />
            <p className="aurion-caption mt-1">{tEditor("bodyHint")}</p>
          </div>
          <div>
            <label className="block aurion-micro mb-1.5">
              {tEditor("specialtyLabel")}
            </label>
            <select
              className="form-select"
              value={draft.specialty}
              onChange={(e) =>
                setDraft({ ...draft, specialty: e.target.value })
              }
              disabled={saving}
              aria-label={tEditor("specialtyAria")}
            >
              {SPECIALTY_KEYS.map((key) => (
                <option key={key || "all"} value={key}>
                  {key === "" ? tSpecialties("all") : tSpecialties(key)}
                </option>
              ))}
            </select>
            <p className="aurion-caption mt-1">{tEditor("specialtyHint")}</p>
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
            {tEditor("cancel")}
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={saving}
            disabled={saving || !draft.shortcut.trim() || !draft.body.trim()}
            onClick={() => void save()}
          >
            {tEditor("save")}
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
