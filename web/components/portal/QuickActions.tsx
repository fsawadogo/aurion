"use client";

import { Download, IdCard, Search, Sparkles, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import Card from "@/components/ui/Card";
import { listMySessionsByPatientIdentifier } from "@/lib/portal-api";
import type { PatientSessionMatch } from "@/types";

/**
 * Quick actions row above the dashboard KPI tiles.
 *
 * Task-oriented (DO X) rather than nav-oriented (GO TO X) so it
 * complements the sidebar without duplicating it:
 *
 *   1. Find by patient identifier — input + modal results. Uses
 *      the existing GET /me/patients/{id}/sessions endpoint shipped
 *      with #61's foundation. Closest the portal gets to the
 *      "longitudinal context" lookup the iOS app exposes today
 *      via the inbox chip.
 *
 *   2. Bulk export — link to /portal/notes where the multi-select
 *      + zip-download flow already lives. Quick access from the
 *      dashboard saves a sidebar click and a scroll.
 *
 *   3. New AI template — link to the conversational template
 *      builder. Surfacing it on the dashboard is the cheapest way
 *      to remind physicians the feature exists; otherwise it
 *      hides behind two clicks (sidebar → templates → New).
 */
export default function QuickActions() {
  const t = useTranslations("Dashboard.quickActions");
  const [showFindDialog, setShowFindDialog] = useState(false);

  return (
    <section className="mb-6">
      <h2 className="sr-only">{t("title")}</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <FindByIdentifierCard
          title={t("findByIdentifier.title")}
          subtitle={t("findByIdentifier.subtitle")}
          onOpen={() => setShowFindDialog(true)}
        />
        <ActionCard
          icon={<Download className="h-5 w-5" />}
          title={t("bulkExport.title")}
          subtitle={t("bulkExport.subtitle")}
          href="/portal/notes"
        />
        <ActionCard
          icon={<Sparkles className="h-5 w-5" />}
          title={t("newTemplate.title")}
          subtitle={t("newTemplate.subtitle")}
          href="/portal/templates/new"
        />
      </div>

      {showFindDialog && (
        <FindByIdentifierDialog onClose={() => setShowFindDialog(false)} />
      )}
    </section>
  );
}

/* ── Identifier search card ─────────────────────────────────────────────── */

/**
 * Same card shape as ActionCard but with a button affordance for
 * opening the modal — kept distinct so the search input can later
 * move inline if the modal pattern feels heavy.
 */
function FindByIdentifierCard({
  title,
  subtitle,
  onOpen,
}: {
  title: string;
  subtitle: string;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="text-left group rounded-aurion-md border border-aurion-hairline bg-aurion-card p-4 transition-all duration-aurion ease-aurion hover:shadow-card hover:-translate-y-px hover:border-gold-300"
    >
      <div className="flex items-start gap-3">
        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gold-50 text-gold-600 transition-colors group-hover:bg-gold-100">
          <IdCard className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-aurion-primary truncate">
            {title}
          </p>
          <p className="mt-0.5 text-xs text-aurion-secondary leading-relaxed line-clamp-2">
            {subtitle}
          </p>
        </div>
      </div>
    </button>
  );
}

function ActionCard({
  icon,
  title,
  subtitle,
  href,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-aurion-md border border-aurion-hairline bg-aurion-card p-4 transition-all duration-aurion ease-aurion hover:shadow-card hover:-translate-y-px hover:border-gold-300"
    >
      <div className="flex items-start gap-3">
        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gold-50 text-gold-600 transition-colors group-hover:bg-gold-100">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-aurion-primary truncate">
            {title}
          </p>
          <p className="mt-0.5 text-xs text-aurion-secondary leading-relaxed line-clamp-2">
            {subtitle}
          </p>
        </div>
      </div>
    </Link>
  );
}

/* ── Identifier search modal ────────────────────────────────────────────── */

/**
 * Tap "Find by patient identifier" → this modal opens. The user
 * types an identifier and submits; results render below the input
 * as a list of clickable session matches.
 *
 * Submit-on-enter; Escape closes; backdrop click closes.
 */
function FindByIdentifierDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("Dashboard.quickActions.findByIdentifier");
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PatientSessionMatch[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-focus the input when the dialog opens — physicians come here
  // ready to type, no need to make them click first.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Escape key closes the dialog. Document-level handler so it works
  // even when focus moves around inside the modal.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    setSearching(true);
    setError(null);
    try {
      const matches = await listMySessionsByPatientIdentifier(trimmed);
      setResults(matches);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
      setResults(null);
    } finally {
      setSearching(false);
    }
  }

  function openSession(sessionId: string) {
    router.push(`/portal/notes/${sessionId}`);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[10vh]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="find-by-id-title"
    >
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <Card className="relative z-10 w-full max-w-lg">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gold-50 text-gold-600">
            <IdCard className="h-5 w-5" />
          </span>
          <div className="flex-1 min-w-0">
            <h3 id="find-by-id-title" className="text-base font-semibold text-aurion-primary">
              {t("title")}
            </h3>
            <p className="mt-0.5 text-xs text-aurion-secondary">
              {t("subtitle")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-aurion-tertiary hover:text-aurion-primary transition-colors"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("placeholder")}
            className="form-input font-mono"
            // Identifiers are case-sensitive on the server-side
            // exact-match (KMS-encrypted column compares byte-for-byte
            // after decrypt); explicit autocap=off keeps mobile
            // keyboards from sneaking in title-case
            autoCapitalize="off"
            autoComplete="off"
            spellCheck={false}
            disabled={searching}
          />
          <button
            type="submit"
            disabled={searching || !query.trim()}
            className="rounded-aurion-md bg-gold-500 px-4 py-2 text-sm font-semibold text-navy-800 transition-colors hover:bg-gold-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="inline-flex items-center gap-1.5">
              {searching ? (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-navy-800 border-r-transparent" />
              ) : (
                <Search className="h-3.5 w-3.5" />
              )}
              {searching ? t("searching") : t("submit")}
            </span>
          </button>
        </form>

        {error && (
          <p className="mt-3 text-xs text-red-600">{error}</p>
        )}

        {results !== null && (
          <div className="mt-4">
            {results.length === 0 ? (
              <p className="text-sm text-aurion-secondary italic">
                {t("noResults")}
              </p>
            ) : (
              <>
                <p className="text-xs font-medium uppercase tracking-wide text-aurion-tertiary mb-2">
                  {t("resultsTitle", { id: query.trim() })}
                </p>
                <ul className="divide-y divide-aurion-hairline rounded-aurion-md border border-aurion-hairline overflow-hidden">
                  {results.map((match) => (
                    <li key={match.session_id}>
                      <button
                        type="button"
                        onClick={() => openSession(match.session_id)}
                        className="w-full px-3 py-2.5 text-left hover:bg-aurion-muted transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[10px] text-aurion-tertiary shrink-0">
                            {match.session_id.slice(0, 8)}
                          </span>
                          <span className="text-sm text-aurion-primary truncate">
                            {match.specialty.replace(/_/g, " ")}
                          </span>
                          <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-aurion-secondary">
                            {match.state}
                          </span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
