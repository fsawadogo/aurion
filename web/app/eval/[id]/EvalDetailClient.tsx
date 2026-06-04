"use client";

import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouteSegment } from "@/lib/use-route-segment";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  assignEvalSession,
  getEvalAssignees,
  getEvalSession,
  getMe,
  submitEvalScore,
  unassignEvalSession,
} from "@/lib/api";
import type {
  Claim,
  CurrentUser,
  EvalAssignee,
  EvalSessionDetail,
} from "@/types";

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

// Static-export gotcha — see web/lib/use-route-segment.ts. `useParams()`
// returns the build-time "_" sentinel under `output: "export"`; the hook
// reads from the URL bar so the real eval ID wins at runtime.
export default function EvalDetailClient(
  _props: { params: { id: string } },
) {
  const evalId = useRouteSegment("id");
  const [data, setData] = useState<EvalSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [highlightSourceId, setHighlightSourceId] = useState<string | null>(null);

  // Scoring panel state (spec-aligned: pass/fail + per-section SOAP +
  // hallucination count + discrepancies + free-form notes).
  const [descPass, setDescPass] = useState<boolean | null>(null);
  const [soapScores, setSoapScores] = useState<Record<string, number>>({});
  const [hallucinations, setHallucinations] = useState<number>(0);
  const [discrepancies, setDiscrepancies] = useState<string>("");
  const [scoreNotes, setScoreNotes] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [scoreFeedback, setScoreFeedback] = useState<string | null>(null);

  // EVAL-3 assignment state. The picker only shows for ADMINs. We fetch
  // /auth/me to know whether to show it, and /eval/assignees to populate
  // the dropdown options.
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [assignees, setAssignees] = useState<EvalAssignee[]>([]);
  const [assigning, setAssigning] = useState(false);
  const [assignmentFeedback, setAssignmentFeedback] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((u) => {
        if (cancelled) return;
        setMe(u);
        if (u.role === "ADMIN") {
          getEvalAssignees()
            .then((list) => !cancelled && setAssignees(list))
            .catch(() => {
              /* keep assignees empty; UI just hides the picker */
            });
        }
      })
      .catch(() => {
        /* /auth/me failure routes via fetchWithAuth's 401 handler */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleAssign(email: string) {
    if (!data) return;
    setAssigning(true);
    setAssignmentFeedback(null);
    try {
      const updated = email
        ? await assignEvalSession(data.session_id, email)
        : await unassignEvalSession(data.session_id);
      setData((prev) =>
        prev
          ? {
              ...prev,
              assigned_to: updated.assigned_to ?? null,
              assignment_completed_at: updated.assignment_completed_at ?? null,
            }
          : prev,
      );
      setAssignmentFeedback(email ? "Assigned." : "Unassigned.");
    } catch (err) {
      setAssignmentFeedback(err instanceof Error ? err.message : "Failed");
    } finally {
      setAssigning(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getEvalSession(evalId)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        // Hydrate the scoring form from any prior score so re-scoring
        // doesn't start from zero.
        const s = d.scores;
        if (s) {
          setDescPass(s.descriptive_mode_pass ?? null);
          setSoapScores(s.soap_section_scores ?? {});
          setHallucinations(s.hallucination_count ?? 0);
          setDiscrepancies((s.discrepancies ?? []).join("\n"));
          setScoreNotes(s.notes ?? "");
        }
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

  async function handleSubmitScore() {
    if (!data) return;
    setSubmitting(true);
    setScoreFeedback(null);
    try {
      // Map the spec-aligned form into both representations so the
      // backend keeps a consistent legacy aggregate on the row.
      const descCompliance = descPass === null ? 50 : descPass ? 100 : 0;
      const requiredSections = data.note_sections.filter(
        (s) => s.status !== "not_captured",
      );
      const soapAvg5 = requiredSections.length === 0
        ? 0
        : requiredSections.reduce(
            (acc, s) => acc + (soapScores[s.id] ?? 0),
            0,
          ) / requiredSections.length;
      const transcriptAccuracy = Math.round(soapAvg5 * 20); // 0..5 → 0..100
      const citationCorrectness = Math.max(0, 100 - hallucinations * 10); // each hall.= -10 pts
      const cleanedDiscrepancies = discrepancies
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0);

      await submitEvalScore(data.session_id, {
        transcript_accuracy: transcriptAccuracy,
        citation_correctness: citationCorrectness,
        descriptive_mode_compliance: descCompliance,
        notes: scoreNotes,
        descriptive_mode_pass: descPass,
        soap_section_scores: soapScores,
        hallucination_count: hallucinations,
        discrepancies: cleanedDiscrepancies.length > 0 ? cleanedDiscrepancies : null,
      });
      setScoreFeedback("Saved.");
    } catch (err) {
      setScoreFeedback(err instanceof Error ? err.message : "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }

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
              <ArrowLeft className="mr-1 h-4 w-4" />
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

                {/* Assigned-to cell — interactive only for ADMIN, read-only
                    for others. Spans 2 grid cols so the dropdown fits. */}
                <div className="md:col-span-2">
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    Assigned to
                  </p>
                  {me?.role === "ADMIN" ? (
                    <div className="flex items-center gap-2">
                      <select
                        value={data.assigned_to ?? ""}
                        onChange={(e) => handleAssign(e.target.value)}
                        disabled={assigning}
                        className="rounded-lg border border-gray-200 bg-gray-50/50 px-2 py-1 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100 disabled:opacity-50"
                      >
                        <option value="">— Unassigned —</option>
                        {assignees.map((a) => (
                          <option key={a.user_id} value={a.email}>
                            {a.full_name || a.email} ({a.role})
                          </option>
                        ))}
                      </select>
                      {assignmentFeedback && (
                        <span className="text-[11px] text-gray-500">
                          {assignmentFeedback}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-sm">
                      {data.assigned_to ? (
                        <span title={data.assigned_to}>
                          {data.assigned_to.split("@")[0]}
                          {data.assignment_completed_at && (
                            <Badge variant="success" dot>
                              done
                            </Badge>
                          )}
                        </span>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </span>
                  )}
                </div>
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
                    Click any claim&apos;s source chip to scroll-highlight the anchor
                    in the transcript pane.
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

            {/* Spec-aligned scoring panel */}
            <Card title="Quality scoring" className="mt-6">
              <p className="mb-4 text-[11px] text-gray-400">
                Per the eval spec: pass/fail on descriptive mode adherence,
                0–5 per SOAP section, count of hallucinated claims (text
                not traceable to any source), and free-form discrepancies
                to feed engineering quality tracking.
              </p>

              <div className="grid gap-6 lg:grid-cols-2">
                {/* Descriptive mode + hallucinations + notes column */}
                <div className="space-y-5">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">
                      Descriptive mode compliance
                    </label>
                    <div className="flex gap-2">
                      <Button
                        variant={descPass === true ? "primary" : "secondary"}
                        size="sm"
                        onClick={() => setDescPass(true)}
                      >
                        Pass
                      </Button>
                      <Button
                        variant={descPass === false ? "primary" : "secondary"}
                        size="sm"
                        onClick={() => setDescPass(false)}
                      >
                        Fail
                      </Button>
                      <Button
                        variant={descPass === null ? "primary" : "ghost"}
                        size="sm"
                        onClick={() => setDescPass(null)}
                      >
                        Skip
                      </Button>
                    </div>
                    <p className="mt-1 text-[11px] text-gray-400">
                      Fail = any claim crosses from describing into diagnosing /
                      interpreting / suggesting a clinical conclusion.
                    </p>
                  </div>

                  <div>
                    <label
                      htmlFor="hallucination-count"
                      className="mb-1.5 block text-sm font-medium text-gray-700"
                    >
                      Hallucination count
                    </label>
                    <input
                      id="hallucination-count"
                      type="number"
                      min={0}
                      value={hallucinations}
                      onChange={(e) =>
                        setHallucinations(Math.max(0, Number(e.target.value) || 0))
                      }
                      className="w-32 rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
                    />
                    <p className="mt-1 text-[11px] text-gray-400">
                      Claims with no traceable source_id anchor.
                    </p>
                  </div>

                  <div>
                    <label
                      htmlFor="discrepancies"
                      className="mb-1.5 block text-sm font-medium text-gray-700"
                    >
                      Discrepancies (one per line)
                    </label>
                    <textarea
                      id="discrepancies"
                      rows={3}
                      value={discrepancies}
                      onChange={(e) => setDiscrepancies(e.target.value)}
                      placeholder={"e.g.\nClaim claim_004 wrongly anchored to seg_007\nCONFLICTS flag missing on frame_00214"}
                      className="w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="score-notes"
                      className="mb-1.5 block text-sm font-medium text-gray-700"
                    >
                      Notes
                    </label>
                    <textarea
                      id="score-notes"
                      rows={2}
                      value={scoreNotes}
                      onChange={(e) => setScoreNotes(e.target.value)}
                      placeholder="Anything else worth recording."
                      className="w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
                    />
                  </div>
                </div>

                {/* Per-section SOAP completeness column */}
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">
                    SOAP completeness — per section (0 not present → 5 complete)
                  </label>
                  {data.note_sections.length === 0 ? (
                    <p className="text-xs text-gray-400">
                      No sections to score yet (note not generated).
                    </p>
                  ) : (
                    <ul className="space-y-2">
                      {data.note_sections.map((sec) => {
                        const val = soapScores[sec.id] ?? 0;
                        return (
                          <li key={sec.id} className="rounded-lg bg-gray-50/60 p-2">
                            <div className="mb-1 flex items-baseline justify-between">
                              <span className="text-sm text-gray-700">
                                {sec.title || sec.id}
                              </span>
                              <span className="text-xs font-mono text-navy-700 tabular-nums">
                                {val} / 5
                              </span>
                            </div>
                            <input
                              type="range"
                              min={0}
                              max={5}
                              step={1}
                              value={val}
                              onChange={(e) =>
                                setSoapScores((prev) => ({
                                  ...prev,
                                  [sec.id]: Number(e.target.value),
                                }))
                              }
                              className="w-full cursor-pointer accent-gold-500"
                            />
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </div>

              <div className="mt-6 flex items-center justify-end gap-3">
                {scoreFeedback && (
                  <span className="text-xs text-gray-500">{scoreFeedback}</span>
                )}
                <Button
                  variant="primary"
                  loading={submitting}
                  onClick={handleSubmitScore}
                >
                  {data.scored ? "Save changes" : "Submit score"}
                </Button>
              </div>
            </Card>
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
