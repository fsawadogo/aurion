"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  CheckCircleIcon,
  ClockIcon,
} from "@heroicons/react/24/outline";
import { getEvalSessions, submitEvalScore } from "@/lib/api";
import type { EvalSession } from "@/types";

export default function EvalPage() {
  const [evalSessions, setEvalSessions] = useState<EvalSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [transcriptAccuracy, setTranscriptAccuracy] = useState(50);
  const [citationCorrectness, setCitationCorrectness] = useState(50);
  const [descriptiveCompliance, setDescriptiveCompliance] = useState(50);
  const [evalNotes, setEvalNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function fetchEvalSessions() {
    setLoading(true);
    setError(null);
    try {
      const data = await getEvalSessions();
      setEvalSessions(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load eval sessions",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchEvalSessions();
  }, []);

  const selectedSession = evalSessions.find((s) => s.id === selectedId);

  async function handleSubmitScore() {
    if (!selectedSession) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitEvalScore(selectedSession.session_id, {
        transcript_accuracy: transcriptAccuracy,
        citation_correctness: citationCorrectness,
        descriptive_mode_compliance: descriptiveCompliance,
        overall:
          Math.round(
            ((transcriptAccuracy +
              citationCorrectness +
              descriptiveCompliance) /
              3) *
              10,
          ) / 10,
        notes: evalNotes,
      });
      setTranscriptAccuracy(50);
      setCitationCorrectness(50);
      setDescriptiveCompliance(50);
      setEvalNotes("");
      await fetchEvalSessions();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to submit score",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <Header
        title="Evaluation"
        subtitle="Review sessions and score quality"
      />

      <div className="p-6 lg:p-8">
        {error && (
          <div className="mb-6 flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-600/10">
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 text-xs font-medium">
              Dismiss
            </button>
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Session list */}
          <div className="lg:col-span-2">
            <div className="overflow-hidden rounded-xl border border-gray-200/60 bg-white shadow-card">
              <div className="overflow-x-auto">
                <table className="min-w-full">
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50/80">
                      <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Session</th>
                      <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Clinician</th>
                      <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Specialty</th>
                      <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Masked</th>
                      <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Status</th>
                      <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Score</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {loading ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-6">
                          <LoadingSkeleton lines={4} />
                        </td>
                      </tr>
                    ) : evalSessions.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-12 text-center">
                          <p className="text-sm text-gray-400">No sessions available for evaluation yet.</p>
                        </td>
                      </tr>
                    ) : (
                      evalSessions.map((s) => (
                        <tr
                          key={s.id}
                          className={`cursor-pointer transition-colors ${
                            selectedId === s.id
                              ? "bg-gold-50/60 hover:bg-gold-50/80"
                              : "hover:bg-gray-50/80"
                          }`}
                          onClick={() => setSelectedId(s.id)}
                        >
                          <td className="whitespace-nowrap px-4 py-3">
                            <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                              {s.session_id.length > 12
                                ? `${s.session_id.slice(0, 8)}...`
                                : s.session_id}
                            </code>
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                            {s.clinician_name}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm capitalize text-gray-500">
                            {s.specialty.replace(/_/g, " ")}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm">
                            {s.transcript_masked && s.frames_masked ? (
                              <Badge variant="success" dot>Yes</Badge>
                            ) : (
                              <Badge variant="error" dot>No</Badge>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm">
                            {s.scored ? (
                              <Badge variant="success">
                                <span className="inline-flex items-center gap-1">
                                  <CheckCircleIcon className="h-3 w-3" />
                                  Scored
                                </span>
                              </Badge>
                            ) : (
                              <Badge variant="warning">
                                <span className="inline-flex items-center gap-1">
                                  <ClockIcon className="h-3 w-3" />
                                  Pending
                                </span>
                              </Badge>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm font-semibold text-navy-700">
                            {s.scores ? `${s.scores.overall}%` : "--"}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedId(s.id);
                              }}
                            >
                              Review
                            </Button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Scoring panel */}
          <div className="lg:col-span-1 lg:sticky lg:top-20 lg:self-start">
            <Card title="Quality Scoring">
              {selectedSession ? (
                selectedSession.scored && selectedSession.scores ? (
                  <div className="space-y-4 animate-fade-in">
                    <p className="text-xs text-gray-400">
                      Session{" "}
                      <code className="rounded bg-gray-100 px-1 py-0.5 text-gray-600">
                        {selectedSession.session_id.length > 12
                          ? `${selectedSession.session_id.slice(0, 8)}...`
                          : selectedSession.session_id}
                      </code>{" "}
                      has been scored.
                    </p>
                    <div className="space-y-2">
                      <ScoreRow
                        label="Transcript Accuracy"
                        value={selectedSession.scores.transcript_accuracy}
                      />
                      <ScoreRow
                        label="Citation Correctness"
                        value={selectedSession.scores.citation_correctness}
                      />
                      <ScoreRow
                        label="Descriptive Mode"
                        value={selectedSession.scores.descriptive_mode_compliance}
                      />
                      <div className="border-t border-gray-100 pt-2">
                        <ScoreRow
                          label="Overall"
                          value={selectedSession.scores.overall}
                          bold
                        />
                      </div>
                    </div>
                    {selectedSession.scores.notes && (
                      <div className="rounded-lg bg-gray-50 p-3">
                        <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-gray-400">Notes</p>
                        <p className="text-sm text-gray-600">
                          {selectedSession.scores.notes}
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-5 animate-fade-in">
                    <p className="text-xs text-gray-400">
                      Scoring session{" "}
                      <code className="rounded bg-gray-100 px-1 py-0.5 text-gray-600">
                        {selectedSession.session_id.length > 12
                          ? `${selectedSession.session_id.slice(0, 8)}...`
                          : selectedSession.session_id}
                      </code>
                    </p>
                    <SliderInput
                      label="Transcript Accuracy"
                      value={transcriptAccuracy}
                      onChange={setTranscriptAccuracy}
                    />
                    <SliderInput
                      label="Citation Correctness"
                      value={citationCorrectness}
                      onChange={setCitationCorrectness}
                    />
                    <SliderInput
                      label="Descriptive Mode Compliance"
                      value={descriptiveCompliance}
                      onChange={setDescriptiveCompliance}
                    />
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-gray-700">
                        Notes
                      </label>
                      <textarea
                        rows={3}
                        value={evalNotes}
                        onChange={(e) => setEvalNotes(e.target.value)}
                        className="w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
                        placeholder="Quality observations..."
                      />
                    </div>
                    <Button
                      variant="primary"
                      fullWidth
                      loading={submitting}
                      onClick={handleSubmitScore}
                    >
                      Submit Score
                    </Button>
                  </div>
                )
              ) : (
                <div className="flex flex-col items-center justify-center py-6 text-center">
                  <div className="mb-3 rounded-lg bg-gray-50 p-3">
                    <svg className="h-6 w-6 text-gray-300" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd"/>
                    </svg>
                  </div>
                  <p className="text-sm text-gray-400">
                    Select a session to review and score.
                  </p>
                </div>
              )}
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}

function SliderInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  const color = value >= 90 ? "text-emerald-600" : value >= 70 ? "text-amber-600" : "text-red-600";
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label className="text-sm font-medium text-gray-700">{label}</label>
        <span className={`text-sm font-bold tabular-nums ${color}`}>{value}</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full cursor-pointer accent-gold-500"
      />
      <div className="mt-0.5 flex justify-between text-[10px] text-gray-300">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
    </div>
  );
}

function ScoreRow({
  label,
  value,
  bold,
}: {
  label: string;
  value: number;
  bold?: boolean;
}) {
  const color = value >= 90 ? "text-emerald-600" : value >= 70 ? "text-amber-600" : "text-red-600";
  return (
    <div className="flex items-center justify-between">
      <span
        className={`text-sm ${bold ? "font-semibold text-navy-700" : "text-gray-500"}`}
      >
        {label}
      </span>
      <span className={`text-sm tabular-nums ${bold ? "font-bold" : "font-semibold"} ${color}`}>
        {value}%
      </span>
    </div>
  );
}
