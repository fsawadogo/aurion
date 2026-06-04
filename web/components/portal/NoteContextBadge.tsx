"use client";

import { Clock4 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

/**
 * Header chip on the note review screen that surfaces "this Stage 1
 * note actually consumed prior encounters into the LLM prompt" — the
 * web mirror of the iOS `contextAwareBadgeOrNil` view (#61, full slice).
 *
 * Visibility:
 *   - Visible iff ``encountersReferenced > 0`` AND a patient identifier
 *     is set on the session (clickable destination requires both).
 *   - Hidden when ``priorContextUsed`` is null (cold-start sessions),
 *     when the count is zero (lookup ran, found nothing), or when no
 *     identifier is set (defensive — backend prior_context_used is
 *     only populated when an identifier exists, but a brief render
 *     race between the note + session payloads could land us here).
 *
 * Navigation:
 *   - Clicking routes to ``/portal/patients/{identifier}`` where the
 *     existing PatientDetailClient already shows the full timeline of
 *     prior encounters for this clinician + identifier. Keeps a
 *     single destination for "show me the prior visits" intent.
 *
 * Privacy:
 *   - The component receives only the slim count + last-visit date.
 *   - The identifier IS PHI but is required to construct the route;
 *     it never lands in a log line, an error message, or the badge's
 *     visible text — only the link's href.
 */
interface NoteContextBadgeProps {
  encountersReferenced: number;
  /** Patient identifier used to construct the navigation target.
   * When null/empty the badge hides itself. */
  identifier: string | null | undefined;
}

export default function NoteContextBadge({
  encountersReferenced,
  identifier,
}: NoteContextBadgeProps) {
  const t = useTranslations("LongitudinalContext");

  if (encountersReferenced <= 0) return null;
  if (!identifier || !identifier.trim()) return null;

  return (
    <Link
      href={`/portal/patients/${encodeURIComponent(identifier)}`}
      // Gold-tinted chip — matches the patient identifier chip pattern
      // already used elsewhere on this header so the affordances feel
      // related. Same neutral border + amber-leaning fill the iOS
      // badge uses.
      className="inline-flex items-center gap-2 rounded-full border border-gold-200 bg-gold-50 px-3 py-1.5 text-sm font-medium text-gold-700 transition hover:bg-gold-100 hover:text-gold-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-500"
      aria-label={t("badge.contextAware")}
      title={t("badge.tapToView")}
      data-testid="note-context-badge"
    >
      <Clock4 className="h-4 w-4" aria-hidden="true" />
      <span className="font-semibold">{t("badge.contextAware")}</span>
      <span className="text-gold-600">·</span>
      <span>
        {t("badge.priorVisitsCount", { count: encountersReferenced })}
      </span>
    </Link>
  );
}
