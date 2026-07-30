"use client";

/**
 * /portal/admin/grounded-lab — Grounded Lab (descriptive vs grounded).
 *
 * ADMIN / EVAL_TEAM surface to VALIDATE grounded visual findings before they
 * ride live patient notes. Pick a past session whose masked clip is still in
 * S3, replay it through the vision layer twice — strict Descriptive vs Grounded
 * — and read the two finding sets side by side, each still cited to its frame.
 *
 * READ-ONLY: the backend replay never writes a note version or mutates the
 * chart. The page is intentionally NOT gated on
 * `grounded_visual_findings_enabled` — it always runs both modes, so it works
 * whether the live flag is on or off (validate before flipping, re-validate
 * after).
 */

import { FlaskConical, Play, Quote, TriangleAlert } from "lucide-react";
import {
  ApiError,
  getGroundedLabSessions,
  humanizeError,
  runGroundedLab,
} from "@/lib/api";
import type {
  GroundedLabFinding,
  GroundedLabPair,
  GroundedLabRunResponse,
  GroundedLabSessionItem,
} from "@/types";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import EmptyPanelState from "@/components/portal/EmptyPanelState";
import PageHeader from "@/components/portal/PageHeader";

const INPUT_CLS =
  "w-full rounded-aurion-md border border-hairline bg-white px-3 py-2 text-aurion-callout text-navy-800 focus:outline-none focus:ring-2 focus:ring-gold-300/40";

function confidenceVariant(
  c: string,
): "success" | "warning" | "error" | "neutral" {
  if (c === "high") return "success";
  if (c === "medium") return "warning";
  if (c === "low") return "error";
  return "neutral";
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function FindingCell({
  finding,
  emptyLabel,
  showCitation,
  frameId,
}: {
  finding: GroundedLabFinding | null;
  emptyLabel: string;
  showCitation: boolean;
  frameId: string;
}) {
  if (!finding) {
    return (
      <p className="text-aurion-micro italic text-navy-300">{emptyLabel}</p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-aurion-callout text-navy-800">{finding.text}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={confidenceVariant(finding.confidence)} dot>
          {finding.confidence}
        </Badge>
        {finding.conflict_flag ? (
          <Badge variant="warning">
            <TriangleAlert className="mr-1 h-3 w-3" aria-hidden="true" />
            {finding.integration_status}
          </Badge>
        ) : (
          <Badge variant="neutral">{finding.integration_status}</Badge>
        )}
        {showCitation && (
          <span className="inline-flex items-center gap-1 text-aurion-micro text-navy-400">
            <Quote className="h-3 w-3" aria-hidden="true" />
            {frameId}
          </span>
        )}
      </div>
    </div>
  );
}

export default function GroundedLabPage() {
  const t = useTranslations("AdminGroundedLab");
  const [sessions, setSessions] = useState<GroundedLabSessionItem[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<GroundedLabRunResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getGroundedLabSessions();
      setSessions(res.items);
      // Default the picker to the newest session that still has media.
      const firstWithMedia = res.items.find(
        (s) => s.frame_count > 0 || s.clip_count > 0,
      );
      if (firstWithMedia) setSelected(firstWithMedia.session_id);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const onRun = useCallback(async () => {
    if (!selected) return;
    setRunning(true);
    setRunError(null);
    setResult(null);
    try {
      setResult(await runGroundedLab(selected));
    } catch (e) {
      // 409 = the session's media was purged / never captured.
      if (e instanceof ApiError && e.status === 409) {
        setRunError(t("noMedia"));
      } else {
        setRunError(humanizeError(e, t("runError")));
      }
    } finally {
      setRunning(false);
    }
  }, [selected, t]);

  function sessionLabel(s: GroundedLabSessionItem): string {
    const when = s.started_at ? new Date(s.started_at).toLocaleString() : "";
    const media = `${s.frame_count}f · ${s.clip_count}c`;
    const spec = s.specialty ? ` · ${s.specialty}` : "";
    return `${s.physician_name} — ${when}${spec} (${media})`;
  }

  return (
    <div className="aurion-page-padded" data-testid="grounded-lab-page">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
      />

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
          data-testid="grounded-lab-error"
        >
          {error}
        </div>
      )}

      <Card className="mb-5" title={t("pickerTitle")}>
        {loading ? (
          <LoadingSkeleton lines={3} />
        ) : sessions.length === 0 ? (
          <EmptyPanelState
            icon={<FlaskConical className="h-5 w-5" aria-hidden="true" />}
            title={t("noSessionsTitle")}
            hint={t("noSessionsBody")}
          />
        ) : (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="flex-1">
              <span className="mb-1 block text-aurion-micro font-medium text-navy-500">
                {t("sessionLabel")}
              </span>
              <select
                className={INPUT_CLS}
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                data-testid="grounded-lab-session-select"
              >
                {sessions.map((s) => (
                  <option key={s.session_id} value={s.session_id}>
                    {sessionLabel(s)}
                  </option>
                ))}
              </select>
            </label>
            <Button
              onClick={onRun}
              loading={running}
              disabled={!selected || running}
              data-testid="grounded-lab-run-button"
            >
              <Play className="mr-1.5 h-4 w-4" aria-hidden="true" />
              {t("runButton")}
            </Button>
          </div>
        )}
        <p className="mt-3 text-aurion-micro text-navy-400">{t("readOnlyNote")}</p>
      </Card>

      {runError && (
        <div
          className="mb-4 rounded-aurion-md border border-amber-200 bg-amber-50 px-4 py-3 text-aurion-callout text-amber-800"
          role="alert"
          data-testid="grounded-lab-run-error"
        >
          {runError}
        </div>
      )}

      {running && (
        <Card>
          <LoadingSkeleton lines={6} />
        </Card>
      )}

      {result && !running && (
        <div data-testid="grounded-lab-result">
          <Card
            className="mb-4"
            title={t("summaryTitle")}
            action={
              result.provider_used ? (
                <Badge variant="brand">{result.provider_used}</Badge>
              ) : undefined
            }
          >
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statFrames")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {result.frame_count}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statDescriptive")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {result.descriptive_findings}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statGrounded")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {result.grounded_findings}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statMode")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {result.evidence_mode}
                </dd>
              </div>
            </dl>
          </Card>

          {result.pairs.length === 0 ? (
            <Card>
              <EmptyPanelState
                icon={<FlaskConical className="h-5 w-5" aria-hidden="true" />}
                title={t("noFindingsTitle")}
                hint={t("noFindingsBody")}
              />
            </Card>
          ) : (
            <Card noPadding>
              {/* Column headers */}
              <div className="grid grid-cols-[7rem_1fr_1fr] border-b border-hairline bg-navy-50/40 text-aurion-micro font-semibold uppercase tracking-wide text-navy-500">
                <div className="px-4 py-2">{t("colFrame")}</div>
                <div className="px-4 py-2">{t("colDescriptive")}</div>
                <div className="px-4 py-2">{t("colGrounded")}</div>
              </div>
              <ul className="divide-y divide-hairline">
                {result.pairs.map((pair: GroundedLabPair) => (
                  <li
                    key={pair.frame_id}
                    className="grid grid-cols-[7rem_1fr_1fr]"
                  >
                    <div className="px-4 py-3">
                      <p className="text-aurion-callout font-medium text-navy-700">
                        {formatTimestamp(pair.timestamp_ms)}
                      </p>
                      <p className="mt-0.5 text-aurion-micro text-navy-400">
                        {pair.evidence_kind}
                      </p>
                      <p className="text-aurion-micro text-navy-400">
                        {pair.audio_anchor_id}
                      </p>
                    </div>
                    <div className="border-l border-hairline px-4 py-3">
                      <FindingCell
                        finding={pair.descriptive}
                        emptyLabel={t("noFinding")}
                        showCitation={false}
                        frameId={pair.frame_id}
                      />
                    </div>
                    <div className="border-l border-hairline px-4 py-3">
                      <FindingCell
                        finding={pair.grounded}
                        emptyLabel={t("noFinding")}
                        showCitation
                        frameId={pair.frame_id}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
