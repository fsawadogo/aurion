import type { SessionState } from "@/types";

/**
 * Shared session formatting helpers used across every portal surface
 * that lists or summarizes sessions (dashboard, inbox, command palette,
 * notification bell, note review, templates, and the patient detail
 * page).
 *
 * Lifted out of `app/portal/dashboard/page.tsx` and 5 other call sites
 * during #61's patient-detail slice — each call site previously held
 * its own copy. That's the rule-of-three trigger several times over;
 * extracting once keeps display behaviour consistent the next time
 * we tweak "12 min ago" copy or add a new state badge variant.
 *
 * All three helpers are pure. No `useTranslations` here — the strings
 * they return ("just now", "12 min ago", short month name from
 * `toLocaleDateString`) are intentionally locale-derived from the
 * browser's locale settings, not the next-intl message catalogs.
 * If we ever localize them through next-intl, change the signatures
 * to take a `t` function explicitly rather than reading context.
 */

/** Snake_case specialty key → Title Case display name.
 *
 *   "orthopedic_surgery" → "Orthopedic Surgery"
 *   "general"            → "General"
 *
 * Pure string transform — no locale awareness. */
export function humanSpecialty(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Relative-time string for an ISO-8601 timestamp.
 *
 * Buckets: <1min "just now" · <1hr "12 min ago" · <24hr "3 hr ago" ·
 * <7d "2d ago" · older "Mar 14" (or "Mar 14, 2025" with `withYear`).
 *
 * Returns the original string unchanged for invalid input so callers
 * never have to guard against `Invalid Date`. */
export function formatRelative(
  iso: string,
  opts?: { withYear?: boolean },
): string {
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
    ...(opts?.withYear ? { year: "numeric" } : {}),
  });
}

/** Maps a SessionState to the Badge variant that telegraphs "what
 * kind of attention does this need?". Single source of truth so the
 * dashboard, inbox, and patient detail page agree on the colour for
 * each state. */
export type SessionBadgeVariant =
  | "success"
  | "warning"
  | "info"
  | "neutral"
  | "error";

export function badgeVariantFor(state: SessionState): SessionBadgeVariant {
  switch (state) {
    case "AWAITING_REVIEW":
      return "warning";
    case "PROCESSING_STAGE1":
    case "PROCESSING_STAGE2":
      return "info";
    case "REVIEW_COMPLETE":
    case "EXPORTED":
      return "success";
    case "RECORDING":
    case "PAUSED":
      return "info";
    case "FAILED":
      return "error";
    default:
      return "neutral";
  }
}

/** First 8 hex chars of a UUID — a glanceable short id for dense tables.
 * Pair with `title={fullId}` on the element so the full id stays available
 * on hover/copy. "b90baea3-56fb-4a4f-..." → "b90baea3". */
export function shortSessionId(id: string): string {
  return id.slice(0, 8);
}

// Leading honorifics stripped before abbreviating a name. Lowercased,
// with/without a trailing dot. "Dre" = French "Docteure".
const HONORIFICS = new Set([
  "dr",
  "dre",
  "mr",
  "mrs",
  "ms",
  "mx",
  "prof",
  "professor",
]);

function nameTokens(fullName: string): string[] {
  return fullName
    .trim()
    .split(/\s+/)
    .filter((t) => t && !HONORIFICS.has(t.replace(/\.$/, "").toLowerCase()));
}

/** Abbreviate a clinician's full name to "F. Lastname" for dense lists —
 * first given-name initial + last token, honorific stripped. Falls back to
 * the single token (or trimmed input) when there's no surname.
 *
 *   "Faical Sawadogo"      → "F. Sawadogo"
 *   "Dr. Perry Gdalevitch" → "P. Gdalevitch"
 *   "Aurion Admin"         → "A. Admin"
 *   "Madonna"              → "Madonna"
 *
 * Pair with `title={fullName}` so the full name shows on hover. */
export function abbreviateName(fullName: string): string {
  const tokens = nameTokens(fullName);
  if (tokens.length === 0) return fullName.trim();
  if (tokens.length === 1) return tokens[0];
  const first = tokens[0].charAt(0).toUpperCase();
  return `${first}. ${tokens[tokens.length - 1]}`;
}

/** 1–2 letter monogram for a name avatar (first + last token initials,
 * honorific stripped). "Faical Sawadogo" → "FS"; "Admin" → "A". */
export function nameInitials(fullName: string): string {
  const tokens = nameTokens(fullName);
  if (tokens.length === 0) return "—";
  if (tokens.length === 1) return tokens[0].charAt(0).toUpperCase();
  return (
    tokens[0].charAt(0) + tokens[tokens.length - 1].charAt(0)
  ).toUpperCase();
}
