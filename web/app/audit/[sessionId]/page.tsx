"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { ArrowLeftIcon } from "@heroicons/react/24/outline";
import { getSessionAudit } from "@/lib/api";
import type { AuditEvent } from "@/types";

function eventBadgeVariant(
  eventType: string,
): "success" | "warning" | "error" | "info" | "neutral" {
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

export default function AuditTimelinePage({
  params,
}: {
  params: { sessionId: string };
}) {
  const sessionId = decodeURIComponent(params.sessionId);
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
          setError(err instanceof Error ? err.message : "Failed to load timeline");
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
              <ArrowLeftIcon className="mr-1 h-4 w-4" />
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
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                Session
              </p>
              <code className="block break-all rounded bg-gray-100 px-2 py-1 font-mono text-xs text-gray-700">
                {sessionId}
              </code>
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
            <ol className="relative space-y-4 border-l border-gray-200 pl-6">
              {events.map((evt, i) => (
                <li
                  key={`${evt.event_timestamp}-${evt.event_id || i}`}
                  className="relative"
                >
                  <span
                    aria-hidden
                    className="absolute -left-[1.625rem] top-1 flex h-3 w-3 items-center justify-center rounded-full bg-white ring-2 ring-gold-400"
                  />
                  <div className="flex items-baseline gap-3">
                    <time className="text-xs font-mono text-gray-400">
                      {new Date(evt.event_timestamp).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </time>
                    <Badge variant={eventBadgeVariant(evt.event_type)}>
                      {evt.event_type}
                    </Badge>
                  </div>
                  <p className="mt-0.5 text-[11px] text-gray-400">
                    {new Date(evt.event_timestamp).toLocaleDateString()}
                  </p>
                  {evt.details && Object.keys(evt.details).length > 0 && (
                    <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-gray-50 px-3 py-2 text-[11px] text-gray-600">
                      {JSON.stringify(evt.details, null, 2)}
                    </pre>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </>
  );
}
