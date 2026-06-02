"use client";

import { Check } from "lucide-react";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
  const router = useRouter();
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
      setError(e instanceof Error ? e.message : "Could not start a session.");
    } finally {
      setBootstrapping(false);
    }
  }, [resumeId]);

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
      setError(e instanceof Error ? e.message : "Reply failed.");
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
      router.push(`/portal/templates/${custom.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
      setFinalizing(false);
    }
  }

  return (
    <div className="aurion-page-padded aurion-container">
      <PageHeader
        breadcrumb={[
          { label: "Templates", href: "/portal/templates" },
          { label: "New" },
        ]}
        eyebrow="Conversational builder"
        title="New template"
        description="Chat with the builder to design a custom note template. When you're happy with the preview, click Save."
      />

      {bootstrapping ? (
        <Card>
          <LoadingSkeleton lines={8} />
        </Card>
      ) : error && !authSession ? (
        <Card>
          <p className="text-sm text-red-600">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void bootstrap()}>
            Retry
          </Button>
        </Card>
      ) : authSession ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="h-[calc(100vh-220px)] min-h-[480px]">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
              Conversation
            </h2>
            <TemplateChat
              messages={authSession.messages}
              busy={busy}
              onSend={onSend}
            />
          </div>
          <div className="space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-0">
              Draft preview
            </h2>
            {error && (
              <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
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
                  Save this template
                </Button>
              </>
            ) : (
              <Card>
                <p className="text-sm text-gray-500 italic">
                  The builder will draft your template here once you&apos;ve
                  confirmed the specialty, sections, and which are
                  required.
                </p>
              </Card>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
