"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header";
import {
  CheckCircleIcon,
  ClockIcon,
} from "@heroicons/react/24/outline";
import { getEvalSessions, submitEvalScore } from "@/lib/api";
import type { EvalSession, EvalScore } from "@/types";

export default function EvalPage() {
  const [evalSessions, setEvalSessions] = useState<EvalSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [transcriptAccuracy, setTranscriptAccuracy] = useState(0);
  const [citationCorrectness, setCitationCorrectness] = useState(0);
  const [descriptiveCompliance, setDescriptiveCompliance] = useState(0);
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
      // Reset form
      setTranscriptAccuracy(0);
      setCitationCorrectness(0);
      setDescriptiveCompliance(0);
      setEvalNotes("");
      // Refresh data
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
        title="Eval Team Interface"
        subtitle="Review session triads and score quality"
      />

      <div className="p-6 lg:p-8">
        {error && (
          <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-2 text-red-500 underline"
            >
              dismiss
            </button>
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Session list */}
          <div className="lg:col-span-2">
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                        Session
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                        Clinician
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                        Specialty
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                        Masked
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                        Status
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                        Score
                      </th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {loading ? (
                      <tr>
                        <td
                          colSpan={7}
                          className="px-4 py-8 text-center text-sm text-gray-400"
                        >
                          Loading eval sessions...
                        </td>
                      </tr>
                    ) : evalSessions.length === 0 ? (
                      <tr>
                        <td
                          colSpan={7}
                          className="px-4 py-8 text-center text-sm text-gray-400"
                        >
                          No sessions available for evaluation yet.
                        </td>
                      </tr>
                    ) : (
                      evalSessions.map((s) => (
                        <tr
                          key={s.id}
                          className={`cursor-pointer hover:bg-gray-50 ${
                            selectedId === s.id ? "bg-gold-50" : ""
                          }`}
                          onClick={() => setSelectedId(s.id)}
                        >
                          <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-500">
                            {s.session_id.length > 12
                              ? `${s.session_id.slice(0, 8)}...`
                              : s.session_id}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                            {s.clinician_name}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                            {s.specialty.replace(/_/g, " ")}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm">
                            {s.transcript_masked && s.frames_masked ? (
                              <span className="text-green-600">Yes</span>
                            ) : (
                              <span className="text-red-600">No</span>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm">
                            {s.scored ? (
                              <span className="inline-flex items-center gap-1 text-green-600">
                                <CheckCircleIcon className="h-4 w-4" />
                                Scored
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-amber-600">
                                <ClockIcon className="h-4 w-4" />
                                Pending
                              </span>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm font-semibold text-navy">
                            {s.scores ? `${s.scores.overall}%` : "--"}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedId(s.id);
                              }}
                              className="text-gold-600 hover:text-gold-800"
                            >
                              Review
                            </button>
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
          <div className="lg:col-span-1">
            <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <h3 className="mb-4 text-base font-semibold text-navy">
                Quality Scoring
              </h3>

              {selectedSession ? (
                selectedSession.scored && selectedSession.scores ? (
                  <div className="space-y-4">
                    <p className="text-sm text-gray-500">
                      Session{" "}
                      {selectedSession.session_id.length > 12
                        ? `${selectedSession.session_id.slice(0, 8)}...`
                        : selectedSession.session_id}{" "}
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
                        value={
                          selectedSession.scores.descriptive_mode_compliance
                        }
                      />
                      <div className="border-t border-gray-200 pt-2">
                        <ScoreRow
                          label="Overall"
                          value={selectedSession.scores.overall}
                          bold
                        />
                      </div>
                    </div>
                    <div className="rounded-lg bg-gray-50 p-3">
                      <p className="text-xs text-gray-400">Notes</p>
                      <p className="mt-1 text-sm text-gray-600">
                        {selectedSession.scores.notes || "No notes."}
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <p className="text-sm text-gray-500">
                      Score session{" "}
                      {selectedSession.session_id.length > 12
                        ? `${selectedSession.session_id.slice(0, 8)}...`
                        : selectedSession.session_id}
                      :
                    </p>
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">
                        Transcript Accuracy (0-100)
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={transcriptAccuracy}
                        onChange={(e) =>
                          setTranscriptAccuracy(Number(e.target.value))
                        }
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">
                        Citation Correctness (0-100)
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={citationCorrectness}
                        onChange={(e) =>
                          setCitationCorrectness(Number(e.target.value))
                        }
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">
                        Descriptive Mode Compliance (0-100)
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={descriptiveCompliance}
                        onChange={(e) =>
                          setDescriptiveCompliance(Number(e.target.value))
                        }
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">
                        Notes
                      </label>
                      <textarea
                        rows={3}
                        value={evalNotes}
                        onChange={(e) => setEvalNotes(e.target.value)}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
                        placeholder="Quality observations..."
                      />
                    </div>
                    <button
                      onClick={handleSubmitScore}
                      disabled={submitting}
                      className="w-full rounded-lg bg-gold py-2.5 text-sm font-semibold text-navy transition-colors hover:bg-gold-600 disabled:opacity-60"
                    >
                      {submitting ? "Submitting..." : "Submit Score"}
                    </button>
                  </div>
                )
              ) : (
                <p className="text-sm text-gray-400">
                  Select a session from the table to review and score.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
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
  return (
    <div className="flex items-center justify-between">
      <span
        className={`text-sm ${bold ? "font-semibold text-navy" : "text-gray-600"}`}
      >
        {label}
      </span>
      <span
        className={`text-sm ${
          bold ? "font-bold text-navy" : "font-medium"
        } ${value >= 90 ? "text-green-600" : value >= 70 ? "text-amber-600" : "text-red-600"}`}
      >
        {value}%
      </span>
    </div>
  );
}
