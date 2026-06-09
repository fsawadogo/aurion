"use client";

import { Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import Button from "@/components/ui/Button";
import type { ChatMessage } from "@/types";

/**
 * Chat message-bubble UI for the conversational template builder.
 *
 * Pure presentational — the parent owns the API calls (start /
 * continue / finalize) and conversation state. This component just
 * renders the messages and surfaces an input.
 *
 * Strips the fenced JSON action blocks from assistant messages
 * before rendering — the schema-JSON noise belongs in the draft
 * preview card next to the chat, not inside a chat bubble.
 */

interface TemplateChatProps {
  messages: ChatMessage[];
  /** Disables the input + send button (during an in-flight LLM call). */
  busy: boolean;
  onSend: (message: string) => Promise<void> | void;
}

export default function TemplateChat({
  messages,
  busy,
  onSend,
}: TemplateChatProps) {
  const t = useTranslations("TemplateChat");
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the latest message on update.
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages.length, busy]);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    await onSend(text);
  }

  return (
    <div className="flex h-full flex-col rounded-lg border border-gray-200 bg-white">
      <div
        ref={listRef}
        className="flex-1 overflow-y-auto p-4 space-y-3"
        aria-live="polite"
      >
        {messages.map((m, i) => (
          <Bubble key={i} message={m} emptyLabel={t("draftUpdated")} />
        ))}
        {busy && (
          <div className="flex">
            <span className="inline-flex items-center gap-1.5 rounded-2xl rounded-bl-md bg-gray-100 px-3 py-2 text-sm text-gray-500">
              <Dots />
              <span>{t("thinking")}</span>
            </span>
          </div>
        )}
      </div>
      <div className="border-t border-gray-100 p-3 flex items-center gap-2">
        <input
          className="form-input flex-1"
          placeholder={busy ? t("sending") : t("inputPlaceholder")}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          disabled={busy}
          aria-label={t("inputAria")}
        />
        <Button
          variant="primary"
          size="sm"
          onClick={() => void send()}
          disabled={busy || draft.trim().length === 0}
          loading={busy}
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function Bubble({
  message,
  emptyLabel,
}: {
  message: ChatMessage;
  emptyLabel: string;
}) {
  const isUser = message.role === "user";
  const cleaned = isUser ? message.content : stripDraftBlock(message.content);
  return (
    <div className={"flex " + (isUser ? "justify-end" : "justify-start")}>
      <span
        className={
          "max-w-[80%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm " +
          (isUser
            ? "rounded-br-md bg-navy-700 text-white"
            : "rounded-bl-md bg-gray-100 text-gray-800")
        }
      >
        {cleaned || emptyLabel}
      </span>
    </div>
  );
}

function Dots() {
  return (
    <span className="inline-flex gap-1">
      <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-pulse" />
      <span
        className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-pulse"
        style={{ animationDelay: "150ms" }}
      />
      <span
        className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-pulse"
        style={{ animationDelay: "300ms" }}
      />
    </span>
  );
}

/** Strip the fenced ```json {"action":"draft_template",...}``` block
 * the LLM emits. The draft preview card next to the chat is the right
 * place for that JSON — inside a chat bubble it's overwhelming. */
function stripDraftBlock(text: string): string {
  const re = /```(?:json)?\s*\{[\s\S]*?"action"\s*:\s*"draft_template"[\s\S]*?\}\s*```/gi;
  return text.replace(re, "").trim();
}
