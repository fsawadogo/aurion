"use client";

/**
 * /portal/admin/grounded-lab — Grounded Lab (descriptive vs grounded).
 *
 * ADMIN / EVAL_TEAM surface to VALIDATE grounded visual findings before they
 * ride live patient notes. Two ways in:
 *   • Pick a past session whose masked clip is still in S3, OR
 *   • Upload a video right here — it's ingested through the same admin
 *     video-import pipeline (masking + transcription), then the comparison
 *     runs on the resulting session automatically.
 * Either way the clip is replayed through the vision layer twice — strict
 * Descriptive vs Grounded — and the two finding sets read side by side, each
 * still cited to its frame.
 *
 * READ-ONLY comparison: the backend replay never writes a note version or
 * mutates the chart. The page is intentionally NOT gated on
 * `grounded_visual_findings_enabled` — it always runs both modes, so it works
 * whether the live flag is on or off (validate before flipping, re-validate
 * after). The UPLOAD path is gated on `video_import_enabled` (the admin
 * video-import endpoints 404 while that feature is dark), so it degrades to a
 * hint when import is off; picking an existing session always works.
 */

import {
  FlaskConical,
  Film,
  Play,
  Quote,
  ShieldCheck,
  TriangleAlert,
  UploadCloud,
} from "lucide-react";
import {
  ApiError,
  createAdminVideoImport,
  getAdminVideoImportStatus,
  getFusionCompareRun,
  getGroundedLabRun,
  getGroundedLabSessions,
  getModalityCompareRun,
  humanizeError,
  processAdminVideoImport,
  runFusionCompare,
  runGroundedLab,
  runModalityCompare,
} from "@/lib/api";
import { getPortalFeatureFlags } from "@/lib/portal-api";
import type {
  FusionCompareResult,
  FusionNote,
  GroundedLabFinding,
  GroundedLabPair,
  GroundedLabRunResponse,
  GroundedLabSessionItem,
  ModalityCompareResult,
} from "@/types";
import { useCallback, useEffect, useRef, useState } from "react";

// The run is async: a large frame set is captioned over minutes (past the ALB
// idle timeout), so we poll the job until it completes.
const POLL_INTERVAL_MS = 3000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import EmptyPanelState from "@/components/portal/EmptyPanelState";
import PageHeader from "@/components/portal/PageHeader";

const INPUT_CLS =
  "w-full rounded-aurion-md border border-hairline bg-white px-3 py-2 text-aurion-callout text-navy-800 focus:outline-none focus:ring-2 focus:ring-gold-300/40";

// Upload constraints — mirror the video-import surface so a clip accepted here
// is accepted by the backend presign.
const MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB
const ACCEPTED_VIDEO = ["video/mp4", "video/quicktime", "video/webm"];
const UPLOAD_SPECIALTIES = [
  "orthopedic_surgery",
  "plastic_surgery",
  "musculoskeletal",
  "emergency_medicine",
  "general",
];

function humanBytes(n: number): string {
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** Raw S3 PUT with upload progress. No Aurion bearer — the presign is the auth. */
function putWithProgress(
  url: string,
  file: File,
  onProgress: (pct: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader(
      "Content-Type",
      file.type || "application/octet-stream",
    );
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`upload_failed_${xhr.status}`));
    xhr.onerror = () => reject(new Error("upload_network_error"));
    xhr.send(file);
  });
}

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

// One note column in the Fusion A/B comparison: the note's sections, each with
// its claims. Conflict claims (surfaced audio/visual disagreements in Fusion B)
// are flagged amber.
function FusionNoteColumn({ note }: { note: FusionNote }) {
  const populated = note.sections.filter((s) => s.claims.length > 0);
  if (populated.length === 0) {
    return (
      <p className="px-4 py-3 text-aurion-micro italic text-navy-300">
        No populated sections.
      </p>
    );
  }
  return (
    <div className="divide-y divide-hairline">
      {populated.map((section) => (
        <div key={section.id} className="px-4 py-3">
          <p className="mb-1.5 text-aurion-micro font-semibold uppercase tracking-wide text-navy-500">
            {section.title || section.id}
          </p>
          <ul className="space-y-1.5">
            {section.claims.map((claim) => {
              const isConflict = claim.id.startsWith("conflict_");
              return (
                <li
                  key={claim.id}
                  className={`text-aurion-callout ${
                    isConflict ? "text-amber-800" : "text-navy-800"
                  }`}
                >
                  {isConflict && (
                    <TriangleAlert
                      className="mr-1 inline h-3 w-3"
                      aria-hidden="true"
                    />
                  )}
                  {claim.text}
                  {claim.source_type === "visual" && (
                    <span className="ml-1 text-aurion-micro text-navy-400">
                      · visual
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
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
  const tSpec = useTranslations("Specialties");
  const [sessions, setSessions] = useState<GroundedLabSessionItem[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Input source: an existing captured session, or a clip uploaded right here.
  const [source, setSource] = useState<"session" | "upload">("session");
  const [videoImportEnabled, setVideoImportEnabled] = useState(false);

  // Comparison modes share the input: "grounded" (descriptive vs grounded
  // captions), "fusion" (Fusion A vs B notes), "modality" (audio-only vs
  // visual-only vs merged notes), and "all" (run all three in one pass and
  // read them stacked).
  const [mode, setMode] = useState<
    "grounded" | "fusion" | "modality" | "all"
  >("grounded");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<GroundedLabRunResponse | null>(null);
  const [fusionResult, setFusionResult] = useState<FusionCompareResult | null>(
    null,
  );
  const [modalityResult, setModalityResult] =
    useState<ModalityCompareResult | null>(null);

  // Upload sub-flow state. `uploadPhase` drives the compact stepper; a prepared
  // clip hands its session_id straight into the comparison run.
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadSpecialty, setUploadSpecialty] = useState("general");
  const [uploadConsent, setUploadConsent] = useState(false);
  const [uploadPhase, setUploadPhase] = useState<
    "idle" | "uploading" | "processing"
  >("idle");
  const [uploadPct, setUploadPct] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);

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
    // Gate the upload option on the video-import feature. Best-effort: a fetch
    // failure just leaves the upload tab showing its "import is off" hint.
    try {
      const flags = await getPortalFeatureFlags();
      setVideoImportEnabled(!!flags.video_import_enabled);
    } catch {
      setVideoImportEnabled(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  // Monotonic run token: a re-run (or unmount) bumps it so an in-flight poll
  // loop from a superseded run never writes stale state.
  const runSeqRef = useRef(0);
  useEffect(() => () => {
    runSeqRef.current += 1;
  }, []);

  const onRun = useCallback(
    async (overrideSessionId?: string) => {
      const sid = overrideSessionId ?? selected;
      if (!sid) return;
      const seq = (runSeqRef.current += 1);
      const isCurrent = () => runSeqRef.current === seq;
      setRunning(true);
      setRunError(null);
      setResult(null);
      setFusionResult(null);
      setModalityResult(null);

      // Start one comparison and poll its job until done, writing its result as
      // soon as it lands. Self-contained (catches its own errors) so several can
      // run concurrently under Promise.all without one failure aborting another.
      const runOne = async (m: "grounded" | "fusion" | "modality") => {
        try {
          const started =
            m === "fusion"
              ? await runFusionCompare(sid)
              : m === "modality"
                ? await runModalityCompare(sid)
                : await runGroundedLab(sid);
          for (;;) {
            if (!isCurrent()) return;
            const status =
              m === "fusion"
                ? await getFusionCompareRun(started.job_id)
                : m === "modality"
                  ? await getModalityCompareRun(started.job_id)
                  : await getGroundedLabRun(started.job_id);
            if (!isCurrent()) return;
            if (status.status === "completed" && status.result) {
              if (m === "fusion") {
                setFusionResult(status.result as FusionCompareResult);
              } else if (m === "modality") {
                setModalityResult(status.result as ModalityCompareResult);
              } else {
                setResult(status.result as GroundedLabRunResponse);
              }
              return;
            }
            if (status.status === "failed") {
              setRunError(
                status.error === "no_media" ? t("noMedia") : t("runError"),
              );
              return;
            }
            await sleep(POLL_INTERVAL_MS);
          }
        } catch (e) {
          if (!isCurrent()) return;
          // 409 = the session's media was purged / never captured.
          if (e instanceof ApiError && e.status === 409) {
            setRunError(t("noMedia"));
          } else {
            setRunError(humanizeError(e, t("runError")));
          }
        }
      };

      const modesToRun: ("grounded" | "fusion" | "modality")[] =
        mode === "all" ? ["grounded", "fusion", "modality"] : [mode];
      try {
        await Promise.all(modesToRun.map(runOne));
      } finally {
        if (isCurrent()) setRunning(false);
      }
    },
    [selected, mode, t],
  );

  // Upload token: guards the ingest poll loop the same way runSeqRef guards the
  // comparison poll, so a superseded upload never flips state on a later one.
  const uploadSeqRef = useRef(0);
  useEffect(() => () => {
    uploadSeqRef.current += 1;
  }, []);

  const pickUploadFile = useCallback(
    (f: File | null) => {
      setUploadError(null);
      if (!f) return;
      if (!ACCEPTED_VIDEO.includes(f.type)) {
        setUploadError(t("uploadBadFormat"));
        return;
      }
      if (f.size === 0) {
        setUploadError(t("uploadEmpty"));
        return;
      }
      if (f.size > MAX_VIDEO_BYTES) {
        setUploadError(t("uploadTooLarge"));
        return;
      }
      setUploadFile(f);
    },
    [t],
  );

  // Upload a clip → ingest it through the admin video-import pipeline (masking
  // + transcription) → run the selected comparison on the resulting session.
  const onUploadAndCompare = useCallback(async () => {
    if (!uploadFile || !uploadConsent) return;
    const seq = (uploadSeqRef.current += 1);
    const isCurrent = () => uploadSeqRef.current === seq;
    setUploadError(null);
    setUploadPct(0);
    setUploadPhase("uploading");
    try {
      const created = await createAdminVideoImport({
        specialty: uploadSpecialty,
        encounter_type: "doctor_patient",
        output_language: "en",
        consent_attested: true,
        consent_method: "attested",
      });
      await putWithProgress(created.upload_url, uploadFile, (pct) => {
        if (isCurrent()) setUploadPct(pct);
      });
      if (!isCurrent()) return;
      setUploadPhase("processing");
      await processAdminVideoImport(created.session_id);
      // Poll the import until the session has masked media + a transcript.
      for (;;) {
        if (!isCurrent()) return;
        const s = await getAdminVideoImportStatus(created.session_id);
        if (!isCurrent()) return;
        if (s.status === "failed") {
          setUploadError(s.error_message || t("uploadError"));
          setUploadPhase("idle");
          return;
        }
        if (
          s.status === "completed" ||
          s.session_state === "AWAITING_REVIEW"
        ) {
          break;
        }
        await sleep(POLL_INTERVAL_MS);
      }
      if (!isCurrent()) return;
      // The import flips to AWAITING_REVIEW when the note is ready, but the
      // masked frames land in S3 (frames/{id}/) a moment LATER. Auto-running
      // the comparison the instant we see AWAITING_REVIEW therefore races the
      // frame writes and 409s with "no media" on a clip that is actually fine —
      // a manual re-run seconds later succeeds. Wait until the session reports
      // retrievable media before running: the sessions list's frame_count /
      // clip_count count the SAME S3 prefixes the run reads, so >0 is an exact
      // "frames are now listable" signal. Bounded so a genuinely empty import
      // still falls through and surfaces the proper "no media" message.
      let ready: GroundedLabSessionItem | null = null;
      for (let attempt = 0; attempt < 20; attempt++) {
        if (!isCurrent()) return;
        try {
          const list = await getGroundedLabSessions();
          const found = list.items.find(
            (s) => s.session_id === created.session_id,
          );
          if (found && (found.frame_count > 0 || found.clip_count > 0)) {
            ready = found;
            break;
          }
        } catch {
          // Transient list failure — keep waiting; the run below still guards.
        }
        await sleep(POLL_INTERVAL_MS);
      }
      if (!isCurrent()) return;
      // Surface the prepared clip in the session picker (with real media counts
      // when the readiness poll saw them; a light placeholder otherwise) and
      // select it.
      const item: GroundedLabSessionItem = ready ?? {
        session_id: created.session_id,
        physician_name: t("uploadedClipLabel"),
        started_at: new Date().toISOString(),
        specialty: uploadSpecialty,
        visit_type: null,
        state: "AWAITING_REVIEW",
        frame_count: 0,
        clip_count: 0,
      };
      setSessions((prev) => [
        item,
        ...prev.filter((p) => p.session_id !== created.session_id),
      ]);
      setSelected(created.session_id);
      setUploadPhase("idle");
      setUploadPct(0);
      // Run on the freshly-prepared clip. If media never showed up within the
      // wait window, run anyway so the proper "no media" message surfaces
      // instead of silently doing nothing.
      void onRun(created.session_id);
    } catch (e) {
      if (!isCurrent()) return;
      setUploadError(humanizeError(e, t("uploadError")));
      setUploadPhase("idle");
    }
  }, [uploadFile, uploadConsent, uploadSpecialty, onRun, t]);

  function sessionLabel(s: GroundedLabSessionItem): string {
    const when = s.started_at ? new Date(s.started_at).toLocaleString() : "";
    const media = `${s.frame_count}f · ${s.clip_count}c`;
    const spec = s.specialty ? ` · ${s.specialty}` : "";
    return `${s.physician_name} — ${when}${spec} (${media})`;
  }

  const uploadBusy = uploadPhase !== "idle";
  // In "all" mode each comparison renders the moment it finishes (the others
  // may still be polling); single-mode keeps the classic "show when the run is
  // done" behaviour so a re-run never flashes a stale result.
  const showResults = mode === "all" || !running;

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
        {/* Mode toggle: which comparison to run on the chosen input. "all"
            runs every comparison in one pass. Wraps on narrow screens. */}
        <div
          className="mb-4 inline-flex flex-wrap gap-0.5 rounded-aurion-md border border-hairline p-0.5"
          role="tablist"
          data-testid="grounded-lab-mode"
        >
          {(["grounded", "fusion", "modality", "all"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-[10px] px-3 py-1.5 text-aurion-micro font-medium transition-colors ${
                mode === m
                  ? "bg-navy-800 text-white"
                  : "text-navy-500 hover:text-navy-700"
              }`}
              data-testid={`grounded-lab-mode-${m}`}
            >
              {m === "grounded"
                ? t("modeGrounded")
                : m === "fusion"
                  ? t("modeFusion")
                  : m === "modality"
                    ? t("modeModality")
                    : t("modeAll")}
            </button>
          ))}
        </div>
        <p className="mb-3 text-aurion-micro text-navy-400">
          {mode === "grounded"
            ? t("modeGroundedHint")
            : mode === "fusion"
              ? t("modeFusionHint")
              : mode === "modality"
                ? t("modeModalityHint")
                : t("modeAllHint")}
        </p>

        {/* Source toggle: an existing session, or upload a clip right here. */}
        <div
          className="mb-4 inline-flex rounded-aurion-md border border-hairline p-0.5"
          role="tablist"
          data-testid="grounded-lab-source"
        >
          {(["session", "upload"] as const).map((s) => (
            <button
              key={s}
              type="button"
              role="tab"
              aria-selected={source === s}
              onClick={() => setSource(s)}
              disabled={uploadBusy}
              className={`rounded-[10px] px-3 py-1.5 text-aurion-micro font-medium transition-colors disabled:opacity-50 ${
                source === s
                  ? "bg-navy-800 text-white"
                  : "text-navy-500 hover:text-navy-700"
              }`}
              data-testid={`grounded-lab-source-${s}`}
            >
              {s === "session" ? t("sourceSession") : t("sourceUpload")}
            </button>
          ))}
        </div>

        {source === "session" ? (
          loading ? (
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
                onClick={() => void onRun()}
                loading={running}
                disabled={!selected || running}
                data-testid="grounded-lab-run-button"
              >
                <Play className="mr-1.5 h-4 w-4" aria-hidden="true" />
                {mode === "all" ? t("runAllButton") : t("runButton")}
              </Button>
            </div>
          )
        ) : !videoImportEnabled ? (
          <EmptyPanelState
            icon={<UploadCloud className="h-5 w-5" aria-hidden="true" />}
            title={t("uploadDisabledTitle")}
            hint={t("uploadDisabledBody")}
          />
        ) : (
          <div className="space-y-4" data-testid="grounded-lab-upload">
            <p className="text-aurion-micro text-navy-400">{t("sourceHint")}</p>

            <label
              className={
                "flex cursor-pointer flex-col items-center justify-center rounded-aurion-md border-2 border-dashed border-hairline px-6 py-8 text-center transition-colors hover:border-navy-300 " +
                (uploadBusy ? "pointer-events-none opacity-60" : "")
              }
            >
              <UploadCloud
                className="mb-2 h-7 w-7 text-navy-300"
                aria-hidden="true"
              />
              {uploadFile ? (
                <span className="text-aurion-callout font-medium text-navy-700">
                  <Film className="mr-1 inline h-4 w-4" aria-hidden="true" />
                  {uploadFile.name} · {humanBytes(uploadFile.size)}
                </span>
              ) : (
                <>
                  <span className="text-aurion-callout font-medium text-navy-700">
                    {t("uploadDropzone")}
                  </span>
                  <span className="mt-1 text-aurion-micro text-navy-400">
                    {t("uploadAccepted")}
                  </span>
                </>
              )}
              <input
                type="file"
                accept="video/mp4,video/quicktime,video/webm"
                className="hidden"
                disabled={uploadBusy}
                data-testid="grounded-lab-upload-input"
                onChange={(e) => {
                  pickUploadFile(e.target.files?.[0] ?? null);
                  e.target.value = "";
                }}
              />
            </label>

            <label className="block sm:max-w-xs">
              <span className="mb-1 block text-aurion-micro font-medium text-navy-500">
                {t("uploadSpecialty")}
              </span>
              <select
                className={INPUT_CLS}
                value={uploadSpecialty}
                disabled={uploadBusy}
                onChange={(e) => setUploadSpecialty(e.target.value)}
                data-testid="grounded-lab-upload-specialty"
              >
                {UPLOAD_SPECIALTIES.map((s) => (
                  <option key={s} value={s}>
                    {tSpec(s)}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex items-start gap-2 rounded-aurion-md border border-amber-200 bg-amber-50 px-4 py-3 text-aurion-callout text-amber-800">
              <ShieldCheck
                className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600"
                aria-hidden="true"
              />
              <span className="flex cursor-pointer items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={uploadConsent}
                  disabled={uploadBusy}
                  onChange={(e) => setUploadConsent(e.target.checked)}
                  data-testid="grounded-lab-upload-consent"
                />
                <span>{t("uploadConsentLabel")}</span>
              </span>
            </label>

            {uploadError && (
              <p
                className="rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
                role="alert"
                data-testid="grounded-lab-upload-error"
              >
                {uploadError}
              </p>
            )}

            {uploadPhase === "uploading" && (
              <div data-testid="grounded-lab-upload-progress">
                <div className="h-2 w-full overflow-hidden rounded-full bg-navy-50">
                  <div
                    className="h-full rounded-full bg-aurion-gold transition-all"
                    style={{ width: `${uploadPct}%` }}
                  />
                </div>
                <p className="mt-2 text-aurion-micro text-navy-400">
                  {t("uploadingLabel", { percent: uploadPct })}
                </p>
              </div>
            )}

            {uploadPhase === "processing" && (
              <div
                className="flex items-center gap-2 text-aurion-callout text-navy-500"
                data-testid="grounded-lab-upload-processing"
              >
                <span className="h-2 w-2 flex-shrink-0 rounded-full bg-aurion-gold animate-aurion-pulse" />
                {t("preparingLabel")}
              </div>
            )}

            <Button
              onClick={() => void onUploadAndCompare()}
              loading={uploadBusy}
              disabled={!uploadFile || !uploadConsent || uploadBusy}
              data-testid="grounded-lab-upload-button"
            >
              <Play className="mr-1.5 h-4 w-4" aria-hidden="true" />
              {t("uploadButton")}
            </Button>
          </div>
        )}

        <p className="mt-3 text-aurion-micro text-navy-400">
          {t("readOnlyNote")}
        </p>
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

      {running && !result && !fusionResult && !modalityResult && (
        <Card>
          <p className="mb-3 text-aurion-callout text-navy-500" data-testid="grounded-lab-running">
            {mode === "all" ? t("runningAllHint") : t("runningHint")}
          </p>
          <LoadingSkeleton lines={6} />
        </Card>
      )}

      {running &&
        mode === "all" &&
        (result || fusionResult || modalityResult) && (
          <div
            className="mb-4 flex items-center gap-2 rounded-aurion-md border border-hairline bg-navy-50/40 px-4 py-3 text-aurion-callout text-navy-500"
            data-testid="grounded-lab-running-more"
          >
            <span className="h-2 w-2 flex-shrink-0 rounded-full bg-aurion-gold animate-aurion-pulse" />
            {t("runningMoreHint")}
          </div>
        )}

      {modalityResult && showResults && (
        <div data-testid="grounded-lab-modality-result">
          <Card className="mb-4" title={t("modalitySummaryTitle")}>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statFrames")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {modalityResult.frame_count}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statSectionsAudio")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {modalityResult.sections_audio}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statSectionsVisual")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {modalityResult.sections_visual}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statSectionsMerged")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {modalityResult.sections_merged}
                </dd>
              </div>
            </dl>
          </Card>

          <Card noPadding>
            <div className="grid grid-cols-3 border-b border-hairline bg-navy-50/40 text-aurion-micro font-semibold uppercase tracking-wide text-navy-500">
              <div className="px-4 py-2">{t("colAudioOnly")}</div>
              <div className="px-4 py-2">{t("colVisualOnly")}</div>
              <div className="px-4 py-2">{t("colMerged")}</div>
            </div>
            <div className="grid grid-cols-3">
              <div>
                <FusionNoteColumn note={modalityResult.note_audio} />
              </div>
              <div className="border-l border-hairline">
                {modalityResult.note_visual ? (
                  <FusionNoteColumn note={modalityResult.note_visual} />
                ) : (
                  <p className="px-4 py-3 text-aurion-micro italic text-navy-300">
                    {t("noVisualNote")}
                  </p>
                )}
              </div>
              <div className="border-l border-hairline">
                <FusionNoteColumn note={modalityResult.note_merged} />
              </div>
            </div>
          </Card>
        </div>
      )}

      {result && showResults && (
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

      {fusionResult && showResults && (
        <div data-testid="grounded-lab-fusion-result">
          <Card className="mb-4" title={t("fusionSummaryTitle")}>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statFrames")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {fusionResult.frame_count}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statSectionsA")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {fusionResult.sections_a}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statSectionsB")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {fusionResult.sections_b}
                </dd>
              </div>
              <div>
                <dt className="text-aurion-micro text-navy-400">
                  {t("statConflictsB")}
                </dt>
                <dd className="text-aurion-callout font-semibold text-navy-800">
                  {fusionResult.conflicts_b}
                </dd>
              </div>
            </dl>
          </Card>

          <Card noPadding>
            <div className="grid grid-cols-2 border-b border-hairline bg-navy-50/40 text-aurion-micro font-semibold uppercase tracking-wide text-navy-500">
              <div className="px-4 py-2">{t("colFusionA")}</div>
              <div className="px-4 py-2">{t("colFusionB")}</div>
            </div>
            <div className="grid grid-cols-2">
              <div>
                <FusionNoteColumn note={fusionResult.note_a} />
              </div>
              <div className="border-l border-hairline">
                <FusionNoteColumn note={fusionResult.note_b} />
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
