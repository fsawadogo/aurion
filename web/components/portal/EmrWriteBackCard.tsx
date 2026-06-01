"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowUpTrayIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
  PaperAirplaneIcon,
  ServerStackIcon,
} from "@heroicons/react/24/outline";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  listEmrConnectors,
  listMySessionEmrWriteBacks,
  sendMySessionToEmr,
} from "@/lib/portal-api";
import type {
  EmrConnectorsCatalog,
  EmrWriteBack,
  EmrWriteBackStatus,
} from "@/types";

/**
 * EMR write-back card — #57 foundation.
 *
 * Approval-gated (the note can't be sent to the EMR from a draft).
 * Shows the connector dropdown (single-option in the foundation
 * deployment — `stub` only), a Send button, and the history of past
 * attempts.
 *
 * Status semantics:
 *   queued / sending — transient (we surface them anyway in case of
 *     a slow connector; the row will flip to sent or failed by the
 *     time the route returns synchronously)
 *   sent — green check; shows the EMR-side external id (the chart
 *     link for billing dispute reconciliation)
 *   failed — amber warning; shows the sanitized error_reason so the
 *     physician knows whether to retry or escalate
 *
 * The card carries a small "Pilot mode" pill when the only connector
 * available is `stub` — keeps the physician from thinking the note
 * actually went to a chart system.
 */

interface EmrWriteBackCardProps {
  sessionId: string;
  /** From the parent's ExportMetadata.is_approved. */
  noteApproved: boolean;
}

export default function EmrWriteBackCard({
  sessionId,
  noteApproved,
}: EmrWriteBackCardProps) {
  const [rows, setRows] = useState<EmrWriteBack[]>([]);
  const [connectors, setConnectors] = useState<EmrConnectorsCatalog | null>(null);
  const [selectedConnector, setSelectedConnector] = useState<string>("stub");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [history, cat] = await Promise.all([
        listMySessionEmrWriteBacks(sessionId),
        listEmrConnectors(),
      ]);
      setRows(history);
      setConnectors(cat);
      // If we haven't picked a connector yet (or the deployment lost
      // ours), default to the catalog's stated default.
      if (!cat.available.includes(selectedConnector)) {
        setSelectedConnector(cat.default);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load EMR status.");
    } finally {
      setLoading(false);
    }
  }, [sessionId, selectedConnector]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function send() {
    setSending(true);
    setError(null);
    try {
      const row = await sendMySessionToEmr(sessionId, selectedConnector);
      // Prepend (newest-first ordering matches backend)
      setRows([row, ...rows]);
      if (row.status === "failed") {
        // Friendly callout — the row already carries the error_reason
        // for the row-level surface; this is the top-level toast.
        setError(
          `Send recorded but the connector failed: ${row.error_reason ?? "unknown reason"}`,
        );
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Send failed.";
      if (/\b409\b/.test(msg)) {
        setError("EMR write-back requires an approved note.");
      } else if (/\b400\b/.test(msg)) {
        setError("Unknown EMR connector — please pick another.");
      } else {
        setError(msg);
      }
    } finally {
      setSending(false);
    }
  }

  if (!noteApproved) return null;

  const isPilotMode =
    connectors !== null
    && connectors.available.length === 1
    && connectors.available[0] === "stub";

  const lastSent = rows.find((r) => r.status === "sent");

  // Latest (newest) row dictates the action-bar mode. The retry
  // scheduler (#174) mutates this same row on each retry; we want
  // the UI to read "auto-retry in flight" so the physician doesn't
  // create a duplicate by clicking "Send again."
  const latest = rows[0];
  const isAutoRetryPending =
    latest !== undefined
    && latest.status === "failed"
    && latest.scheduled_at !== null
    && latest.scheduled_at !== undefined;
  const isTerminalFailure =
    latest !== undefined
    && latest.status === "failed"
    && (latest.scheduled_at === null || latest.scheduled_at === undefined);

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2 text-aurion-headline">
        <ServerStackIcon className="h-4 w-4 text-gold-500" />
        EMR write-back
        {isPilotMode && (
          <Badge variant="warning" dot>
            Pilot mode — stub connector
          </Badge>
        )}
        {lastSent && (
          <span className="aurion-micro ml-2 text-emerald-700">
            Sent {new Date(lastSent.created_at).toLocaleString()}
          </span>
        )}
      </div>

      {isPilotMode && (
        <div className="mb-3 flex items-start gap-2 rounded-aurion-md bg-amber-50 border border-amber-200 px-3 py-2 text-aurion-caption text-amber-900">
          <ExclamationTriangleIcon className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <strong>Pilot connector active.</strong> Sends record the
            attempt locally with full audit trail but do not transmit
            to an external EMR. Real Oscar / Epic / generic-FHIR
            connectors land in follow-ups.
          </div>
        </div>
      )}

      {error && (
        <div className="mb-3 rounded-aurion-md bg-amber-50 border border-amber-200 px-3 py-2 text-aurion-caption text-amber-800">
          {error}
        </div>
      )}

      {loading ? (
        <LoadingSkeleton lines={2} />
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-2 mb-3">
            {connectors && connectors.available.length > 1 && (
              <div>
                <label
                  htmlFor="emr-connector"
                  className="block text-aurion-micro text-navy-500 mb-0.5"
                >
                  Connector
                </label>
                <select
                  id="emr-connector"
                  value={selectedConnector}
                  onChange={(e) => setSelectedConnector(e.target.value)}
                  className="px-2 py-1 text-sm rounded-aurion-xs border border-hairline focus:border-gold-500 focus:outline-none"
                  disabled={sending}
                >
                  {connectors.available.map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {/* Button is always enabled (clinician escape hatch) but
                the copy + callout below set expectations differently
                when an auto-retry is already queued. A click while a
                retry is pending creates a NEW write-back row
                alongside the queued retry — explicit physician
                action overrides the scheduler. */}
            <Button
              variant={isAutoRetryPending ? "ghost" : "primary"}
              size="sm"
              loading={sending}
              disabled={sending}
              onClick={() => void send()}
            >
              <PaperAirplaneIcon className="h-4 w-4 mr-1.5" />
              {rows.length === 0
                ? "Send to EMR"
                : isAutoRetryPending
                ? "Send fresh now (skip wait)"
                : "Send again"}
            </Button>
          </div>

          {isAutoRetryPending && latest.scheduled_at && (
            <div className="mb-3 flex items-start gap-2 rounded-aurion-md bg-amber-50 border border-amber-200 px-3 py-2 text-aurion-caption text-amber-900">
              <ArrowUpTrayIcon className="h-4 w-4 mt-0.5 shrink-0 animate-pulse" />
              <div>
                <strong>
                  Auto-retry scheduled for{" "}
                  {new Date(latest.scheduled_at).toLocaleTimeString()}.
                </strong>{" "}
                The system will re-send the same payload automatically.
                If you need to force a fresh attempt sooner, click
                Send again — it creates a new write-back row alongside
                the queued retry.
              </div>
            </div>
          )}

          {isTerminalFailure && (
            <div className="mb-3 flex items-start gap-2 rounded-aurion-md bg-red-50 border border-red-200 px-3 py-2 text-aurion-caption text-red-900">
              <ExclamationTriangleIcon className="h-4 w-4 mt-0.5 shrink-0" />
              <div>
                <strong>No more auto-retries.</strong> The last attempt
                hit a terminal error or exhausted the retry budget.
                Use Send again to fresh-start the write-back; if the
                problem is config (auth, endpoint), fix it first.
              </div>
            </div>
          )}

          {rows.length > 0 && (
            <ul className="divide-y divide-hairline">
              {rows.map((r) => (
                <WriteBackRow key={r.id} row={r} />
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}

function WriteBackRow({ row }: { row: EmrWriteBack }) {
  const isRetryPending = row.status === "failed" && !!row.scheduled_at;
  const isTerminal = row.status === "failed" && !row.scheduled_at;
  return (
    <li className="py-3 flex items-start gap-3">
      <StatusIcon status={row.status} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
          <StatusBadge status={row.status} />
          <span className="aurion-callout text-navy-700">
            via {row.connector}
          </span>
          {row.attempt_count > 1 && (
            <span className="text-aurion-micro text-navy-500">
              · attempt {row.attempt_count}
            </span>
          )}
          {isRetryPending && (
            <Badge variant="warning" dot>
              Auto-retry queued
            </Badge>
          )}
          {isTerminal && (
            <Badge variant="neutral">No more retries</Badge>
          )}
        </div>
        {row.external_id && (
          <p className="text-aurion-caption text-navy-700 mt-1 font-mono break-all">
            EMR id: {row.external_id}
          </p>
        )}
        {row.error_reason && (
          <p className="text-aurion-caption text-amber-800 mt-1 leading-snug">
            {row.error_reason}
          </p>
        )}
        {isRetryPending && row.scheduled_at && (
          <p className="text-aurion-caption text-amber-700 mt-1">
            Next attempt at{" "}
            <strong>
              {new Date(row.scheduled_at).toLocaleTimeString()}
            </strong>
          </p>
        )}
        <p className="text-aurion-micro text-navy-400 mt-1">
          {new Date(row.created_at).toLocaleString()}
          {" · "}
          fingerprint {row.payload_fingerprint.slice(0, 12)}…
        </p>
      </div>
    </li>
  );
}

function StatusIcon({ status }: { status: EmrWriteBackStatus }) {
  switch (status) {
    case "sent":
      return <CheckCircleIcon className="h-5 w-5 text-emerald-600 shrink-0 mt-0.5" />;
    case "failed":
      return <ExclamationTriangleIcon className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />;
    default:
      return <ArrowUpTrayIcon className="h-5 w-5 text-navy-400 shrink-0 mt-0.5" />;
  }
}

function StatusBadge({ status }: { status: EmrWriteBackStatus }) {
  switch (status) {
    case "queued":
      return <Badge variant="neutral">Queued</Badge>;
    case "sending":
      return <Badge variant="info" dot>Sending</Badge>;
    case "sent":
      return <Badge variant="success" dot>Sent</Badge>;
    case "failed":
      return <Badge variant="warning" dot>Failed</Badge>;
  }
}
