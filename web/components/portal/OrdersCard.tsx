"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ClipboardDocumentCheckIcon,
  CheckIcon,
  TrashIcon,
  PencilIcon,
  ArrowPathIcon,
  BeakerIcon,
  CameraIcon,
  UserPlusIcon,
  ClipboardDocumentListIcon,
} from "@heroicons/react/24/outline";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  cancelMySessionOrder,
  confirmMySessionOrder,
  extractMySessionOrders,
  listMySessionOrders,
} from "@/lib/portal-api";
import type { NoteOrder, NoteOrderKind } from "@/types";

/**
 * Draft orders card on the note review screen.
 *
 * Visible only after the note is approved (parent gates the prop)
 * — orders are EMR-bound; can't come from a draft note.
 *
 * Three states:
 *   - No orders yet         → "Extract from note" CTA
 *   - Orders present        → grouped by kind, each row gets
 *                                confirm / cancel actions; status
 *                                badge tells the physician where it
 *                                sits in the lifecycle
 *   - Extracting / acting   → buttons spin; nothing else changes
 *
 * Edit-details flow stays inline-only here (status badge + key/value
 * preview); a richer per-kind edit modal can come later if the pilot
 * shows physicians need to tweak the structured shape often.
 */

interface OrdersCardProps {
  sessionId: string;
  /** From the parent's ExportMetadata.is_approved. */
  noteApproved: boolean;
}

const KIND_LABEL: Record<NoteOrderKind, string> = {
  imaging: "Imaging",
  lab: "Lab",
  referral: "Referral",
  prescription: "Prescription",
};

const KIND_ICON: Record<NoteOrderKind, typeof BeakerIcon> = {
  imaging: CameraIcon,
  lab: BeakerIcon,
  referral: UserPlusIcon,
  prescription: ClipboardDocumentListIcon,
};

export default function OrdersCard({
  sessionId,
  noteApproved,
}: OrdersCardProps) {
  const [orders, setOrders] = useState<NoteOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const xs = await listMySessionOrders(sessionId);
      setOrders(xs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load orders.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function extract() {
    setExtracting(true);
    setError(null);
    try {
      const created = await extractMySessionOrders(sessionId);
      // Reload the whole list so old drafts stay visible alongside
      // the new extraction batch.
      await load();
      if (created.length === 0) {
        setError(
          "The extractor found no orderable actions in this note. If something's missing, you can re-run after editing the note.",
        );
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Extraction failed.";
      if (/\b409\b/.test(msg)) {
        setError(
          "Orders can only be extracted after the note is approved.",
        );
      } else if (/\b502\b/.test(msg)) {
        setError("AI provider didn't respond — please try again.");
      } else {
        setError(msg);
      }
    } finally {
      setExtracting(false);
    }
  }

  async function onConfirm(o: NoteOrder) {
    setBusyId(o.id);
    setError(null);
    try {
      const updated = await confirmMySessionOrder(sessionId, o.id);
      setOrders(orders.map((x) => (x.id === updated.id ? updated : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Confirm failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function onCancel(o: NoteOrder) {
    if (
      !confirm(
        `Cancel this ${KIND_LABEL[o.kind].toLowerCase()} order? The row stays in the audit log.`,
      )
    )
      return;
    setBusyId(o.id);
    setError(null);
    try {
      const updated = await cancelMySessionOrder(sessionId, o.id);
      setOrders(orders.map((x) => (x.id === updated.id ? updated : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed.");
    } finally {
      setBusyId(null);
    }
  }

  if (!noteApproved) return null;

  // Order: drafts at the top (they need attention), then confirmed,
  // then sent, then cancelled. Within each, newest-first.
  const visible = [...orders].sort((a, b) => {
    const rank: Record<string, number> = {
      draft: 0,
      confirmed: 1,
      sent: 2,
      cancelled: 3,
    };
    if (rank[a.status] !== rank[b.status]) return rank[a.status] - rank[b.status];
    return b.created_at.localeCompare(a.created_at);
  });

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2 text-aurion-headline">
        <ClipboardDocumentCheckIcon className="h-4 w-4 text-gold-500" />
        Orders
        {visible.length > 0 && (
          <span className="aurion-micro ml-2">
            {visible.filter((o) => o.status === "draft").length} draft ·{" "}
            {visible.filter((o) => o.status === "confirmed").length} confirmed
          </span>
        )}
        <div className="flex-1" />
        {visible.length > 0 && (
          <Button
            size="sm"
            variant="ghost"
            loading={extracting}
            disabled={extracting}
            onClick={() => void extract()}
          >
            <ArrowPathIcon className="h-4 w-4 mr-1" />
            Re-extract
          </Button>
        )}
      </div>

      {error && (
        <div className="mb-3 rounded-aurion-md bg-amber-50 border border-amber-200 px-3 py-2 text-aurion-caption text-amber-800">
          {error}
        </div>
      )}

      {loading ? (
        <LoadingSkeleton lines={3} />
      ) : visible.length === 0 ? (
        <div className="py-2">
          <p className="aurion-callout text-navy-500 mb-3">
            Pull structured orders out of this note — imaging, labs,
            referrals, prescriptions. You confirm each before it goes
            out. The extractor only picks what you already dictated;
            nothing new gets invented.
          </p>
          <Button
            variant="primary"
            size="sm"
            loading={extracting}
            disabled={extracting}
            onClick={() => void extract()}
          >
            <ClipboardDocumentCheckIcon className="h-4 w-4 mr-1.5" />
            Extract orders from note
          </Button>
        </div>
      ) : (
        <ul className="divide-y divide-hairline">
          {visible.map((o) => (
            <OrderRow
              key={o.id}
              order={o}
              busy={busyId === o.id}
              onConfirm={() => void onConfirm(o)}
              onCancel={() => void onCancel(o)}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

/* ── Row ─────────────────────────────────────────────────────────────── */

function OrderRow({
  order,
  busy,
  onConfirm,
  onCancel,
}: {
  order: NoteOrder;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const Icon = KIND_ICON[order.kind];
  const isDraft = order.status === "draft";
  const isConfirmed = order.status === "confirmed";
  const isCancelled = order.status === "cancelled";

  return (
    <li
      className={
        "py-3 flex items-start gap-3 " +
        (isCancelled ? "opacity-60" : "")
      }
    >
      <Icon className="h-5 w-5 text-navy-400 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline flex-wrap gap-2 mb-1">
          <span className="aurion-callout font-semibold text-navy-800">
            {KIND_LABEL[order.kind]}
          </span>
          <StatusBadge status={order.status} />
        </div>
        <p className="text-aurion-caption text-navy-700 leading-snug">
          {summarizeDetails(order)}
        </p>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {isDraft && (
          <>
            <Button
              size="sm"
              variant="primary"
              loading={busy}
              disabled={busy}
              onClick={onConfirm}
            >
              <CheckIcon className="h-4 w-4 mr-1" />
              Confirm
            </Button>
            <button
              type="button"
              onClick={onCancel}
              disabled={busy}
              className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
              aria-label="Cancel order"
            >
              <TrashIcon className="h-4 w-4" />
            </button>
          </>
        )}
        {isConfirmed && (
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
            aria-label="Cancel order"
          >
            <TrashIcon className="h-4 w-4" />
          </button>
        )}
      </div>
    </li>
  );
}

function StatusBadge({ status }: { status: NoteOrder["status"] }) {
  switch (status) {
    case "draft":
      return <Badge variant="brand" dot>Draft — needs confirm</Badge>;
    case "confirmed":
      return <Badge variant="success" dot>Confirmed</Badge>;
    case "sent":
      return <Badge variant="info" dot>Sent</Badge>;
    case "cancelled":
      return <Badge variant="neutral">Cancelled</Badge>;
  }
}

function summarizeDetails(o: NoteOrder): string {
  const d = o.details as Record<string, string>;
  switch (o.kind) {
    case "imaging": {
      const lat = d.laterality && d.laterality !== "null" ? ` (${d.laterality})` : "";
      const ind = d.indication ? ` — ${d.indication}` : "";
      return `${d.modality ?? "?"} of ${d.body_part ?? "?"}${lat}${ind}`;
    }
    case "lab":
      return `${d.panel ?? "?"}${d.indication ? ` — ${d.indication}` : ""}`;
    case "referral":
      return [
        d.specialty,
        d.urgency && d.urgency !== "routine" ? `(${d.urgency})` : null,
        d.reason ? `— ${d.reason}` : null,
      ]
        .filter(Boolean)
        .join(" ");
    case "prescription":
      return [
        d.drug,
        d.dose,
        d.frequency,
        d.duration ? `for ${d.duration}` : null,
        d.indication ? `— ${d.indication}` : null,
      ]
        .filter(Boolean)
        .join(" ");
  }
}
