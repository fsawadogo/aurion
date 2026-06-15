"use client";

import { Check, LayoutGrid, Sparkles, SlidersHorizontal } from "lucide-react";
import { humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import TemplateChat from "@/components/portal/TemplateChat";
import TemplateDraftPreview from "@/components/portal/TemplateDraftPreview";
import TemplateSectionEditor, {
  blankTemplate,
  normalizeTemplate,
  validateTemplate,
} from "@/components/portal/TemplateSectionEditor";
import {
  continueTemplateAuthoring,
  createMyCustomTemplate,
  finalizeTemplateAuthoring,
  getTemplateAuthoring,
  startTemplateAuthoring,
} from "@/lib/portal-api";
import type { TemplateAuthoringSession, TemplateDefinition } from "@/types";

/**
 * /portal/templates/new — create a custom note template.
 *
 * Two modes:
 *   * "manual" (default) — a deterministic structured section editor
 *     (TemplateSectionEditor → createMyCustomTemplate). No LLM, so it works
 *     even when the note provider is down / rate-limited.
 *   * "ai" — the conversational builder (chat + draft preview → finalize).
 *     Forced when resuming an authoring session via `?session=<id>` (the
 *     upload flow lands here).
 *
 * On save the template is persisted and the user lands on
 * /portal/templates/[id] for the read view.
 */
export default function NewTemplatePage() {
  return (
    <Suspense fallback={null}>
      <NewTemplateInner />
    </Suspense>
  );
}

type Mode = "manual" | "ai";

function NewTemplateInner() {
  const t = useTranslations("TemplateNew");
  const te = useTranslations("TemplateEditor");
  const search = useSearchParams();
  const resumeId = search.get("session");

  // Resuming an authoring session (upload flow) forces AI mode; otherwise the
  // deterministic manual editor is the default.
  const [mode, setMode] = useState<Mode>(resumeId ? "ai" : "manual");
  // Lazy-mount the AI builder so we don't mint an authoring session until the
  // user actually enters AI mode; once mounted it stays mounted (hidden), so
  // toggling back and forth preserves the conversation instead of restarting.
  const [aiActivated, setAiActivated] = useState<boolean>(!!resumeId);

  // Both builders stay mounted and the inactive one is hidden with `hidden`
  // (display:none) rather than conditionally rendered — so switching tabs
  // never unmounts the active builder and silently discards in-progress work.
  return (
    <div className="aurion-page-padded aurion-container">
      <PageHeader
        breadcrumb={[
          { label: t("breadcrumbTemplates"), href: "/portal/templates" },
          { label: t("breadcrumbNew") },
        ]}
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
      />

      {/* Mode toggle — resuming an upload session pins AI mode. */}
      {!resumeId && (
        <div className="mb-4 inline-flex items-center gap-1 rounded-aurion-md border border-gray-200 p-1">
          <ModeButton
            active={mode === "manual"}
            onClick={() => setMode("manual")}
            icon={<SlidersHorizontal className="h-4 w-4" />}
            label={t("modeManual")}
          />
          <ModeButton
            active={mode === "ai"}
            onClick={() => {
              setAiActivated(true);
              setMode("ai");
            }}
            icon={<Sparkles className="h-4 w-4" />}
            label={t("modeAi")}
          />
        </div>
      )}

      <div className={mode === "manual" ? "" : "hidden"}>
        <ManualBuilder t={t} te={te} />
      </div>
      {aiActivated && (
        <div className={mode === "ai" ? "" : "hidden"}>
          <AiBuilder t={t} resumeId={resumeId} />
        </div>
      )}
    </div>
  );
}

/* ── Manual structured builder (deterministic, no LLM) ──────────────────── */

function ManualBuilder({
  t,
  te,
}: {
  t: ReturnType<typeof useTranslations>;
  te: ReturnType<typeof useTranslations>;
}) {
  const [draft, setDraft] = useState<TemplateDefinition>(() => blankTemplate());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSave() {
    const validationKey = validateTemplate(draft);
    if (validationKey) {
      setError(te(validationKey));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createMyCustomTemplate(normalizeTemplate(draft));
      // Hard navigation for the dynamic /portal/templates/[id] route under
      // static export (see web/lib/use-route-segment.ts).
      window.location.assign(`/portal/templates/${created.id}`);
    } catch (e) {
      setError(humanizeError(e, t("saveError")));
      setSaving(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Card>
          <p className="mb-4 text-aurion-callout text-navy-500">{t("manualHint")}</p>
          <TemplateSectionEditor value={draft} onChange={setDraft} disabled={saving} />
        </Card>

        {error && (
          <div
            role="alert"
            className="rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          >
            {error}
          </div>
        )}

        <div className="flex justify-end">
          <Button
            variant="primary"
            onClick={() => void onSave()}
            loading={saving}
            disabled={saving}
          >
            <Check className="mr-1 h-4 w-4" />
            {t("createButton")}
          </Button>
        </div>
      </div>

      {/* Live Preview (Stitch) — reflects the manual draft as sections are
          added. Reuses the AI builder's preview card; it shows its own
          empty state until sections exist. */}
      <div className="lg:col-span-1">
        <div className="lg:sticky lg:top-4">
          <TemplateDraftPreview template={draft} />
        </div>
      </div>
    </div>
  );
}

/* ── Conversational AI builder (unchanged behavior) ─────────────────────── */

function AiBuilder({
  t,
  resumeId,
}: {
  t: ReturnType<typeof useTranslations>;
  resumeId: string | null;
}) {
  const [authSession, setAuthSession] = useState<TemplateAuthoringSession | null>(
    null,
  );
  const [bootstrapping, setBootstrapping] = useState(true);
  const [busy, setBusy] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bootstrap = useCallback(async () => {
    setBootstrapping(true);
    setError(null);
    try {
      const s = resumeId
        ? await getTemplateAuthoring(resumeId)
        : await startTemplateAuthoring();
      setAuthSession(s);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setBootstrapping(false);
    }
  }, [resumeId, t]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  async function onSend(message: string) {
    if (!authSession || busy) return;
    setBusy(true);
    setError(null);
    setAuthSession({
      ...authSession,
      messages: [...authSession.messages, { role: "user", content: message }],
    });
    try {
      const updated = await continueTemplateAuthoring(authSession.id, message);
      setAuthSession(updated);
    } catch (e) {
      setError(humanizeError(e, t("replyError")));
      void getTemplateAuthoring(authSession.id).then(setAuthSession).catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  async function onFinalize() {
    if (!authSession) return;
    setFinalizing(true);
    setError(null);
    try {
      const custom = await finalizeTemplateAuthoring(authSession.id);
      window.location.assign(`/portal/templates/${custom.id}`);
    } catch (e) {
      setError(humanizeError(e, t("saveError")));
      setFinalizing(false);
    }
  }

  if (bootstrapping) {
    return (
      <Card>
        <LoadingSkeleton lines={8} />
      </Card>
    );
  }
  if (error && !authSession) {
    return (
      <Card>
        <p className="text-sm text-red-600">{error}</p>
        <Button variant="secondary" className="mt-3" onClick={() => void bootstrap()}>
          {t("retry")}
        </Button>
      </Card>
    );
  }
  if (!authSession) return null;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="h-[calc(100vh-260px)] min-h-[480px]">
        <h2 className="aurion-micro mb-2">{t("conversationLabel")}</h2>
        <TemplateChat messages={authSession.messages} busy={busy} onSend={onSend} />
      </div>
      <div className="space-y-3">
        <h2 className="aurion-micro mb-0">{t("draftPreviewLabel")}</h2>
        {error && (
          <div
            role="alert"
            className="rounded-aurion-md border border-red-200 bg-red-50 px-3 py-2 text-aurion-callout text-red-700"
          >
            {error}
          </div>
        )}
        {authSession.draft_template ? (
          <>
            <TemplateDraftPreview template={authSession.draft_template} />
            <Button
              variant="primary"
              onClick={() => void onFinalize()}
              loading={finalizing}
              disabled={finalizing}
              fullWidth
            >
              <Check className="mr-1 h-4 w-4" />
              {t("saveTemplate")}
            </Button>
          </>
        ) : (
          <Card>
            <div className="flex flex-col items-center justify-center py-6 text-center">
              <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-navy-50 text-navy-400">
                <LayoutGrid className="h-6 w-6" />
              </div>
              <p className="text-aurion-callout italic text-navy-500 max-w-[34ch]">
                {t("draftPlaceholder")}
              </p>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        "inline-flex items-center gap-1.5 rounded-aurion-xs px-3 py-1.5 text-xs font-medium transition-colors duration-short " +
        (active
          ? "bg-navy-50 text-navy-800"
          : "text-navy-500 hover:bg-canvas hover:text-navy-700")
      }
    >
      {icon}
      {label}
    </button>
  );
}
