"use client";

import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouteSegment } from "@/lib/use-route-segment";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getSessionDetail, humanizeError} from "@/lib/api";
import {
  formatRelative,
  humanSpecialty,
  nameInitials,
  shortSessionId,
} from "@/lib/session-format";
import type { NoteSectionStatus, SessionDetail } from "@/types";

const stateBadgeVariant: Record<string, "success" | "warning" | "error" | "info" | "neutral"> = {
  IDLE: "neutral",
  CONSENT_PENDING: "warning",
  RECORDING: "error",
  PAUSED: "warning",
  PROCESSING_STAGE1: "info",
  AWAITING_REVIEW: "info",
  PROCESSING_STAGE2: "info",
  REVIEW_COMPLETE: "success",
  EXPORTED: "success",
  PURGED: "neutral",
  FAILED: "error",
};

const statusBadgeVariant: Record<NoteSectionStatus, "success" | "warning" | "error" | "info" | "neutral"> = {
  populated: "success",
  pending_video: "info",
  not_captured: "neutral",
  processing_failed: "error",
};

const statusLabel: Record<NoteSectionStatus, string> = {
  populated: "Populated",
  pending_video: "Awaiting video",
  not_captured: "Not captured",
  processing_failed: "Processing failed",
};

const sourceLabel: Record<string, string> = {
  transcript: "Transcript",
  visual: "Frame",
  screen: "Screen",
  physician_edit: "Physician edit",
};

// SCREAMING_CASE / snake_case enum → Title Case for display.
// "PROCESSING_STAGE1" → "Processing Stage 1". The raw value is kept in
// a `title` attribute at the call site so it stays available on hover.
function humanizeState(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/([a-z])(\d)/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Under static export the `params` prop carries the placeholder ID
// from `generateStaticParams` ("_"). `useParams()` returns the same
// sentinel — it reads from the matched route, not the URL bar — so
// downstream fetches hit /api/v1/sessions/_ and 422 in production.
// `useRouteSegment()` reads from `usePathname()`, which reflects the
// real URL after Amplify's SPA-fallback rewrite served the placeholder
// shell. `params` is ignored on purpose — preserved in the signature
// so the server wrapper in `page.tsx` keeps working without further
// plumbing.
export default function SessionDetailClient(
  _props: { params: { id: string } },
) {
  const sessionId = useRouteSegment("id");
  const [data, setData] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSessionDetail(sessionId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(humanizeError(err, "Failed to load session"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const pct = data ? Math.round(data.completeness_score * 100) : 0;
  const belowTarget = pct < 90;

  return (
    <>
      <Header
        title="Session detail"
        subtitle={
          data
            ? [data.clinician_name?.trim(), humanSpecialty(data.specialty)]
                .filter(Boolean)
                .join(" — ")
            : undefined
        }
        actions={
          <Link href="/sessions">
            <Button variant="secondary" size="sm">
              <ArrowLeft className="mr-1 h-4 w-4" />
              Back to sessions
            </Button>
          </Link>
        }
      />

      <div className="p-6 lg:p-8">
        {error && (
          <Card className="mb-6 border-red-200 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </Card>
        )}

        {loading ? (
          <Card>
            <LoadingSkeleton lines={8} />
          </Card>
        ) : data === null ? (
          !error && (
            <Card>
              <div className="py-12 text-center">
                <p className="text-sm font-medium text-gray-600">Session not found</p>
                <p className="mt-1 text-xs text-gray-400">
                  This session may have been purged, or the link is no longer valid.
                </p>
              </div>
            </Card>
          )
        ) : (
          <>
            {/* Summary card */}
            <Card className="mb-6">
              <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
                <SummaryCell label="Clinician">
                  {data.clinician_name?.trim() ? (
                    <div className="flex items-center gap-2.5" title={data.clinician_name}>
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-navy-50 text-[11px] font-semibold text-navy-700 ring-1 ring-inset ring-navy-100">
                        {nameInitials(data.clinician_name)}
                      </span>
                      <span className="text-sm font-medium text-navy-800">
                        {data.clinician_name}
                      </span>
                    </div>
                  ) : (
                    <span className="text-sm text-gray-400">—</span>
                  )}
                </SummaryCell>
                <SummaryCell label="Session ID">
                  <code
                    title={data.id}
                    className="rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs tracking-tight text-gray-500"
                  >
                    {shortSessionId(data.id)}
                  </code>
                </SummaryCell>
                <SummaryCell label="State">
                  <Badge variant={stateBadgeVariant[data.state] ?? "neutral"} dot>
                    <span title={data.state}>{humanizeState(data.state)}</span>
                  </Badge>
                </SummaryCell>
                <SummaryCell label="Completeness">
                  <div className="flex items-center gap-3">
                    <div className="h-1.5 w-20 overflow-hidden rounded-full bg-gray-100">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          belowTarget ? "bg-red-400" : "bg-gradient-to-r from-gold-400 to-gold-500"
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className={`text-sm font-semibold ${belowTarget ? "text-red-600" : "text-emerald-600"}`}>
                      {pct}%
                    </span>
                  </div>
                </SummaryCell>
                <SummaryCell label="Sections">
                  <span className="text-sm">
                    <span className="font-medium">{data.sections_populated}</span>
                    <span className="text-gray-400"> / {data.sections_required} required</span>
                  </span>
                </SummaryCell>

                <SummaryCell label="Note version">
                  {data.note_version > 0 ? (
                    <span className="text-sm">
                      v{data.note_version}
                      <span className="ml-1 text-xs text-gray-400">
                        (stage {data.note_stage}
                        {data.is_approved ? ", approved" : ""})
                      </span>
                    </span>
                  ) : (
                    <span className="text-sm text-gray-400">No note yet</span>
                  )}
                </SummaryCell>
                <SummaryCell label="Provider">
                  {data.provider_used ? (
                    <span className="text-sm text-gray-600">{data.provider_used}</span>
                  ) : (
                    <span className="text-sm text-gray-400">—</span>
                  )}
                </SummaryCell>
                <SummaryCell label="Created / Updated">
                  <div className="space-y-0.5 text-sm text-gray-500">
                    <span
                      className="block"
                      title={new Date(data.created_at).toLocaleString()}
                    >
                      <span className="text-gray-400">Created</span>{" "}
                      {formatRelative(data.created_at)}
                    </span>
                    <span
                      className="block"
                      title={new Date(data.updated_at).toLocaleString()}
                    >
                      <span className="text-gray-400">Updated</span>{" "}
                      {formatRelative(data.updated_at)}
                    </span>
                  </div>
                </SummaryCell>
              </div>
            </Card>

            {/* Sections table */}
            <Card>
              <div className="mb-4 flex items-baseline justify-between">
                <h2 className="text-base font-semibold text-navy-700">Section Coverage</h2>
                <p className="text-xs text-gray-400">
                  Per-section coverage against the {humanSpecialty(data.specialty)} template.
                  Required sections that are empty are highlighted.
                </p>
              </div>

              {data.sections.length === 0 ? (
                <p className="py-12 text-center text-sm text-gray-400">
                  No template sections — the specialty template may have been removed.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full">
                    <thead>
                      <tr className="border-b border-gray-100 bg-gray-50/80">
                        <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Section</th>
                        <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Required</th>
                        <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Status</th>
                        <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Claims</th>
                        <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Source breakdown</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {data.sections.map((sec) => {
                        const isGap = sec.required && sec.status !== "populated";
                        return (
                          <tr key={sec.id} className={isGap ? "bg-red-50/30" : ""}>
                            <td className="whitespace-nowrap px-4 py-3">
                              <p className="text-sm font-medium text-gray-700">{sec.title}</p>
                              <p className="font-mono text-[11px] text-gray-400">{sec.id}</p>
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-sm">
                              <span className={sec.required ? "font-medium text-gray-600" : "text-gray-400"}>
                                {sec.required ? "Required" : "Optional"}
                              </span>
                            </td>
                            <td className="whitespace-nowrap px-4 py-3">
                              <Badge variant={statusBadgeVariant[sec.status] ?? "neutral"} dot>
                                {statusLabel[sec.status] ?? sec.status}
                              </Badge>
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                              {sec.claims_count}
                            </td>
                            <td className="px-4 py-3 text-xs text-gray-500">
                              {Object.keys(sec.claim_sources).length === 0 ? (
                                <span className="text-gray-300">—</span>
                              ) : (
                                <div className="flex flex-wrap gap-1.5">
                                  {Object.entries(sec.claim_sources).map(([src, count]) => (
                                    <span
                                      key={src}
                                      className="inline-flex items-center gap-1 rounded bg-gray-100 px-1.5 py-0.5"
                                    >
                                      <span className="text-gray-600">{sourceLabel[src] ?? src}</span>
                                      <span className="font-mono text-gray-400">{count}</span>
                                    </span>
                                  ))}
                                </div>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              <p className="mt-4 text-[11px] text-gray-400">
                Claim text is not surfaced here — for masked transcript / frame / note
                review, use the <Link href="/eval" className="underline">Eval interface</Link>.
              </p>
            </Card>
          </>
        )}
      </div>
    </>
  );
}

function SummaryCell({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
        {label}
      </p>
      <div>{children}</div>
    </div>
  );
}
