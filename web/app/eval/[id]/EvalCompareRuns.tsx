"use client";

/**
 * EVAL-1 — Compare runs.
 *
 * A "run" is one note VERSION of this session (GET /admin/eval/sessions/{id}
 * /runs): the settings that produced it (`settings_snapshot`), deterministic
 * metrics (claim count, grounding rate, section completeness — no model call),
 * and the note itself. Pick two or more and the panel lays them out
 * side-by-side so you can read a flag-off-vs-on / with-vs-without-frames
 * comparison directly — the input for the eval receipt that gates turning the
 * template engine on.
 *
 * English-only, like the rest of the eval lab (an internal eval-team surface).
 */

import { useEffect, useMemo, useState } from "react";

import { getEvalSessionRuns } from "@/lib/api";
import type { EvalRun } from "@/types";

/** Deterministic metrics surfaced from `compute_grounding_metrics`. */
const METRIC_ROWS: { key: string; label: string; kind: "pct" | "count" }[] = [
  { key: "total_claims", label: "Claims", kind: "count" },
  { key: "grounding_rate", label: "Grounding rate", kind: "pct" },
  { key: "ungrounded_claims", label: "Ungrounded claims", kind: "count" },
  { key: "section_completeness", label: "Section completeness", kind: "pct" },
  { key: "ap_claims", label: "A&P claims", kind: "count" },
  { key: "multi_anchor_rate", label: "A&P multi-source", kind: "pct" },
];

function stageLabel(stage: number): string {
  if (stage === 1) return "Stage 1 · transcript";
  if (stage === 2) return "Stage 2 · + frames";
  return `Stage ${stage}`;
}

function metricLabel(run: EvalRun, key: string, kind: "pct" | "count"): string {
  const v = run.metrics[key];
  if (v == null || Number.isNaN(v)) return "—";
  return kind === "pct" ? `${Math.round(v * 100)}%` : `${Math.round(v)}`;
}

/** Settings pulled from the version's provenance snapshot. Null snapshot (a
 * version generated before the provenance migration) → every field is "—". */
function templateLabel(run: EvalRun): string {
  const s = run.settings_snapshot;
  if (!s) return "—";
  if (s.custom_template_id) return "Custom template";
  if (s.template_key) return String(s.template_key);
  return "Specialty default";
}

function flagLabel(run: EvalRun, key: string): string {
  const s = run.settings_snapshot;
  if (!s || s[key] == null) return "—";
  return s[key] ? "On" : "Off";
}

function snapStr(run: EvalRun, key: string): string {
  const s = run.settings_snapshot;
  if (!s || s[key] == null) return "—";
  return String(s[key]);
}

const SETTINGS_ROWS: { label: string; get: (r: EvalRun) => string }[] = [
  { label: "Template", get: templateLabel },
  { label: "Template engine", get: (r) => flagLabel(r, "template_engine_enabled") },
  { label: "Grounded synthesis", get: (r) => flagLabel(r, "grounded_synthesis_enabled") },
  { label: "Detail level", get: (r) => snapStr(r, "detail_level") },
  { label: "Provider", get: (r) => r.provider_used },
];

export default function EvalCompareRuns({ sessionId }: { sessionId: string }) {
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  useEffect(() => {
    let alive = true;
    getEvalSessionRuns(sessionId)
      .then((rows) => {
        if (!alive) return;
        setRuns(rows);
        // Preselect the last two versions — the most useful default comparison
        // (e.g. Stage 1 vs the Stage 2 note built on top of it).
        const versions = rows.map((r) => r.version).sort((a, b) => a - b);
        setSelected(new Set(versions.slice(-2)));
      })
      .catch(() => {
        if (alive) setError("Could not load runs for this session.");
      });
    return () => {
      alive = false;
    };
  }, [sessionId]);

  const chosen = useMemo(
    () =>
      (runs ?? [])
        .filter((r) => selected.has(r.version))
        .sort((a, b) => a.version - b.version),
    [runs, selected],
  );

  const anyUnknownSettings = chosen.some((r) => !r.settings_snapshot);

  function toggle(version: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(version)) next.delete(version);
      else next.add(version);
      return next;
    });
  }

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!runs) return <p className="text-sm text-gray-500">Loading runs…</p>;
  if (runs.length === 0)
    return (
      <p className="text-sm text-gray-500">
        No note versions yet — a run appears once this session has a generated
        note.
      </p>
    );

  return (
    <div className="space-y-4" data-testid="eval-compare">
      <p className="text-sm text-gray-500">
        Each note version is a run. Pick two or more to compare the settings
        that produced them, the deterministic metrics, and the notes
        side-by-side.
      </p>

      {/* Run selector */}
      <div className="flex flex-wrap gap-2">
        {runs.map((r) => {
          const on = selected.has(r.version);
          return (
            <button
              key={r.version}
              type="button"
              onClick={() => toggle(r.version)}
              aria-pressed={on}
              data-testid={`eval-run-pill-${r.version}`}
              className={
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
                (on
                  ? "border-gold-500 bg-gold-50 text-navy-800"
                  : "border-gray-300 bg-white text-gray-600 hover:border-gray-400")
              }
            >
              v{r.version} · {stageLabel(r.stage)}
              {r.is_approved ? " · ✓ approved" : ""}
            </button>
          );
        })}
      </div>

      {chosen.length < 2 ? (
        <p className="text-sm text-gray-500">
          Select at least two runs to compare.
        </p>
      ) : (
        <>
          {/* Settings + metrics comparison */}
          <div className="overflow-x-auto">
            <table
              className="w-full min-w-[32rem] border-collapse text-sm"
              data-testid="eval-compare-table"
            >
              <thead>
                <tr className="border-b border-gray-200 text-left">
                  <th className="py-2 pr-4 font-semibold text-gray-500"> </th>
                  {chosen.map((r) => (
                    <th key={r.version} className="py-2 pr-4 font-semibold text-navy-800">
                      v{r.version}
                      <span className="block text-[11px] font-normal text-gray-400">
                        {stageLabel(r.stage)}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td
                    colSpan={chosen.length + 1}
                    className="pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400"
                  >
                    Settings
                  </td>
                </tr>
                {SETTINGS_ROWS.map((row) => (
                  <tr key={row.label} className="border-b border-gray-100">
                    <td className="py-1.5 pr-4 text-gray-500">{row.label}</td>
                    {chosen.map((r) => (
                      <td key={r.version} className="py-1.5 pr-4 text-navy-800">
                        {row.get(r)}
                      </td>
                    ))}
                  </tr>
                ))}
                <tr>
                  <td
                    colSpan={chosen.length + 1}
                    className="pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400"
                  >
                    Metrics
                  </td>
                </tr>
                {METRIC_ROWS.map((row) => (
                  <tr key={row.key} className="border-b border-gray-100">
                    <td className="py-1.5 pr-4 text-gray-500">{row.label}</td>
                    {chosen.map((r) => (
                      <td
                        key={r.version}
                        className="py-1.5 pr-4 tabular-nums text-navy-800"
                        data-testid={`metric-${row.key}-v${r.version}`}
                      >
                        {metricLabel(r, row.key, row.kind)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {anyUnknownSettings && (
            <p className="text-xs text-gray-400">
              &ldquo;—&rdquo; settings mean the version predates provenance
              capture; its flags/template weren&rsquo;t recorded. New versions
              carry the full snapshot.
            </p>
          )}

          {/* Side-by-side notes */}
          <div
            className="grid gap-4"
            style={{
              gridTemplateColumns: `repeat(${chosen.length}, minmax(16rem, 1fr))`,
            }}
          >
            {chosen.map((r) => (
              <div
                key={r.version}
                className="rounded-aurion-md border border-gray-200 p-3"
                data-testid={`eval-run-note-${r.version}`}
              >
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
                  v{r.version} · {stageLabel(r.stage)}
                </p>
                <div className="space-y-3">
                  {r.note_sections.map((sec) => (
                    <div key={sec.id}>
                      <p className="text-sm font-medium text-navy-800">
                        {sec.title}
                        <span className="ml-2 text-[11px] font-normal text-gray-400">
                          {sec.status}
                        </span>
                      </p>
                      {sec.claims.length > 0 ? (
                        <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-navy-700">
                          {sec.claims.map((c) => (
                            <li key={c.id}>{c.text}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-1 text-xs text-gray-400">—</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
