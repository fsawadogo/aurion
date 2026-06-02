"use client";

import {
  AlertTriangle,
  BadgeCheck,
  Bell,
  CheckCheck,
  Download,
  Eye,
  FileCheck,
  FileText,
  Send,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { getMyAuditLog } from "@/lib/portal-api";
import type { AuditEvent, PaginatedResponse } from "@/types";

/**
 * Global notification bell for the clinician portal.
 *
 * Pinned to the top-right of the viewport (fixed position so it's
 * available from every portal page, not just the dashboard). Polls
 * /api/v1/me/audit on the same 30s cadence as the dashboard's
 * ActivityFeed; surfaces the last 6 noteworthy events in a dropdown
 * panel.
 *
 * Unread tracking:
 *   * `lastSeen` timestamp lives in localStorage under
 *     `aurion-notifications-last-seen`.
 *   * Any event with `event_timestamp > lastSeen` is "unread" and
 *     contributes to the red count badge.
 *   * Opening the dropdown automatically marks all as read. We don't
 *     wait for an explicit click — once the user has seen the
 *     dropdown, the badge has served its purpose. A separate "mark
 *     all read" button in the footer covers the edge case where
 *     localStorage was empty and the user hits 99+ on first load.
 *
 * Why a separate component (not just ActivityFeed embedded in a
 * popover): the bell needs to track unread state, render a count
 * badge, and animate the icon on new activity. ActivityFeed renders
 * a static panel on the dashboard. Two components, one data source,
 * different presentation responsibilities.
 *
 * Why not WebSocket: see ActivityFeed.tsx for the rationale —
 * polling matches the audit feed's HTTP-only nature and the 30s
 * cadence is fine for physician workflows.
 */

const POLL_INTERVAL_MS = 30_000;
const DROPDOWN_LIMIT = 6;
const LAST_SEEN_KEY = "aurion-notifications-last-seen";

/** Allowlist mirrors ActivityFeed's. Kept in sync by code review;
 *  if it churns, extract to a shared constants module. */
const NOTEWORTHY_EVENTS: ReadonlySet<string> = new Set([
  "stage1_delivered",
  "stage1_failed",
  "stage2_complete",
  "stage2_failed",
  "stage1_approved",
  "note_exported",
  "bulk_note_export",
  "conflict_resolved",
  "emr_write_back_sent",
  "emr_write_back_failed",
  "session_purged",
  "session_discarded",
]);

export default function NotificationBell() {
  const t = useTranslations("Notifications");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  /* ── Read lastSeen on mount ───────────────────────────────────────── */

  useEffect(() => {
    try {
      const stored = localStorage.getItem(LAST_SEEN_KEY);
      setLastSeen(stored);
    } catch {
      // localStorage can throw in Safari private mode — fail silent,
      // every event becomes "unread" which is the safer default.
    }
  }, []);

  /* ── Polling ──────────────────────────────────────────────────────── */

  const load = useCallback(async () => {
    setFailed(false);
    try {
      const resp = (await getMyAuditLog({ page_size: 25 })) as PaginatedResponse<AuditEvent>;
      const noteworthy = (resp.items ?? []).filter((e) =>
        NOTEWORTHY_EVENTS.has(e.event_type),
      );
      setEvents(noteworthy.slice(0, DROPDOWN_LIMIT));
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  /* ── Unread count ─────────────────────────────────────────────────── */

  const unreadCount = useMemo(() => {
    if (lastSeen === null) {
      // Never seen anything yet — cap the badge at the dropdown
      // limit so a fresh session doesn't slam the user with "27 new".
      // After they open the dropdown once, the cap effectively
      // resets to "delta since last open".
      return Math.min(events.length, 9);
    }
    return events.filter((e) => e.event_timestamp > lastSeen).length;
  }, [events, lastSeen]);

  /* ── Mark as read on open ─────────────────────────────────────────── */

  const markAllRead = useCallback(() => {
    if (events.length === 0) return;
    const newest = events[0].event_timestamp;
    setLastSeen(newest);
    try {
      localStorage.setItem(LAST_SEEN_KEY, newest);
    } catch {
      // Private mode again — state still updates in memory for
      // this session, which is good enough until refresh.
    }
  }, [events]);

  // Open dropdown → mark all read on the same tick. Separating these
  // would make the badge flash off-and-back during the render.
  const openDropdown = useCallback(() => {
    setOpen(true);
    markAllRead();
  }, [markAllRead]);

  /* ── Close on outside click + Escape ──────────────────────────────── */

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (
        dropdownRef.current?.contains(target) ||
        buttonRef.current?.contains(target)
      ) {
        return;
      }
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  /* ── Render ───────────────────────────────────────────────────────── */

  return (
    <div className="fixed top-4 right-4 z-40 sm:top-5 sm:right-5">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => (open ? setOpen(false) : openDropdown())}
        aria-label={t("ariaLabel", { count: unreadCount })}
        aria-expanded={open}
        aria-haspopup="menu"
        className={
          "relative inline-flex h-10 w-10 items-center justify-center rounded-full border border-aurion-hairline bg-aurion-card shadow-card transition-all duration-aurion ease-aurion hover:shadow-card-hover hover:-translate-y-px " +
          (unreadCount > 0 ? "ring-1 ring-gold-300/40" : "")
        }
      >
        <Bell
          className={
            "h-4 w-4 transition-transform duration-aurion ease-aurion " +
            (unreadCount > 0 ? "text-gold-600" : "text-aurion-secondary")
          }
        />
        {unreadCount > 0 && (
          <span
            className="absolute -top-1 -right-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white"
            aria-hidden
          >
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={dropdownRef}
          role="menu"
          aria-label={t("dropdownLabel")}
          className="absolute right-0 top-12 w-80 rounded-aurion-lg border border-aurion-hairline bg-aurion-card shadow-card-hover overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center gap-2 border-b border-aurion-hairline px-3 py-2.5">
            <Bell className="h-4 w-4 text-aurion-secondary" />
            <h3 className="text-sm font-semibold text-aurion-primary">
              {t("title")}
            </h3>
            <button
              type="button"
              onClick={markAllRead}
              disabled={unreadCount === 0}
              className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-gold-600 hover:text-gold-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
            >
              <CheckCheck className="h-3 w-3" />
              {t("markAllRead")}
            </button>
          </div>

          {/* Body */}
          <div className="max-h-[60vh] overflow-y-auto">
            {failed ? (
              <FailedState />
            ) : events.length === 0 ? (
              <EmptyState />
            ) : (
              <ul className="divide-y divide-aurion-hairline">
                {events.map((event) => (
                  <NotificationRow
                    key={uniqueKey(event)}
                    event={event}
                    lastSeen={lastSeen}
                    onSelect={() => setOpen(false)}
                  />
                ))}
              </ul>
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-aurion-hairline px-3 py-2 text-center">
            <Link
              href="/portal/dashboard"
              onClick={() => setOpen(false)}
              className="text-xs font-medium text-gold-600 hover:text-gold-700 transition-colors"
            >
              {t("seeAll")} →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Row ────────────────────────────────────────────────────────────────── */

function NotificationRow({
  event,
  lastSeen,
  onSelect,
}: {
  event: AuditEvent;
  lastSeen: string | null;
  onSelect: () => void;
}) {
  const tEvent = useTranslations("Dashboard.activity.event");
  const meta = visualFor(event.event_type);
  const isUnread = lastSeen === null || event.event_timestamp > lastSeen;

  const href =
    event.event_type === "bulk_note_export"
      ? "/portal/notes"
      : `/portal/notes/${event.session_id}`;

  return (
    <li>
      <Link
        href={href}
        onClick={onSelect}
        className="group flex items-start gap-2.5 px-3 py-2.5 transition-colors hover:bg-aurion-muted"
      >
        <span
          className={
            "mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full " +
            meta.iconBg
          }
        >
          {meta.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p
            className={
              "text-xs leading-snug " +
              (isUnread
                ? "font-semibold text-aurion-primary"
                : "text-aurion-secondary")
            }
          >
            {tEvent(meta.labelKey)}
          </p>
          <p className="mt-0.5 text-[10px] text-aurion-tertiary">
            <span className="font-mono">{event.session_id.slice(0, 8)}</span>
            <span aria-hidden> · </span>
            {formatRelative(event.event_timestamp)}
          </p>
        </div>
        {isUnread && (
          <span
            className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-gold-500"
            aria-hidden
          />
        )}
      </Link>
    </li>
  );
}

/* ── Empty + failed states ──────────────────────────────────────────────── */

function EmptyState() {
  const t = useTranslations("Notifications");
  return (
    <div className="flex flex-col items-center justify-center py-6 text-center">
      <Bell className="h-6 w-6 text-aurion-tertiary" />
      <p className="mt-2 text-xs font-medium text-aurion-primary">
        {t("empty")}
      </p>
      <p className="mt-1 max-w-[24ch] text-[10px] text-aurion-secondary leading-relaxed">
        {t("emptyHint")}
      </p>
    </div>
  );
}

function FailedState() {
  const t = useTranslations("Notifications");
  return (
    <div className="flex items-center gap-2 px-3 py-4">
      <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
      <p className="flex-1 text-xs text-aurion-primary">
        {t("loadFailed")}
      </p>
    </div>
  );
}

/* ── Visual mapping ─────────────────────────────────────────────────────── */

interface RowVisual {
  icon: React.ReactNode;
  iconBg: string;
  labelKey: string;
}

function visualFor(eventType: string): RowVisual {
  switch (eventType) {
    case "stage1_delivered":
      return { icon: <FileText className="h-3 w-3 text-amber-700" />, iconBg: "bg-amber-50", labelKey: "stage1Delivered" };
    case "stage1_failed":
      return { icon: <XCircle className="h-3 w-3 text-red-600" />, iconBg: "bg-red-50", labelKey: "stage1Failed" };
    case "stage2_complete":
      return { icon: <Sparkles className="h-3 w-3 text-navy-600" />, iconBg: "bg-navy-50", labelKey: "stage2Complete" };
    case "stage2_failed":
      return { icon: <XCircle className="h-3 w-3 text-red-600" />, iconBg: "bg-red-50", labelKey: "stage2Failed" };
    case "stage1_approved":
      return { icon: <BadgeCheck className="h-3 w-3 text-emerald-600" />, iconBg: "bg-emerald-50", labelKey: "stage1Approved" };
    case "note_exported":
      return { icon: <Download className="h-3 w-3 text-emerald-700" />, iconBg: "bg-emerald-50", labelKey: "noteExported" };
    case "bulk_note_export":
      return { icon: <Download className="h-3 w-3 text-emerald-700" />, iconBg: "bg-emerald-50", labelKey: "bulkNoteExport" };
    case "conflict_resolved":
      return { icon: <FileCheck className="h-3 w-3 text-navy-600" />, iconBg: "bg-navy-50", labelKey: "conflictResolved" };
    case "emr_write_back_sent":
      return { icon: <Send className="h-3 w-3 text-emerald-700" />, iconBg: "bg-emerald-50", labelKey: "emrSent" };
    case "emr_write_back_failed":
      return { icon: <AlertTriangle className="h-3 w-3 text-red-600" />, iconBg: "bg-red-50", labelKey: "emrFailed" };
    case "session_purged":
    case "session_discarded":
      return { icon: <Trash2 className="h-3 w-3 text-aurion-tertiary" />, iconBg: "bg-aurion-muted", labelKey: eventType === "session_purged" ? "sessionPurged" : "sessionDiscarded" };
    default:
      return { icon: <Eye className="h-3 w-3 text-aurion-secondary" />, iconBg: "bg-aurion-muted", labelKey: "generic" };
  }
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function uniqueKey(e: AuditEvent): string {
  if (e.event_id) return e.event_id;
  return `${e.session_id}:${e.event_timestamp}`;
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const m = Math.round((Date.now() - d.getTime()) / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hr ago`;
  const days = Math.round(h / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}
