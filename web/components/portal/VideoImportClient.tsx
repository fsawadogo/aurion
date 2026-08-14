"use client";

/**
 * Encounter-video upload (VID-05).
 *
 * Phased flow: form → uploading → processing → (redirect to the existing
 * note-review screen). Matches the backend's single presigned-PUT,
 * clinician-only `/me/video-imports` surface (gated behind
 * `video_import_enabled` — every call 404s while the feature is dark).
 */

import {
  ArrowDown,
  ArrowUp,
  FileText,
  Film,
  ShieldCheck,
  UploadCloud,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import PageHeader from "@/components/portal/PageHeader";
import {
  BUILT_IN_TEMPLATE_KEYS,
  MAX_CONTEXT_DESCRIPTION_LEN,
} from "@/components/portal/VisitTypeContextsEditor";
import {
  createAdminVideoImport,
  getAdminVideoImportStatus,
  humanizeError,
  processAdminVideoImport,
} from "@/lib/api";
import {
  abortVideoImportMultipart,
  completeVideoImportMultipart,
  createVideoImport,
  getMyProfile,
  getPortalFeatureFlags,
  getVideoImportStatus,
  listMyCustomTemplates,
  processVideoImport,
  cancelVideoImport,
  discardSession,
  startVideoImportMultipart,
  type VideoImportStatus,
} from "@/lib/portal-api";
import { shouldStopPolling } from "@/lib/poll";
import type {
  CustomTemplate,
  PhysicianProfile,
  VisitTypeContext,
} from "@/types";

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

// Built-in visit-type labels (mirrors VisitTypesTab). Custom labels fall
// through to the raw key, which IS the clinician's own text.
const VISIT_TYPE_LABELS: Record<string, string> = {
  new_patient: "New patient",
  follow_up: "Follow-up",
  pre_op: "Pre-op",
  post_op: "Post-op",
};
function humanizeVisitType(key: string): string {
  return VISIT_TYPE_LABELS[key] ?? key;
}
const POLL_MS = 4000;

type Phase = "form" | "uploading" | "processing" | "error" | "cancelled";

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
  // Reuse the profile editor's localized built-in template names so the
  // resolved-template line reads exactly as it does in the clinician's profile.
  const tTemplates = useTranslations("Profile.contexts.templates");

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

  // Source of truth for chosen clips. In single-file mode (flag off) this
  // holds at most one file; the single-file UI derives `file` from files[0]
  // so its render path is byte-identical to before. In multi-clip mode the
  // ordered list is the upload order the backend stitches into one note.
  const [files, setFiles] = useState<File[]>([]);
  const file = files[0] ?? null;
  const [multiClipEnabled, setMultiClipEnabled] = useState(false);
  // Admin/eval surface keeps a specialty picker (no personal profile). The
  // clinician surface takes specialty from the profile — TE-4d: specialty is
  // a profile property, not a per-upload choice.
  const [specialty, setSpecialty] = useState("general");
  const [profile, setProfile] = useState<PhysicianProfile | null>(null);
  // TE-4d: visit type + context drive template resolution the same way iOS
  // does. Empty = no specific visit context → the specialty default.
  const [visitType, setVisitType] = useState("");
  const [contextId, setContextId] = useState("");
  const [encounterType, setEncounterType] = useState("doctor_patient");
  const [language, setLanguage] = useState("en");
  const [consent, setConsent] = useState(false);
  const [customTemplates, setCustomTemplates] = useState<CustomTemplate[]>([]);
  // Free-text encounter context (iOS `encounter_context`). Prefilled from a
  // picked context's saved note; the clinician can add to it before upload.
  const [contextNote, setContextNote] = useState("");

  const [phase, setPhase] = useState<Phase>("form");
  // Elapsed processing time. A stepper alone cannot distinguish "this stage
  // is slow" from "this page is dead"; a ticking clock can.
  const [elapsedSec, setElapsedSec] = useState(0);
  const [uploadPct, setUploadPct] = useState(0);
  const [stageIndex, setStageIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // Cancel (wedged-import escape hatch). The session id is needed after the
  // upload returns so the clinician can act on the job; `cancelledRef` stops
  // the poll loop, which is otherwise the only thing keeping the spinner alive.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const cancelledRef = useRef(false);
  // Whether /process would actually succeed again — the server decides, so the
  // UI never offers a Retry that 409s. Null until a cancel returns.
  const [retryable, setRetryable] = useState<boolean | null>(null);
  const [retryBlockedReason, setRetryBlockedReason] = useState<string | null>(null);
  const dragRef = useRef(false);
  const [, forceDrag] = useState(0);

  // Tick only while processing; reset on entry so a retry starts from zero.
  useEffect(() => {
    if (phase !== "processing") {
      setElapsedSec(0);
      return;
    }
    const id = window.setInterval(() => setElapsedSec((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [phase]);

  const elapsedLabel =
    phase === "processing" && elapsedSec > 0
      ? `${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, "0")}`
      : null;

  // Clinician-only: list the clinician's custom templates so they can apply one
  // (its structure + AI instructions) to the imported note. Admin/eval uploads
  // use the specialty default. Best-effort — a fetch failure just hides the picker.
  useEffect(() => {
    if (surface !== "clinician") return;
    let alive = true;
    listMyCustomTemplates()
      .then((rows) => {
        if (alive) setCustomTemplates(rows);
      })
      .catch(() => {});
    // TE-4d: the clinician's profile drives specialty + the visit-type→context
    // map. Best-effort — a fetch failure falls back to the specialty default
    // (no visit-context picker, the pre-TE-4d behaviour).
    getMyProfile()
      .then((p) => {
        if (alive) setProfile(p);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [surface]);

  // Multi-clip is a clinician-surface capability (the admin/eval surface has
  // no per-clip presign fan-out). Best-effort: a fetch failure leaves the
  // classic single-file UI in place.
  useEffect(() => {
    // Fetch on BOTH surfaces — /me/feature-flags is available to any role, and
    // the admin/eval upload page (/portal/admin/upload) must support multi-clip
    // too. (The earlier `surface !== "clinician"` guard silently disabled the
    // multi-file UI for admins, who land on the admin surface via the sidebar.)
    let alive = true;
    getPortalFeatureFlags()
      .then((flags) => {
        if (alive) setMultiClipEnabled(!!flags.multi_clip_import_enabled);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  /** Validate one candidate file; returns it when acceptable, else sets the
   *  matching error and returns null. */
  const validateFile = useCallback(
    (f: File): File | null => {
      if (!ACCEPTED.includes(f.type)) {
        setError(t("errors.badFormat"));
        return null;
      }
      if (f.size === 0) {
        setError(t("errors.empty"));
        return null;
      }
      if (f.size > MAX_VIDEO_BYTES) {
        setError(t("errors.tooLarge"));
        return null;
      }
      return f;
    },
    [t],
  );

  // Single-file path (flag off): replaces the selection, unchanged behaviour.
  const pickFile = useCallback(
    (f: File | null) => {
      setError(null);
      if (!f) return;
      const valid = validateFile(f);
      if (valid) setFiles([valid]);
    },
    [validateFile],
  );

  // Multi-clip path (flag on): append every valid dropped/selected file to the
  // ordered list; the first bad file surfaces its error and the rest are still
  // added.
  const addFiles = useCallback(
    (list: FileList | File[] | null) => {
      setError(null);
      if (!list) return;
      const incoming = Array.from(list);
      if (incoming.length === 0) return;
      const valid: File[] = [];
      for (const f of incoming) {
        const ok = validateFile(f);
        if (ok) valid.push(ok);
      }
      if (valid.length > 0) setFiles((prev) => [...prev, ...valid]);
    },
    [validateFile],
  );

  const moveClip = useCallback((index: number, delta: number) => {
    setFiles((prev) => {
      const target = index + delta;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }, []);

  const removeClip = useCallback((index: number) => {
    setError(null);
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const canSubmit = files.length > 0 && consent && phase === "form";

  // The saved context the clinician picked (if any) — drives the resolved-
  // template line and prefilled the context box. Only the clinician surface
  // has a visit-type→context map.
  const selectedContext: VisitTypeContext | null =
    visitType && contextId
      ? profile?.contexts_per_visit_type[visitType]?.find(
          (c) => c.id === contextId,
        ) ?? null
      : null;

  // Localized name of the template a picked context pins EXPLICITLY: a custom
  // ref → its display name; a built-in key → the shared localized label.
  // Returns null when the context inherits (no explicit binding) — the web
  // can't predict the server's clinician/org-default resolution, so we don't
  // assert a template name we might get wrong.
  const resolvedTemplateName: string | null = (() => {
    if (!selectedContext) return null;
    if (selectedContext.template_ref) {
      return (
        customTemplates.find((c) => c.id === selectedContext.template_ref)
          ?.display_name ?? t("form.templateCustomFallback")
      );
    }
    if (selectedContext.template_key) {
      return (BUILT_IN_TEMPLATE_KEYS as readonly string[]).includes(
        selectedContext.template_key,
      )
        ? tTemplates(selectedContext.template_key)
        : selectedContext.template_key;
    }
    return null;
  })();

  function mapStage(s: VideoImportStatus): number {
    if (s.status === "completed" || s.session_state === "AWAITING_REVIEW")
      return STAGES.indexOf("ready");
    if (s.frames_extracted > 0 || s.frames_dropped > 0)
      return STAGES.indexOf("maskingFrames");
    if (s.session_state === "PROCESSING_STAGE1")
      return STAGES.indexOf("transcribing");
    return STAGES.indexOf("extractingAudio");
  }

  async function poll(sessionId: string, errorCount = 0): Promise<void> {
    // A cancel already moved the UI on; a late poll must not drag it back into
    // "processing" or overwrite the cancelled card with a stale status.
    if (cancelledRef.current) return;
    try {
      const s = await api.status(sessionId);
      if (cancelledRef.current) return;
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
      // Success → reset the consecutive-error count (default arg).
      window.setTimeout(() => void poll(sessionId), POLL_MS);
    } catch {
      // Persistent failure (status endpoint unreachable / refresh failed) →
      // stop instead of spinning forever; processing may still finish, so point
      // the clinician at My Notes rather than showing a hard processing error.
      if (shouldStopPolling(errorCount + 1)) {
        setError(t("errors.lostContact"));
        setPhase("error");
        return;
      }
      window.setTimeout(() => void poll(sessionId, errorCount + 1), POLL_MS);
    }
  }

  /** Stop waiting on a wedged import.
   *
   *  Only the clinician surface has the route; admin/eval keeps the old
   *  behaviour. Marks the job failed server-side so it stops occupying the
   *  session, then shows what is actually possible next — the server decides
   *  retryability, because once processing has begun the raw clip is purged
   *  and there is nothing left to re-process.
   */
  async function onCancelProcessing() {
    if (!sessionId) return;
    setCancelling(true);
    setError(null);
    try {
      const res = await cancelVideoImport(sessionId);
      cancelledRef.current = true;
      setRetryable(res.retryable);
      setRetryBlockedReason(res.retry_blocked_reason);
      setPhase("cancelled");
    } catch (e) {
      setError(humanizeError(e, t("errors.cancelFailed")));
      setPhase("error");
    } finally {
      setCancelling(false);
    }
  }

  /** Re-run processing on the SAME uploaded clip. Only offered when the server
   *  said `retryable`, i.e. the clip is still in S3 and the session never left
   *  CONSENT_PENDING. */
  async function onRetryProcessing() {
    if (!sessionId) return;
    setError(null);
    setPhase("processing");
    setStageIndex(0);
    cancelledRef.current = false;
    try {
      await api.process(sessionId);
      void poll(sessionId);
    } catch (e) {
      setError(humanizeError(e, t("errors.processingFailed")));
      setPhase("error");
    }
  }

  /** Discard the wedged session and return to an empty form.
   *
   *  Best-effort: if the delete fails we still reset, because leaving the
   *  clinician staring at a dead session is worse than an orphaned row (which
   *  the audit trail still accounts for). */
  async function onStartOver() {
    if (sessionId) {
      try {
        await discardSession(sessionId);
      } catch {
        // Intentionally ignored — see above.
      }
    }
    cancelledRef.current = false;
    setSessionId(null);
    setRetryable(null);
    setRetryBlockedReason(null);
    setError(null);
    setFiles([]);
    setConsent(false);
    setUploadPct(0);
    setStageIndex(0);
    setPhase("form");
  }

  async function start() {
    if (files.length === 0) return;
    const multi = files.length > 1;
    setPhase("uploading");
    setError(null);
    setUploadPct(0);
    try {
      const created = await api.create({
        // Clinician: specialty comes from the profile, not a picker. Admin/eval
        // keeps its picker. Falls back to the picker value if the profile
        // hasn't loaded.
        specialty:
          surface === "clinician"
            ? profile?.primary_specialty ?? specialty
            : specialty,
        encounter_type: encounterType,
        output_language: language,
        // TE-4d: send the visit type + context so the backend resolves the
        // mapped template via the same resolver iOS uses. Omitted when nothing
        // is picked → the specialty default. The template now comes from the
        // context (no standalone template picker) — no custom_template_id.
        ...(visitType ? { consultation_type: visitType } : {}),
        ...(contextId ? { context_id: contextId } : {}),
        // Free-text encounter context (iOS `encounter_context`) — prefilled
        // from a picked context's saved note, editable before upload.
        ...(contextNote.trim() ? { encounter_context: contextNote.trim() } : {}),
        consent_attested: true,
        consent_method: "attested",
        // Only send clip_count when there's more than one clip so single-file
        // imports hit the byte-identical legacy request shape.
        ...(multi ? { clip_count: files.length } : {}),
      });

      if (multi) {
        // One presigned PUT per clip, uploaded IN ORDER. The backend returns
        // `clips` ordered by `index`; guard against a server that didn't echo
        // enough presigns for the requested count.
        const clips = [...(created.clips ?? [])].sort((a, b) => a.index - b.index);
        if (clips.length < files.length) throw new Error("upload_failed");
        // Aggregate progress across clips: each clip contributes an equal
        // slice of the overall bar (per-file byte-weighting is unnecessary at
        // pilot scale and keeps the single-PUT uploader unchanged).
        const share = 100 / files.length;
        for (let i = 0; i < files.length; i++) {
          await putWithProgress(clips[i].upload_url, files[i], (pct) =>
            setUploadPct(Math.round(i * share + (pct / 100) * share)),
          );
        }
        setUploadPct(100);
      } else {
        // Single-file: large clinician uploads use resumable S3 multipart;
        // everything else (and the admin surface, which has no /me multipart
        // route) uses the single presigned PUT.
        const single = files[0];
        if (surface === "clinician" && single.size > MULTIPART_THRESHOLD) {
          await uploadMultipart(created.session_id, single, setUploadPct);
        } else {
          await putWithProgress(created.upload_url, single, setUploadPct);
        }
      }

      setPhase("processing");
      setStageIndex(0);
      setSessionId(created.session_id);
      cancelledRef.current = false;
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
                if (multiClipEnabled) {
                  addFiles(e.dataTransfer.files);
                } else {
                  pickFile(e.dataTransfer.files?.[0] ?? null);
                }
              }}
              className={
                "flex cursor-pointer flex-col items-center justify-center rounded-aurion-md border-2 border-dashed px-6 py-10 text-center transition-colors " +
                (dragRef.current
                  ? "border-aurion-gold bg-gold-50"
                  : "border-gray-300 hover:border-gray-400")
              }
            >
              <UploadCloud className="mb-2 h-8 w-8 text-gray-400" />
              {!multiClipEnabled && file ? (
                <span className="text-sm font-medium text-navy-700">
                  <Film className="mr-1 inline h-4 w-4" />
                  {file.name} · {humanBytes(file.size)}
                </span>
              ) : (
                <>
                  <span className="text-sm font-medium text-navy-700">
                    {multiClipEnabled
                      ? t("dropzone.promptMulti")
                      : t("dropzone.prompt")}
                  </span>
                  <span className="mt-1 text-xs text-gray-400">
                    {t("dropzone.accepted")}
                  </span>
                </>
              )}
              <input
                type="file"
                accept="video/mp4,video/quicktime,video/webm"
                multiple={multiClipEnabled}
                className="hidden"
                data-testid="video-import-file-input"
                onChange={(e) => {
                  if (multiClipEnabled) {
                    addFiles(e.target.files);
                  } else {
                    pickFile(e.target.files?.[0] ?? null);
                  }
                  // Allow re-selecting the same file(s) after a removal.
                  e.target.value = "";
                }}
              />
            </label>
          </Card>

          {multiClipEnabled && files.length > 0 && (
            <Card title={t("clips.title")}>
              <p className="mb-3 text-xs text-gray-500">{t("clips.hint")}</p>
              <ol className="space-y-2" data-testid="video-import-clip-list">
                {files.map((f, i) => (
                  <li
                    key={`${f.name}-${f.size}-${i}`}
                    className="flex items-center gap-2 rounded-aurion-md border border-gray-200 px-3 py-2 text-sm"
                    data-testid="video-import-clip-row"
                  >
                    <span className="w-5 flex-shrink-0 text-right font-medium text-gray-400">
                      {i + 1}
                    </span>
                    <Film className="h-4 w-4 flex-shrink-0 text-navy-500" />
                    <span className="min-w-0 flex-1 truncate text-navy-700">
                      {f.name}
                    </span>
                    <span className="flex-shrink-0 text-xs text-gray-400">
                      {humanBytes(f.size)}
                    </span>
                    <button
                      type="button"
                      className="rounded p-1 text-gray-400 hover:text-navy-700 disabled:opacity-30"
                      aria-label={t("clips.moveUp")}
                      disabled={i === 0}
                      onClick={() => moveClip(i, -1)}
                    >
                      <ArrowUp className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      className="rounded p-1 text-gray-400 hover:text-navy-700 disabled:opacity-30"
                      aria-label={t("clips.moveDown")}
                      disabled={i === files.length - 1}
                      onClick={() => moveClip(i, 1)}
                    >
                      <ArrowDown className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      className="rounded p-1 text-gray-400 hover:text-red-600"
                      aria-label={t("clips.remove")}
                      onClick={() => removeClip(i)}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </li>
                ))}
              </ol>
            </Card>
          )}

          <Card title={t("form.title")}>
            {surface === "clinician" ? (
              // TE-4e: mirror the iOS capture flow — visit type → context →
              // context box — with the template coming FROM the picked context
              // (no standalone template picker) and specialty taken from the
              // profile (so no specialty field here). Sends the same
              // consultation_type / context_id / encounter_context fields iOS's
              // /sessions carries; iOS itself is untouched.
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {(profile?.consultation_types.length ?? 0) > 0 && (
                    <label className="block text-sm">
                      <span className="mb-1 block font-medium text-navy-700">
                        {t("form.visitType")}
                      </span>
                      <select
                        className="form-input"
                        value={visitType}
                        onChange={(e) => {
                          setVisitType(e.target.value);
                          // Context belongs to a visit type — reset both the
                          // pick and the prefilled note when the type changes.
                          setContextId("");
                          setContextNote("");
                        }}
                        data-testid="video-import-visit-type"
                      >
                        <option value="">{t("form.visitTypeDefault")}</option>
                        {profile?.consultation_types.map((vt) => (
                          <option key={vt} value={vt}>
                            {humanizeVisitType(vt)}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
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
                        <option key={v} value={v}>
                          {t(`form.encounter.${v}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                {/* The visit type's saved contexts. Picking one resolves its
                    pinned template server-side and prefills the context box
                    with the context's saved note. */}
                {visitType &&
                  (profile?.contexts_per_visit_type[visitType]?.length ?? 0) >
                    0 && (
                    <label className="block text-sm">
                      <span className="mb-1 block font-medium text-navy-700">
                        {t("form.visitContext")}
                      </span>
                      <select
                        className="form-input"
                        value={contextId}
                        onChange={(e) => {
                          const id = e.target.value;
                          setContextId(id);
                          const ctx = profile?.contexts_per_visit_type[
                            visitType
                          ]?.find((c) => c.id === id);
                          setContextNote(ctx?.description ?? "");
                        }}
                        data-testid="video-import-visit-context"
                      >
                        <option value="">
                          {t("form.visitContextDefault")}
                        </option>
                        {profile?.contexts_per_visit_type[visitType]?.map(
                          (ctx) => (
                            <option key={ctx.id} value={ctx.id}>
                              {ctx.label}
                            </option>
                          ),
                        )}
                      </select>
                    </label>
                  )}

                {/* Resolved template — shown when the picked context pins one
                    explicitly (the "pull up its template" feedback). */}
                {resolvedTemplateName && (
                  <p
                    className="flex items-center gap-2 text-sm text-navy-600"
                    data-testid="video-import-resolved-template"
                  >
                    <FileText className="h-4 w-4 flex-shrink-0 text-navy-400" />
                    <span>
                      {t("form.templateApplied")}:{" "}
                      <span className="font-medium text-navy-800">
                        {resolvedTemplateName}
                      </span>
                    </span>
                  </p>
                )}

                {/* Context box — free text that travels to the note as
                    encounter context (iOS `encounter_context`). */}
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-navy-700">
                    {t("form.contextNote")}
                  </span>
                  <textarea
                    className="form-input min-h-[80px] resize-y"
                    value={contextNote}
                    maxLength={MAX_CONTEXT_DESCRIPTION_LEN}
                    placeholder={t("form.contextNotePlaceholder")}
                    onChange={(e) => setContextNote(e.target.value)}
                    data-testid="video-import-context-note"
                  />
                </label>

                <label className="block text-sm sm:max-w-xs">
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
            ) : (
              // Admin/eval surface — no personal profile: keep the specialty
              // picker + encounter type + language exactly as before.
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
                      <option key={s} value={s}>
                        {tSpec(s)}
                      </option>
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
                      <option key={v} value={v}>
                        {t(`form.encounter.${v}`)}
                      </option>
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
            )}
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
                    (i <= stageIndex ? "bg-aurion-gold " : "bg-gray-300 ") +
                    // The ACTIVE stage pulses. Without motion a slow stage —
                    // and "Extracting audio" on a real encounter takes
                    // minutes — is pixel-identical to a hung page, which is
                    // exactly how a healthy import came to look stuck.
                    (i === stageIndex ? "animate-aurion-pulse" : "")
                  }
                  data-testid={i === stageIndex ? "active-stage-dot" : undefined}
                />
                {t(`stages.${stage}`)}
              </li>
            ))}
          </ol>
          <p className="mt-4 text-xs text-gray-400">
            {t("processing.leaveSafe")}
            {elapsedLabel && (
              <>
                {" "}
                <span className="tabular-nums" data-testid="elapsed">
                  {t("processing.elapsed", { time: elapsedLabel })}
                </span>
              </>
            )}
          </p>
          {/* Escape hatch. Without it the only exit from a wedged import was
              the 15-minute watchdog — and that only fires while this page is
              polling, so closing the tab left the session stuck indefinitely.
              Clinician surface only: admin/eval has no /cancel route. */}
          {surface === "clinician" && sessionId && (
            <div className="mt-4 border-t border-hairline pt-3">
              <Button
                variant="secondary"
                size="sm"
                loading={cancelling}
                disabled={cancelling}
                onClick={() => void onCancelProcessing()}
                data-testid="cancel-processing"
              >
                {t("processing.cancel")}
              </Button>
            </div>
          )}
        </Card>
      )}

      {phase === "cancelled" && (
        <Card title={t("cancelled.title")}>
          <p className="text-sm text-navy-600">
            {retryable ? t("cancelled.retryable") : retryBlockedReason}
          </p>
          <div className="mt-4 flex items-center gap-3">
            {retryable && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => void onRetryProcessing()}
                data-testid="retry-processing"
              >
                {t("cancelled.retry")}
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void onStartOver()}
              data-testid="start-over"
            >
              {t("cancelled.startOver")}
            </Button>
          </div>
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
