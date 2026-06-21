"use client";

/**
 * Encounter-video upload (VID-05).
 *
 * Phased flow: form → uploading → processing → (redirect to the existing
 * note-review screen). Matches the backend's single presigned-PUT,
 * clinician-only `/me/video-imports` surface (gated behind
 * `video_import_enabled` — every call 404s while the feature is dark).
 */

import { Film, ShieldCheck, UploadCloud } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import PageHeader from "@/components/portal/PageHeader";
import {
  createAdminVideoImport,
  getAdminVideoImportStatus,
  processAdminVideoImport,
} from "@/lib/api";
import {
  abortVideoImportMultipart,
  completeVideoImportMultipart,
  createVideoImport,
  getVideoImportStatus,
  processVideoImport,
  startVideoImportMultipart,
  type VideoImportStatus,
} from "@/lib/portal-api";

const MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB
// Above this, use S3 multipart (resumable per-part) instead of a single PUT.
// Multipart is wired on the clinician (/me) surface only.
const MULTIPART_THRESHOLD = 100 * 1024 * 1024; // 100 MB
const ACCEPTED = ["video/mp4", "video/quicktime", "video/webm"];
const SPECIALTIES = [
  "orthopedic_surgery",
  "plastic_surgery",
  "musculoskeletal",
  "emergency_medicine",
  "general",
];
// Backend-canonical encounter types (the `team_patient` option was removed).
const ENCOUNTER_TYPES = ["doctor_patient", "doctor_team_patient"];
const POLL_MS = 4000;

type Phase = "form" | "uploading" | "processing" | "error";

// Stepper stages, mapped from the backend job status + session state.
const STAGES = [
  "uploading",
  "extractingAudio",
  "transcribing",
  "maskingFrames",
  "ready",
] as const;

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
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
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

/** PUT one multipart part; resolves the part's S3 ETag (CORS exposes it). */
function putPart(
  url: string,
  blob: Blob,
  onLoaded: (loaded: number) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onLoaded(e.loaded);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const etag = xhr.getResponseHeader("ETag");
        etag ? resolve(etag) : reject(new Error("missing_etag"));
      } else {
        reject(new Error(`part_failed_${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("part_network_error"));
    xhr.send(blob);
  });
}

/** S3 multipart upload (clinician surface): slice → PUT each part → complete.
 *  Sequential for robustness; aborts the S3 upload if a part fails. */
async function uploadMultipart(
  sessionId: string,
  file: File,
  onProgress: (pct: number) => void,
): Promise<void> {
  const mp = await startVideoImportMultipart(sessionId, file.size);
  const results: { part_number: number; etag: string }[] = [];
  let baseLoaded = 0;
  try {
    for (const part of mp.parts) {
      const start = (part.part_number - 1) * mp.part_size;
      const blob = file.slice(start, Math.min(start + mp.part_size, file.size));
      const etag = await putPart(part.url, blob, (loaded) =>
        onProgress(Math.round(((baseLoaded + loaded) / file.size) * 100)),
      );
      baseLoaded += blob.size;
      results.push({ part_number: part.part_number, etag });
    }
  } catch (e) {
    await abortVideoImportMultipart(sessionId, mp.upload_id).catch(() => {});
    throw e;
  }
  await completeVideoImportMultipart(sessionId, mp.upload_id, results);
}

interface VideoImportClientProps {
  /** "clinician" (default) → /me/video-imports + redirect to My Notes.
   *  "admin" → /admin/video-imports (eval/admin) + redirect to /sessions. */
  surface?: "clinician" | "admin";
}

export default function VideoImportClient({
  surface = "clinician",
}: VideoImportClientProps) {
  const t = useTranslations("VideoImport");
  const tSpec = useTranslations("Specialties");

  const api =
    surface === "admin"
      ? {
          create: createAdminVideoImport,
          process: processAdminVideoImport,
          status: getAdminVideoImportStatus,
        }
      : {
          create: createVideoImport,
          process: processVideoImport,
          status: getVideoImportStatus,
        };
  // Admin/eval land on the full note review (the Eval interface shows the
  // masked transcript + per-claim text); clinicians use their own review.
  const reviewBase = surface === "admin" ? "/eval" : "/portal/notes";

  const [file, setFile] = useState<File | null>(null);
  const [specialty, setSpecialty] = useState("general");
  const [encounterType, setEncounterType] = useState("doctor_patient");
  const [language, setLanguage] = useState("en");
  const [consent, setConsent] = useState(false);

  const [phase, setPhase] = useState<Phase>("form");
  const [uploadPct, setUploadPct] = useState(0);
  const [stageIndex, setStageIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const dragRef = useRef(false);
  const [, forceDrag] = useState(0);

  const pickFile = useCallback((f: File | null) => {
    setError(null);
    if (!f) return;
    if (!ACCEPTED.includes(f.type)) {
      setError(t("errors.badFormat"));
      return;
    }
    if (f.size === 0) {
      setError(t("errors.empty"));
      return;
    }
    if (f.size > MAX_VIDEO_BYTES) {
      setError(t("errors.tooLarge"));
      return;
    }
    setFile(f);
  }, [t]);

  const canSubmit = file !== null && consent && phase === "form";

  function mapStage(s: VideoImportStatus): number {
    if (s.status === "completed" || s.session_state === "AWAITING_REVIEW")
      return STAGES.indexOf("ready");
    if (s.frames_extracted > 0 || s.frames_dropped > 0)
      return STAGES.indexOf("maskingFrames");
    if (s.session_state === "PROCESSING_STAGE1")
      return STAGES.indexOf("transcribing");
    return STAGES.indexOf("extractingAudio");
  }

  async function poll(sessionId: string): Promise<void> {
    try {
      const s = await api.status(sessionId);
      if (s.status === "failed") {
        setError(s.error_message || t("errors.processingFailed"));
        setPhase("error");
        return;
      }
      setStageIndex(mapStage(s));
      if (s.status === "completed" || s.session_state === "AWAITING_REVIEW") {
        // Static-export: hard-navigate to the dynamic note-review route.
        window.location.href = `${reviewBase}/${sessionId}`;
        return;
      }
      window.setTimeout(() => void poll(sessionId), POLL_MS);
    } catch {
      window.setTimeout(() => void poll(sessionId), POLL_MS);
    }
  }

  async function start() {
    if (!file) return;
    setPhase("uploading");
    setError(null);
    setUploadPct(0);
    try {
      const created = await api.create({
        specialty,
        encounter_type: encounterType,
        output_language: language,
        consent_attested: true,
        consent_method: "attested",
      });
      // Large clinician uploads use resumable S3 multipart; everything else
      // (and the admin surface, which has no /me multipart route) uses the
      // single presigned PUT.
      if (surface === "clinician" && file.size > MULTIPART_THRESHOLD) {
        await uploadMultipart(created.session_id, file, setUploadPct);
      } else {
        await putWithProgress(created.upload_url, file, setUploadPct);
      }
      setPhase("processing");
      setStageIndex(0);
      await api.process(created.session_id);
      void poll(created.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errors.uploadFailed"));
      setPhase("error");
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
      <p className="mb-6 text-sm text-gray-500">{t("description")}</p>

      {phase === "form" && (
        <div className="space-y-4">
          <Card>
            <label
              onDragOver={(e) => {
                e.preventDefault();
                if (!dragRef.current) { dragRef.current = true; forceDrag((n) => n + 1); }
              }}
              onDragLeave={() => { dragRef.current = false; forceDrag((n) => n + 1); }}
              onDrop={(e) => {
                e.preventDefault();
                dragRef.current = false; forceDrag((n) => n + 1);
                pickFile(e.dataTransfer.files?.[0] ?? null);
              }}
              className={
                "flex cursor-pointer flex-col items-center justify-center rounded-aurion-md border-2 border-dashed px-6 py-10 text-center transition-colors " +
                (dragRef.current
                  ? "border-aurion-gold bg-gold-50"
                  : "border-gray-300 hover:border-gray-400")
              }
            >
              <UploadCloud className="mb-2 h-8 w-8 text-gray-400" />
              {file ? (
                <span className="text-sm font-medium text-navy-700">
                  <Film className="mr-1 inline h-4 w-4" />
                  {file.name} · {humanBytes(file.size)}
                </span>
              ) : (
                <>
                  <span className="text-sm font-medium text-navy-700">
                    {t("dropzone.prompt")}
                  </span>
                  <span className="mt-1 text-xs text-gray-400">
                    {t("dropzone.accepted")}
                  </span>
                </>
              )}
              <input
                type="file"
                accept="video/mp4,video/quicktime,video/webm"
                className="hidden"
                onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
              />
            </label>
          </Card>

          <Card title={t("form.title")}>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-navy-700">
                  {t("form.specialty")}
                </span>
                <select
                  className="form-input"
                  value={specialty}
                  onChange={(e) => setSpecialty(e.target.value)}
                >
                  {SPECIALTIES.map((s) => (
                    <option key={s} value={s}>{tSpec(s)}</option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-navy-700">
                  {t("form.encounterType")}
                </span>
                <select
                  className="form-input"
                  value={encounterType}
                  onChange={(e) => setEncounterType(e.target.value)}
                >
                  {ENCOUNTER_TYPES.map((v) => (
                    <option key={v} value={v}>{t(`form.encounter.${v}`)}</option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-navy-700">
                  {t("form.language")}
                </span>
                <select
                  className="form-input"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  <option value="en">{t("form.langEn")}</option>
                  <option value="fr">{t("form.langFr")}</option>
                </select>
              </label>
            </div>
          </Card>

          <div className="flex items-start gap-2 rounded-aurion-md border border-amber-200 bg-amber-50 px-4 py-3">
            <ShieldCheck className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" />
            <label className="flex cursor-pointer items-start gap-2 text-sm text-amber-800">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              <span>{t("consent.attestationLabel")}</span>
            </label>
          </div>

          {error && (
            <p className="rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </p>
          )}

          <Button
            variant="primary"
            disabled={!canSubmit}
            onClick={() => void start()}
          >
            {t("form.submit")}
          </Button>
        </div>
      )}

      {phase === "uploading" && (
        <Card title={t("upload.title")}>
          <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
            <div
              className="h-full rounded-full bg-aurion-gold transition-all"
              style={{ width: `${uploadPct}%` }}
            />
          </div>
          <p className="mt-2 text-sm text-gray-500">
            {t("upload.progress", { percent: uploadPct })}
          </p>
        </Card>
      )}

      {phase === "processing" && (
        <Card title={t("processing.title")}>
          <ol className="space-y-2">
            {STAGES.map((stage, i) => (
              <li
                key={stage}
                className={
                  "flex items-center gap-2 text-sm " +
                  (i < stageIndex
                    ? "text-emerald-600"
                    : i === stageIndex
                      ? "font-medium text-navy-700"
                      : "text-gray-400")
                }
              >
                <span
                  className={
                    "h-2 w-2 rounded-full " +
                    (i <= stageIndex ? "bg-aurion-gold" : "bg-gray-300")
                  }
                />
                {t(`stages.${stage}`)}
              </li>
            ))}
          </ol>
          <p className="mt-4 text-xs text-gray-400">{t("processing.leaveSafe")}</p>
        </Card>
      )}

      {phase === "error" && (
        <Card title={t("errors.title")}>
          <p className="text-sm text-red-700">{error}</p>
          <Button
            variant="secondary"
            className="mt-4"
            onClick={() => { setPhase("form"); setError(null); }}
          >
            {t("errors.retry")}
          </Button>
        </Card>
      )}
    </div>
  );
}
