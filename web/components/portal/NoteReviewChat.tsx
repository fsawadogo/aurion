"use client";

import { ChevronDown, ChevronUp, MessagesSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import TemplateChat from "@/components/portal/TemplateChat";
import { humanizeError } from "@/lib/api";
import {
  getPortalFeatureFlags,
  getReviewChat,
  sendReviewChatMessage,
} from "@/lib/portal-api";
import type { ChatMessage } from "@/types";

/**
 * "Fix this note" — conversational note editing under the generated note
 * (note_review_chat_enabled).
 *
 * Plain-language instructions ("shorten the HPI", "add the sulfa allergy")
 * are applied server-side as grounded, auto-versioned edits: every applied
 * turn creates a NEW immutable note version through the same path as a
 * manual section edit, with provenance enforced in backend code. A turn that
 * applies an edit triggers `onNoteUpdated` so the parent refetches the note.
 *
 * Self-gating: renders nothing until the feature flag resolves true (every
 * backend call 404s while dark — hiding is UX, the flag check server-side is
 * the enforcement). Only shown in the states where edits are allowed, same
 * window as the manual edit path.
 */

const EDITABLE_STATES = new Set(["AWAITING_REVIEW", "REVIEW_COMPLETE"]);

export default function NoteReviewChat({
  sessionId,
  sessionState,
  onNoteUpdated,
}: {
  sessionId: string;
  sessionState: string;
  onNoteUpdated: () => Promise<void> | void;
}) {
  const t = useTranslations("NoteReviewChat");
  const [enabled, setEnabled] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastApplied, setLastApplied] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getPortalFeatureFlags()
      .then((f) => {
        if (!cancelled) setEnabled(f.note_review_chat_enabled);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // History loads lazily on first expand — most reviews never open the chat.
  useEffect(() => {
    if (!expanded || messages !== null) return;
    let cancelled = false;
    void getReviewChat(sessionId)
      .then((state) => {
        if (!cancelled) setMessages(state.messages);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(humanizeError(e, t("loadError")));
          setMessages([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [expanded, messages, sessionId, t]);

  if (!enabled || !EDITABLE_STATES.has(sessionState)) return null;

  async function onSend(message: string) {
    setBusy(true);
    setError(null);
    setLastApplied(null);
    // Optimistic append so the user's bubble shows during the round-trip.
    setMessages((prev) => [...(prev ?? []), { role: "user", content: message }]);
    try {
      const state = await sendReviewChatMessage(sessionId, message);
      setMessages(state.messages);
      if (state.applied_version) {
        setLastApplied(state.applied_version);
        await onNoteUpdated();
      }
    } catch (e) {
      setError(humanizeError(e, t("sendError")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="rounded-lg border border-gray-200 bg-white"
      data-testid="note-review-chat"
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
        onClick={() => setExpanded((x) => !x)}
        aria-expanded={expanded}
      >
        <MessagesSquare className="h-4 w-4 text-gold-600" />
        <span className="flex-1 text-sm font-semibold text-navy-800">
          {t("title")}
        </span>
        <span className="text-[11px] text-gray-400">{t("hint")}</span>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-gray-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-gray-400" />
        )}
      </button>
      {expanded && (
        <div className="border-t border-gray-100 p-3">
          {error && (
            <div
              className="mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
              role="alert"
            >
              {error}
            </div>
          )}
          {lastApplied !== null && (
            <div
              className="mb-2 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-800"
              role="status"
            >
              {t("applied", { version: lastApplied })}
            </div>
          )}
          <div className="h-80">
            <TemplateChat
              messages={messages ?? []}
              busy={busy || messages === null}
              onSend={onSend}
              emptyLabel={t("editApplied")}
              placeholder={t("placeholder")}
            />
          </div>
        </div>
      )}
    </section>
  );
}
