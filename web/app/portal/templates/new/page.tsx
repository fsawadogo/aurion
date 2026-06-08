"use client";

import { Check, LayoutGrid } from "lucide-react";
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
import {
  continueTemplateAuthoring,
  finalizeTemplateAuthoring,
  getTemplateAuthoring,
  startTemplateAuthoring,
} from "@/lib/portal-api";
import type { TemplateAuthoringSession } from "@/types";

/**
 * /portal/templates/new — conversational template builder.
 *
 * Two-column layout: chat (left) + draft preview (right). The chat
 * starts with the LLM's hardcoded bootstrap message ("what specialty
 * is this for?") or — if `?session=<id>` is in the URL — resumes an
 * existing authoring session (used by the upload flow on the list
 * page).
 *
 * On finalize the draft is promoted to a custom_templates row and the
 * user lands on `/portal/templates/[id]` for the read view.
 */
export default function NewTemplatePage() {
  return (
    <Suspense fallback={null}>
      <NewTemplateInner />
    </Suspense>
  );
}

function NewTemplateInner() {
  const t = useTranslations("TemplateNew");
  const search = useSearchParams();
  const resumeId = search.get("session");

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
    // Optimistic user message — appears immediately rather than waiting
    // for the round-trip. Backend echoes the same content on the next
    // GET so there's no drift to reconcile.
    setAuthSession({
      ...authSession,
      messages: [...authSession.messages, { role: "user", content: message }],
    });
    try {
      const updated = await continueTemplateAuthoring(authSession.id, message);
      setAuthSession(updated);
    } catch (e) {
      setError(humanizeError(e, t("replyError")));
      // Roll back the optimistic message so the user can retry.
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
      // Hard navigation for dynamic `/portal/templates/[id]` — Next
      // router collapses the URL under static export. See
      // web/lib/use-route-segment.ts.
      window.location.assign(`/portal/templates/${custom.id}`);
    } catch (e) {
      setError(humanizeError(e, t("saveError")));
      setFinalizing(false);
    }
  }

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

      {bootstrapping ? (
        <Card>
          <LoadingSkeleton lines={8} />
        </Card>
      ) : error && !authSession ? (
        <Card>
          <p className="text-sm text-red-600">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void bootstrap()}>
            {t("retry")}
          </Button>
        </Card>
      ) : authSession ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="h-[calc(100vh-220px)] min-h-[480px]">
            <h2 className="aurion-micro mb-2">
              {t("conversationLabel")}
            </h2>
            <TemplateChat
              messages={authSession.messages}
              busy={busy}
              onSend={onSend}
            />
          </div>
          <div className="space-y-3">
            <h2 className="aurion-micro mb-0">
              {t("draftPreviewLabel")}
            </h2>
            {error && (
              <div className="rounded-aurion-md bg-red-50 border border-red-200 px-3 py-2 text-aurion-callout text-red-700">
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
                  <Check className="h-4 w-4 mr-1" />
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
      ) : null}
    </div>
  );
}
