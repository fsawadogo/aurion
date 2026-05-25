"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { ArrowLeftIcon } from "@heroicons/react/24/outline";
import { getEvalSession } from "@/lib/api";
import type { Claim, EvalSessionDetail } from "@/types";

const statusBadge: Record<string, "success" | "warning" | "error" | "info" | "neutral"> = {
  populated: "success",
  pending_video: "info",
  not_captured: "neutral",
  processing_failed: "error",
};

const sourceBadge: Record<Claim["source_type"], "success" | "warning" | "error" | "info" | "neutral"> = {
  transcript: "info",
  visual: "warning",
  screen: "neutral",
  physician_edit: "success",
};

const sourceLabel: Record<Claim["source_type"], string> = {
  transcript: "Transcript",
  visual: "Frame",
  screen: "Screen",
  physician_edit: "Physician edit",
};

function fmtMs(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export default function EvalDetailPage({ params }: { params: { id: string } }) {
  const evalId = params.id;
  const [data, setData] = useState<EvalSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [highlightSourceId, setHighlightSourceId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getEvalSession(evalId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [evalId]);

  // Frame citations = note claims with source_type === "visual" across all sections.
  const frameCitations = useMemo<Array<Claim & { section_id: string; section_title: string }>>(() => {
    if (!data) return [];
    const out: Array<Claim & { section_id: string; section_title: string }> = [];
    for (const sec of data.note_sections) {
      for (const c of sec.claims || []) {
        if (c.source_type === "visual") {
          out.push({ ...c, section_id: sec.id, section_title: sec.title });
        }
      }
    }
    return out;
  }, [data]);

  return (
    <>
      <Header
        title={data ? `Eval — ${data.clinician_name}` : "Eval"}
        subtitle={data ? data.specialty.replace(/_/g, " ") : undefined}
        actions={
          <Link href="/eval">
            <Button variant="secondary" size="sm">
              <ArrowLeftIcon className="mr-1 h-4 w-4" />
              Back to list
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
            <LoadingSkeleton lines={10} />
          </Card>
        ) : data === null ? null : (
          <>
            {/* Summary strip */}
            <Card className="mb-6">
              <div className="grid gap-4 md:grid-cols-4 lg:grid-cols-6">
                <Cell label="Session">
                  <code className="block break-all text-xs text-gray-600">{data.session_id}</code>
                </Cell>
                <Cell label="Transcript">
                  <Badge variant={data.transcript_masked ? "success" : "error"} dot>
                    {data.transcript_masked ? "Masked" : "Unmasked"}
                  </Badge>
                </Cell>
                <Cell label="Frames">
                  <Badge variant={data.frames_masked ? "success" : "error"} dot>
                    {data.frames_masked ? "Masked" : "Unmasked"}
                  </Badge>
                </Cell>
                <Cell label="Note version">
                  {data.note_version > 0 ? (
                    <span className="text-sm">
                      v{data.note_version}
                      <span className="ml-1 text-xs text-gray-400">(stage {data.note_stage})</span>
                    </span>
                  ) : (
                    <span className="text-sm text-gray-400">No note yet</span>
                  )}
                </Cell>
                <Cell label="Completeness">
                  <span className="text-sm font-semibold">
                    {Math.round(data.note_completeness_score * 100)}%
                  </span>
                </Cell>
                <Cell label="Scored">
                  <Badge variant={data.scored ? "success" : "warning"} dot>
                    {data.scored ? "Yes" : "Pending"}
                  </Badge>
                </Cell>
              </div>
            </Card>

            {/* Three-pane triad */}
            <div className="grid gap-4 lg:grid-cols-12">
              {/* Transcript pane */}
              <div className="lg:col-span-4">
                <Card title={`Transcript (${data.transcript_segments.length})`}>
                  <p className="mb-3 text-[11px] text-gray-400">
                    PHI redacted upstream. Visual-trigger segments highlighted in gold.
                  </p>
                  {data.transcript_segments.length === 0 ? (
                    <p className="py-6 text-center text-sm text-gray-400">No transcript available.</p>
                  ) : (
                    <ol className="space-y-2 max-h-[600px] overflow-auto pr-1">
                      {data.transcript_segments.map((seg) => {
                        const isHighlight = highlightSourceId === seg.id;
                        return (
                          <li
                            id={`seg-${seg.id}`}
                            key={seg.id}
                            className={`rounded-lg p-2 text-sm transition-colors ${
                              isHighlight
                                ? "bg-gold-50 ring-1 ring-gold-200"
                                : seg.is_visual_trigger
                                ? "bg-amber-50/50"
                                : "hover:bg-gray-50"
                            }`}
                          >
                            <div className="flex items-baseline gap-2">
                              <code className="text-[10px] font-mono text-gray-400">
                                {seg.id}
                              </code>
                              <span className="text-[10px] text-gray-400">
                                {fmtMs(seg.start_ms)} → {fmtMs(seg.end_ms)}
                              </span>
                              {seg.is_visual_trigger && (
                                <Badge variant="warning">trigger</Badge>
                              )}
                            </div>
                            <p className="mt-0.5 text-gray-700">{seg.text}</p>
                          </li>
                        );
                      })}
                    </ol>
                  )}
                </Card>
              </div>

              {/* Note pane */}
              <div className="lg:col-span-5">
                <Card title={`Generated note (v${data.note_version})`}>
                  <p className="mb-3 text-[11px] text-gray-400">
                    Click any claim's source chip to scroll-highlight the anchor in the
                    transcript pane.
                  </p>
                  {data.note_sections.length === 0 ? (
                    <p className="py-6 text-center text-sm text-gray-400">
                      No note generated yet.
                    </p>
                  ) : (
                    <div className="space-y-5 max-h-[600px] overflow-auto pr-1">
                      {data.note_sections.map((sec) => (
                        <div key={sec.id}>
                          <div className="mb-1 flex items-baseline justify-between">
                            <h3 className="text-sm font-semibold text-navy-700">
                              {sec.title || sec.id}
                            </h3>
                            <Badge variant={statusBadge[sec.status] ?? "neutral"} dot>
                              {sec.status.replace(/_/g, " ")}
                            </Badge>
                          </div>
                          {sec.claims.length === 0 ? (
                            <p className="text-xs text-gray-300">no claims</p>
                          ) : (
                            <ul className="space-y-1.5">
                              {sec.claims.map((c) => (
                                <li key={c.id} className="rounded bg-gray-50 px-2 py-1.5">
                                  <p className="text-sm text-gray-700">{c.text}</p>
                                  <div className="mt-1 flex items-center gap-1.5 text-[10px] text-gray-400">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setHighlightSourceId(c.source_id);
                                        if (c.source_type === "transcript") {
                                          document
                                            .getElementById(`seg-${c.source_id}`)
                                            ?.scrollIntoView({ behavior: "smooth", block: "center" });
                                        }
                                      }}
                                      className="rounded bg-white px-1.5 py-0.5 ring-1 ring-gray-200 hover:ring-gold-300"
                                    >
                                      <Badge variant={sourceBadge[c.source_type]}>
                                        {sourceLabel[c.source_type]}
                                      </Badge>
                                      <code className="ml-1 text-[10px]">{c.source_id}</code>
                                    </button>
                                    {c.physician_edited && (
                                      <span className="rounded bg-emerald-50 px-1 py-0.5 text-emerald-700">
                                        edited
                                      </span>
                                    )}
                                  </div>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </div>

              {/* Frame citations pane */}
              <div className="lg:col-span-3">
                <Card title={`Frame citations (${frameCitations.length})`}>
                  <p className="mb-3 text-[11px] text-gray-400">
                    Visual claims extracted from the note — these are the masked
                    descriptions, not the raw frames (which never leave the device).
                  </p>
                  {frameCitations.length === 0 ? (
                    <p className="py-6 text-center text-sm text-gray-400">
                      No visual claims in this note.
                    </p>
                  ) : (
                    <ul className="space-y-2 max-h-[600px] overflow-auto pr-1">
                      {frameCitations.map((c) => (
                        <li key={c.id} className="rounded-lg bg-amber-50/50 p-2">
                          <p className="text-xs text-gray-700">{c.text}</p>
                          <p className="mt-1 text-[10px] text-gray-400">
                            <code>{c.source_id}</code>
                            <span className="ml-1">→ {c.section_title}</span>
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
        {label}
      </p>
      <div className="text-sm">{children}</div>
    </div>
  );
}
