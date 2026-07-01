"use client";

import { CalendarDays, Pencil, Plus, Trash2, X } from "lucide-react";
import { humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import {
  addMyScheduleEntry,
  listMySchedule,
  removeMyScheduleEntry,
  updateMyScheduleEntry,
} from "@/lib/portal-api";
import type { ScheduleEntry, ScheduleEntryStatus } from "@/types";

/**
 * /portal/schedule — the clinician's personal patient schedule (#603).
 *
 * Queue patients you plan to see, with an optional slot time and short
 * note, and move each through a simple lifecycle (scheduled → in progress
 * → completed / cancelled). Owner-scoped server-side — a clinician only
 * ever sees their own entries. This is NOT a calendar/booking system:
 * `scheduled_for` is a single optional timestamp with no conflict
 * detection or recurrence.
 *
 * The patient identifier is PHI: it is encrypted + hashed server-side and
 * only decrypted back to the owning clinician. Enter the same clinic
 * identifier (MRN / encounter id) used elsewhere — not a patient name.
 */

const ALL_STATUSES: ScheduleEntryStatus[] = [
  "scheduled",
  "in_progress",
  "completed",
  "cancelled",
];

/* Legal forward transitions, mirroring the backend service. Terminal
 * states (completed / cancelled) have no outgoing edge. Used only to
 * shape the inline status control — the server remains the source of
 * truth and rejects anything illegal with a 409. */
const TRANSITIONS: Record<ScheduleEntryStatus, ScheduleEntryStatus[]> = {
  scheduled: ["in_progress", "completed", "cancelled"],
  in_progress: ["scheduled", "completed", "cancelled"],
  completed: [],
  cancelled: [],
};

const STATUS_VARIANT: Record<
  ScheduleEntryStatus,
  "info" | "warning" | "success" | "neutral"
> = {
  scheduled: "info",
  in_progress: "warning",
  completed: "success",
  cancelled: "neutral",
};

interface EntryDraft {
  patient_identifier: string;
  scheduled_for: string; // datetime-local value ("" = none)
  note: string;
}

const EMPTY_DRAFT: EntryDraft = {
  patient_identifier: "",
  scheduled_for: "",
  note: "",
};

export default function PortalSchedulePage() {
  const t = useTranslations("Schedule");
  const [list, setList] = useState<ScheduleEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ScheduleEntry | "new" | null>(null);
  const [filter, setFilter] = useState<"all" | ScheduleEntryStatus>("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const xs = await listMySchedule();
      setList(sortEntries(xs));
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onDelete(entry: ScheduleEntry) {
    if (!confirm(t("deleteConfirm", { patient: entry.patient_identifier }))) {
      return;
    }
    try {
      await removeMyScheduleEntry(entry.id);
      setList((prev) => prev.filter((x) => x.id !== entry.id));
    } catch (e) {
      setError(humanizeError(e, t("deleteError")));
    }
  }

  async function onStatusChange(
    entry: ScheduleEntry,
    status: ScheduleEntryStatus,
  ) {
    setError(null);
    try {
      const saved = await updateMyScheduleEntry(entry.id, { status });
      setList((prev) =>
        sortEntries(prev.map((x) => (x.id === saved.id ? saved : x))),
      );
    } catch (e) {
      setError(humanizeError(e, t("statusUpdateError")));
    }
  }

  const visible =
    filter === "all" ? list : list.filter((e) => e.status === filter);

  return (
    <div className="aurion-page-padded aurion-container-narrow">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={
          <Button variant="primary" size="sm" onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4 mr-1" />
            {t("newEntry")}
          </Button>
        }
      />

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
        >
          {error}
        </div>
      )}

      <Card>
        {loading ? (
          <LoadingSkeleton lines={6} />
        ) : list.length === 0 ? (
          <div className="py-10 text-center">
            <div className="mx-auto mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-gold-50 text-gold-600">
              <CalendarDays className="h-6 w-6" />
            </div>
            <p className="aurion-callout text-navy-500 mb-4 mx-auto max-w-sm">
              {t("emptyTitle")}
            </p>
            <Button variant="primary" size="sm" onClick={() => setEditing("new")}>
              {t("addFirst")}
            </Button>
          </div>
        ) : (
          <>
            <div
              className="mb-4 flex flex-wrap gap-1.5"
              role="group"
              aria-label={t("filterAria")}
            >
              {(["all", ...ALL_STATUSES] as const).map((s) => {
                const active = filter === s;
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setFilter(s)}
                    aria-pressed={active}
                    data-testid={`schedule-filter-${s}`}
                    className={
                      "rounded-aurion-md border px-3 py-1.5 text-sm font-medium transition-colors duration-short " +
                      (active
                        ? "border-navy-700 bg-navy-700 text-white"
                        : "border-navy-200 text-navy-600 hover:bg-navy-50")
                    }
                  >
                    {s === "all" ? t("filterAll") : t(`status.${s}`)}
                  </button>
                );
              })}
            </div>

            <ul className="divide-y divide-hairline">
              {visible.map((entry) => (
                <li
                  key={entry.id}
                  className="py-3 flex items-start gap-4 hover:bg-canvas/40 -mx-2 px-2 rounded-md transition-colors duration-short"
                >
                  <span className="font-mono text-[13px] font-semibold text-navy-700 bg-gold-50 px-2 py-0.5 rounded-aurion-xs ring-1 ring-inset ring-gold-600/20 shrink-0">
                    {entry.patient_identifier}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant={STATUS_VARIANT[entry.status]}>
                        {t(`status.${entry.status}`)}
                      </Badge>
                      {entry.scheduled_for && (
                        <span className="aurion-caption text-navy-500">
                          {formatSlot(entry.scheduled_for)}
                        </span>
                      )}
                    </div>
                    {entry.note && (
                      <p className="text-aurion-callout text-navy-800 line-clamp-2 mt-1.5">
                        {entry.note}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {TRANSITIONS[entry.status].length > 0 && (
                      <select
                        className="form-select h-8 py-0 text-sm max-w-[9rem]"
                        value=""
                        onChange={(e) => {
                          const next = e.target.value as ScheduleEntryStatus;
                          if (next) void onStatusChange(entry, next);
                        }}
                        aria-label={t("statusChangeAria")}
                        data-testid={`schedule-advance-${entry.id}`}
                      >
                        <option value="">{t("statusChangePrompt")}</option>
                        {TRANSITIONS[entry.status].map((next) => (
                          <option key={next} value={next}>
                            {t(`status.${next}`)}
                          </option>
                        ))}
                      </select>
                    )}
                    <button
                      type="button"
                      onClick={() => setEditing(entry)}
                      className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-canvas hover:text-navy-700"
                      aria-label={t("editAria")}
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => void onDelete(entry)}
                      className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-red-50 hover:text-red-600"
                      aria-label={t("deleteAria")}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      {editing && (
        <ScheduleEditor
          entry={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setEditing(null);
            setList((prev) => {
              const idx = prev.findIndex((x) => x.id === saved.id);
              const next =
                idx >= 0
                  ? prev.map((x) => (x.id === saved.id ? saved : x))
                  : [...prev, saved];
              return sortEntries(next);
            });
          }}
        />
      )}
    </div>
  );
}

/* ── Editor modal ─────────────────────────────────────────────────────── */

function ScheduleEditor({
  entry,
  onClose,
  onSaved,
}: {
  entry: ScheduleEntry | null;
  onClose: () => void;
  onSaved: (e: ScheduleEntry) => void;
}) {
  const tEditor = useTranslations("Schedule.editor");
  const [draft, setDraft] = useState<EntryDraft>(
    entry ? draftFromEntry(entry) : EMPTY_DRAFT,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isEdit = entry !== null;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const slotIso = draft.scheduled_for
        ? new Date(draft.scheduled_for).toISOString()
        : null;
      const note = draft.note.trim() || null;
      let saved: ScheduleEntry;
      if (isEdit && entry) {
        // Identifier is immutable after creation — only slot + note change.
        saved = await updateMyScheduleEntry(entry.id, {
          scheduled_for: slotIso,
          clear_scheduled_for: slotIso === null,
          note,
          clear_note: note === null,
        });
      } else {
        saved = await addMyScheduleEntry({
          patient_identifier: draft.patient_identifier.trim(),
          scheduled_for: slotIso,
          note,
        });
      }
      onSaved(saved);
    } catch (e) {
      const msg = humanizeError(e, tEditor("saveError"));
      // Surface the backend's reason (e.g. the 422 identifier gate)
      // without the "API 4xx:" prefix or JSON envelope.
      setError(
        msg
          .replace(/^API \d+:\s*/, "")
          .replace(/^.*"detail":"?/, "")
          .replace(/"?\}.*$/, ""),
      );
    } finally {
      setSaving(false);
    }
  }

  const canSave =
    !saving && (isEdit || draft.patient_identifier.trim().length > 0);

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
            {isEdit ? tEditor("editTitle") : tEditor("newTitle")}
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
            <label className="block aurion-micro mb-1.5">
              {tEditor("identifierLabel")}
            </label>
            <input
              className="form-input font-mono"
              value={draft.patient_identifier}
              onChange={(e) =>
                setDraft({ ...draft, patient_identifier: e.target.value })
              }
              disabled={saving || isEdit}
              autoFocus={!isEdit}
              placeholder={tEditor("identifierPlaceholder")}
              aria-label={tEditor("identifierAria")}
            />
            <p className="aurion-caption mt-1">
              {isEdit ? tEditor("identifierLocked") : tEditor("identifierHint")}
            </p>
          </div>
          <div>
            <label className="block aurion-micro mb-1.5">
              {tEditor("slotLabel")}
            </label>
            <input
              type="datetime-local"
              className="form-input"
              value={draft.scheduled_for}
              onChange={(e) =>
                setDraft({ ...draft, scheduled_for: e.target.value })
              }
              disabled={saving}
              aria-label={tEditor("slotAria")}
            />
            <p className="aurion-caption mt-1">{tEditor("slotHint")}</p>
          </div>
          <div>
            <label className="block aurion-micro mb-1.5">
              {tEditor("noteLabel")}
            </label>
            <textarea
              className="form-input min-h-[90px] leading-relaxed resize-y"
              value={draft.note}
              onChange={(e) => setDraft({ ...draft, note: e.target.value })}
              disabled={saving}
              maxLength={500}
              placeholder={tEditor("notePlaceholder")}
              aria-label={tEditor("noteAria")}
            />
            <p className="aurion-caption mt-1">{tEditor("noteHint")}</p>
          </div>
          {error && <p className="aurion-caption text-red-600">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-hairline px-5 py-3 bg-canvas/40">
          <Button size="sm" variant="secondary" disabled={saving} onClick={onClose}>
            {tEditor("cancel")}
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={saving}
            disabled={!canSave}
            onClick={() => void save()}
          >
            {tEditor("save")}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── helpers ──────────────────────────────────────────────────────────── */

/** Sort: undated entries by most-recently-created; dated entries by slot.
 * Simple + stable — no calendar semantics, just a sensible reading order
 * (soonest / newest first). */
function sortEntries(xs: ScheduleEntry[]): ScheduleEntry[] {
  return [...xs].sort((a, b) => {
    if (a.scheduled_for && b.scheduled_for) {
      return a.scheduled_for.localeCompare(b.scheduled_for);
    }
    if (a.scheduled_for) return -1;
    if (b.scheduled_for) return 1;
    return b.created_at.localeCompare(a.created_at);
  });
}

function formatSlot(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** ISO → the `datetime-local` input value (local time, no seconds/tz). */
function toLocalInputValue(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function draftFromEntry(entry: ScheduleEntry): EntryDraft {
  return {
    patient_identifier: entry.patient_identifier,
    scheduled_for: entry.scheduled_for ? toLocalInputValue(entry.scheduled_for) : "",
    note: entry.note ?? "",
  };
}
