"use client";

/**
 * `/portal/admin/patients/[identifier]` — the cross-clinician Patient Chart
 * (#604). Every encounter tagged with one patient identifier, ACROSS all
 * pilot clinicians, on a single page — with clinician attribution and a
 * supervisory "Validate" action per note.
 *
 * Elevated-role surface: the backend gates it to CLINICAL_ADMIN/ADMIN AND
 * behind the `cross_clinician_chart_enabled` flag (404 while dark). When the
 * endpoint 404s we render the "not enabled" state instead of an error, so the
 * page reads as "feature off", not "broken". See the server shell for the PHI
 * rationale (role ∧ flag, not owner-scoping).
 */

import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  IdCard,
  ShieldCheck,
  Stethoscope,
  UserRound,
} from "lucide-react";
import { ApiError, humanizeError, parseDetailError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { useRouteSegment } from "@/lib/use-route-segment";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import EmptyPanelState from "@/components/portal/EmptyPanelState";
import PageHeader from "@/components/portal/PageHeader";
import {
  listAdminPatientEncounters,
  validatePatientNote,
} from "@/lib/portal-api";
import {
  badgeVariantFor,
  formatRelative,
  humanSpecialty,
  shortSessionId,
} from "@/lib/session-format";
import type { AdminPatientEncounter } from "@/types";

// A note can be validated (supervisory sign-off) only while the session is in
// one of these states — mirrors the backend allowed_states on the validate
// route. Any other state hides the button (the backend would 409).
const VALIDATABLE_STATES = new Set(["PROCESSING_STAGE2", "REVIEW_COMPLETE"]);

export default function PatientChartClient() {
  const t = useTranslations("AdminPatientChart");
  // Static-export param decode — see web/lib/use-route-segment.ts.
  const identifier = useRouteSegment("identifier");

  const [encounters, setEncounters] = useState<AdminPatientEncounter[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Flag-off / not-authorized → the backend 404s the whole surface.
  const [disabled, setDisabled] = useState(false);

  const load = useCallback(async () => {
    if (!identifier) return;
    setLoading(true);
    setError(null);
    setDisabled(false);
    try {
      const rows = await listAdminPatientEncounters(identifier);
      rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
      setEncounters(rows);
    } catch (e) {
      // 404 = feature dark (or role not permitted) — render the "not enabled"
      // state, no identifier echoed. Everything else is a generic load error.
      if (e instanceof ApiError && e.status === 404) {
        setDisabled(true);
      } else {
        setError(humanizeError(e, t("loadFailed")));
      }
    } finally {
      setLoading(false);
    }
  }, [identifier, t]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="aurion-page-padded aurion-container">
      <PageHeader
        breadcrumb={[
          { label: t("backToSearch"), href: "/portal/admin/patients" },
          { label: identifier || t("title") },
        ]}
        eyebrow={t("eyebrow")}
        title={identifier || t("title")}
        description={
          loading || disabled
            ? undefined
            : encounters.length === 0
              ? t("subtitle.none")
              : t("subtitle.summary", { count: encounters.length })
        }
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            {t("refresh")}
          </Button>
        }
      />

      {error && !loading && (
        <div
          className="mb-4 flex items-center gap-3 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span className="flex-1">{t("loadFailed")}</span>
          <button
            type="button"
            onClick={() => void load()}
            className="text-xs font-semibold underline"
            data-testid="patient-chart-retry"
          >
            {t("retry")}
          </button>
        </div>
      )}

      {disabled ? (
        <Card>
          <div data-testid="patient-chart-disabled">
            <EmptyPanelState
              icon={<ShieldCheck className="h-5 w-5" aria-hidden="true" />}
              title={t("notEnabledTitle")}
              hint={t("notEnabledBody")}
            />
          </div>
        </Card>
      ) : (
        <Card>
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-navy-700">
            <ClipboardList className="h-4 w-4 text-gold-500" />
            {t("encounters.title")}
          </div>
          {loading ? (
            <LoadingSkeleton lines={5} />
          ) : encounters.length === 0 ? (
            <EmptyPanelState
              icon={<IdCard className="h-7 w-7" />}
              title={t("encounters.empty")}
              hint={t("encounters.emptyHint")}
            />
          ) : (
            <ul
              className="divide-y divide-gray-100"
              data-testid="patient-chart-encounter-list"
            >
              {encounters.map((e) => (
                <EncounterRow
                  key={e.session_id}
                  encounter={e}
                  onValidated={() => void load()}
                />
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}

/* ── Subcomponents ──────────────────────────────────────────────────────── */

function EncounterRow({
  encounter,
  onValidated,
}: {
  encounter: AdminPatientEncounter;
  onValidated: () => void;
}) {
  const t = useTranslations("AdminPatientChart");
  const [validating, setValidating] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);

  const variant = badgeVariantFor(encounter.state as never);
  const canValidate =
    !encounter.is_approved &&
    encounter.note_version > 0 &&
    VALIDATABLE_STATES.has(encounter.state);

  const onValidate = useCallback(async () => {
    setValidating(true);
    setRowError(null);
    try {
      await validatePatientNote(encounter.session_id);
      onValidated();
    } catch (err) {
      // 409 = unresolved Stage 2 conflict (#606 invariant) — surface the
      // backend's conflict detail inline; anything else is a generic message.
      if (err instanceof ApiError && err.status === 409) {
        setRowError(parseDetailError(err, t("validateConflict")));
      } else {
        setRowError(humanizeError(err, t("validateFailed")));
      }
    } finally {
      setValidating(false);
    }
  }, [encounter.session_id, onValidated, t]);

  return (
    <li className="py-2.5">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-navy-50 text-navy-400 ring-1 ring-inset ring-navy-100">
          <Stethoscope className="h-4 w-4" />
        </span>
        <div className="flex-1 min-w-0">
          {/* Plain anchor for dynamic /portal/notes/[id] under static export. */}
          <a
            href={`/portal/notes/${encounter.session_id}`}
            className="text-sm font-medium text-navy-800 truncate hover:underline"
            data-testid={`patient-chart-row-${encounter.session_id}`}
          >
            {humanSpecialty(encounter.specialty)}
          </a>
          <p className="text-xs text-gray-500 mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="flex items-center gap-1">
              <UserRound className="h-3 w-3 shrink-0 text-navy-300" />
              <span className="truncate max-w-[14rem]">
                {encounter.clinician_name}
              </span>
            </span>
            <span className="flex items-center gap-1">
              <CalendarDays className="h-3 w-3 shrink-0 text-navy-300" />
              {formatRelative(encounter.created_at, { withYear: true })}
            </span>
            <code
              className="rounded-md bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] tracking-tight text-gray-500"
              title={encounter.session_id}
            >
              {shortSessionId(encounter.session_id)}
            </code>
          </p>
          {rowError && (
            <p
              className="mt-1 text-[11px] text-red-600"
              data-testid={`patient-chart-row-error-${encounter.session_id}`}
            >
              {rowError}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {encounter.is_approved ? (
            <Badge variant="success" dot>
              <span className="inline-flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" />
                {t("validatedBadge")}
              </span>
            </Badge>
          ) : (
            <Badge variant={variant} dot>
              {encounter.state.replace(/_/g, " ")}
            </Badge>
          )}
          {canValidate && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => void onValidate()}
              disabled={validating}
              data-testid={`patient-chart-validate-${encounter.session_id}`}
            >
              {validating ? t("validating") : t("validate")}
            </Button>
          )}
        </div>
      </div>
    </li>
  );
}
