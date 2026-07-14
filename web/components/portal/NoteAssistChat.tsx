"use client";

import { SendHorizontal, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { humanizeError } from "@/lib/api";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import type { ChatMessage, NoteAssistResponse } from "@/types";

/**
 * "Fix this note" chat — a Heidi-style grounded editor shown under the note on
 * the review screen. The physician types a plain-language request; `onAssist`
 * calls `POST /notes/{id}/assist`, which applies grounded edit ops and returns
 * the assistant reply plus (when it changed the note) triggers a re-fetch in
 * the parent. Errors surface IN the chat, never a page banner (#652 lesson).
 *
 * Gating on `note_review_chat_enabled` is the caller's responsibility.
 */
export default function NoteAssistChat({
  onAssist,
}: {
  onAssist: (message: string) => Promise<NoteAssistResponse>;
}) {
  const t = useTranslations("NoteReview.chat");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || sending) return;
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: message }]);
      setSending(true);
      try {
        const res = await onAssist(message);
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: res.assistant_message },
        ]);
      } catch (e) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: humanizeError(e, t("error")) },
        ]);
      } finally {
        setSending(false);
      }
    },
    [onAssist, sending, t],
  );

  useEffect(() => {
    // Assigning scrollTop (rather than scrollTo) keeps the auto-scroll working
    // in browsers while staying compatible with jsdom, which has no scrollTo.
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  const chips = [t("chipShorten"), t("chipAddMissed"), t("chipTidy")];

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-aurion-md bg-navy-900 text-gold-400">
          <Sparkles className="h-4 w-4" />
        </span>
        <div>
          <h2 className="text-aurion-callout font-semibold text-navy-800">
            {t("title")}
          </h2>
          <p className="text-aurion-caption text-navy-500">{t("hint")}</p>
        </div>
      </div>

      {messages.length > 0 && (
        <div
          ref={scrollRef}
          className="mb-3 max-h-64 space-y-2 overflow-y-auto rounded-aurion-md bg-canvas/40 p-3"
        >
          {messages.map((m, i) => (
            <div
              key={`${i}-${m.role}`}
              className={
                m.role === "user"
                  ? "ml-auto max-w-[85%] rounded-aurion-md bg-navy-900 px-3 py-2 text-aurion-caption text-white"
                  : "mr-auto max-w-[85%] rounded-aurion-md bg-white px-3 py-2 text-aurion-caption text-navy-800 ring-1 ring-inset ring-hairline"
              }
            >
              <span className="mb-0.5 block text-[10px] uppercase tracking-wide opacity-60">
                {m.role === "user" ? t("youLabel") : t("assistantLabel")}
              </span>
              {m.content}
            </div>
          ))}
          {sending && (
            <p className="text-aurion-caption text-navy-400">{t("thinking")}</p>
          )}
        </div>
      )}

      <div className="mb-2 flex flex-wrap gap-2">
        {chips.map((label) => (
          <button
            key={label}
            type="button"
            disabled={sending}
            onClick={() => void send(label)}
            className="rounded-full border border-hairline bg-white px-3 py-1 text-aurion-caption font-medium text-navy-600 transition-colors hover:border-navy-200 hover:text-navy-800 disabled:opacity-50"
          >
            {label}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="flex items-center gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
          placeholder={t("placeholder")}
          aria-label={t("title")}
          className="form-input flex-1"
        />
        <Button
          type="submit"
          variant="primary"
          size="sm"
          loading={sending}
          disabled={sending || !input.trim()}
        >
          <SendHorizontal className="h-4 w-4" />
          <span className="sr-only">{t("send")}</span>
        </Button>
      </form>
    </Card>
  );
}
