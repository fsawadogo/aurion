"use client";

import { ArrowLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouteSegment } from "@/lib/use-route-segment";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getSessionAudit, humanizeError} from "@/lib/api";
import { shortSessionId } from "@/lib/session-format";
import type { AuditEvent } from "@/types";

type EventVariant = "success" | "warning" | "error" | "info" | "neutral";

function eventBadgeVariant(eventType: string): EventVariant {
  if (eventType.includes("consent") || eventType.includes("masking_confirmed"))
    return "info";
  if (
    eventType.includes("recording") ||
    eventType.includes("paused") ||
    eventType.includes("purged")
  )
    return "neutral";
  if (eventType.includes("masking_failed") || eventType === "session_failed")
    return "error";
  if (eventType.includes("config")) return "warning";
  if (
    eventType.includes("delivered") ||
    eventType.includes("exported") ||
    eventType.includes("complete")
  )
    return "success";
  return "info";
}

// Timeline node ring color, keyed to the same semantic variant as the
// event badge so the rail is scannable at a glance. Shades match the
// Badge dot palette exactly (Badge.tsx dotColors) — the fixed compliance
// semantic colors, never themed.
const dotRingForVariant: Record<EventVariant, string> = {
  success: "ring-emerald-500",
  warning: "ring-amber-500",
  error: "ring-accent-red",
  info: "ring-blue-500",
  neutral: "ring-navy-400",
};

// Sentence-case an event type for display while keeping the raw value
// available via a title attribute. "stage1_delivered" → "Stage 1 delivered".
function humanizeEventType(raw: string): string {
  const s = raw
    .replace(/_/g, " ")
    .replace(/([a-z])(\d)/gi, "$1 $2")
    .trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : raw;
}

// Title-case a snake_case / SCREAMING_CASE label (detail keys, roles).
// "previous_state" → "Previous State"; "EVAL_TEAM" → "Eval Team".
function humanizeLabel(raw: string): string {
  return raw
    .replace(/_/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

// Render a single detail value as readable text instead of raw JSON.
function formatDetailValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

// Static-export gotcha — see web/lib/use-route-segment.ts for the full
// rationale. `useParams()` returns the "_" sentinel; the hook reads
// from the URL bar so the real session ID wins at runtime.
export default function AuditDetailClient(
  _props: { params: { sessionId: string } },
) {
  const sessionId = useRouteSegment("sessionId");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSessionAudit(sessionId)
      .then((data) => {
        if (cancelled) return;
        // Backend returns latest-first; reverse for a chronological top-to-bottom feed.
        const chronological = [...data].sort((a, b) =>
          a.event_timestamp.localeCompare(b.event_timestamp),
        );
        setEvents(chronological);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(humanizeError(err, "Failed to load timeline"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const firstTs = events[0]?.event_timestamp;
  const lastTs = events[events.length - 1]?.event_timestamp;

  return (
    <>
      <Header
        title="Session timeline"
        subtitle={`${events.length} event${events.length === 1 ? "" : "s"}`}
        actions={
          <Link href="/audit">
            <Button variant="secondary" size="sm">
              <ArrowLeft className="mr-1 h-4 w-4" />
              Back to audit log
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

        <Card className="mb-6">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="min-w-0">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                Session
              </p>
              <code
                title={sessionId}
                className="inline-block rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs tracking-tight text-gray-500"
              >
                {shortSessionId(sessionId)}
              </code>
              <p className="mt-1 break-all font-mono text-[11px] text-gray-400">
                {sessionId}
              </p>
            </div>
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                First event
              </p>
              <p className="text-sm text-gray-600">
                {firstTs ? new Date(firstTs).toLocaleString() : "—"}
              </p>
            </div>
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                Last event
              </p>
              <p className="text-sm text-gray-600">
                {lastTs ? new Date(lastTs).toLocaleString() : "—"}
              </p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-base font-semibold text-navy-700">Chronological events</h2>
            <p className="text-xs text-gray-400">Earliest at top</p>
          </div>

          {loading ? (
            <LoadingSkeleton lines={8} />
          ) : events.length === 0 ? (
            <p className="py-12 text-center text-sm text-gray-400">
              No audit events for this session.
            </p>
          ) : (
            <ol className="relative space-y-5 border-l border-gray-200 pl-6">
              {events.map((evt, i) => {
                const variant = eventBadgeVariant(evt.event_type);
                const detailEntries = evt.details
                  ? Object.entries(evt.details)
                  : [];
                return (
                  <li
                    key={`${evt.event_timestamp}-${evt.event_id || i}`}
                    className="relative"
                  >
                    <span
                      aria-hidden
                      className={
                        "absolute -left-[1.875rem] top-1 h-3 w-3 rounded-full bg-white ring-2 " +
                        dotRingForVariant[variant]
                      }
                    />
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <time
                        dateTime={evt.event_timestamp}
                        className="font-mono text-xs text-gray-400"
                      >
                        {new Date(evt.event_timestamp).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </time>
                      <span title={evt.event_type} className="inline-flex">
                        <Badge variant={variant} dot>
                          {humanizeEventType(evt.event_type)}
                        </Badge>
                      </span>
                      {evt.actor_role && (
                        <span
                          className="text-[11px] text-gray-400"
                          title={evt.actor_id || undefined}
                        >
                          by {humanizeLabel(evt.actor_role)}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-[11px] text-gray-400">
                      {new Date(evt.event_timestamp).toLocaleDateString()}
                    </p>
                    {detailEntries.length > 0 && (
                      <details className="group/details mt-2">
                        <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[11px] font-medium text-gray-400 transition-colors hover:text-gray-600 [&::-webkit-details-marker]:hidden">
                          <ChevronRight className="h-3 w-3 transition-transform duration-short group-open/details:rotate-90" />
                          {detailEntries.length} detail
                          {detailEntries.length === 1 ? "" : "s"}
                        </summary>
                        <dl className="mt-1.5 max-h-44 space-y-1 overflow-auto rounded-lg bg-gray-50 px-3 py-2 text-[11px]">
                          {detailEntries.map(([key, value]) => (
                            <div key={key} className="flex gap-2">
                              <dt
                                className="shrink-0 font-medium text-gray-500"
                                title={key}
                              >
                                {humanizeLabel(key)}
                              </dt>
                              <dd className="min-w-0 break-words font-mono text-gray-700">
                                {formatDetailValue(value)}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </details>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </Card>
      </div>
    </>
  );
}
