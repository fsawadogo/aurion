"use client";

import { AudioLines, Play } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import { getAudioReplayUrl } from "@/lib/portal-api";

/**
 * Encounter audio replay card on the physician's own note-review screen
 * (`/portal/notes/[id]`) — #338.
 *
 * Lets the logged-in clinician REPLAY (play in the browser) the raw audio
 * of their own session. Replay only — the presigned URL is held in
 * component state, rendered straight into a native `<audio controls>`
 * element, and never offered as a download nor logged.
 *
 * ## No auto-fetch (audit hygiene)
 *
 * Each successful `getAudioReplayUrl` call mints a URL AND writes an
 * EVIDENCE_REPLAYED audit row server-side. So we NEVER fetch on mount —
 * the URL is requested only when the physician clicks "Play recording".
 * That keeps the audit trail to genuine, intentional replays.
 *
 * ## Graceful states
 *
 * The backend's outcomes are mapped to localized copy rather than raw
 * errors:
 *   - url present → inline `<audio controls autoPlay>`.
 *   - audio_url null → "Recording not available for this session."
 *   - 403 → "Recording playback isn't enabled." (the
 *     `media_review_retention_enabled` flag is off — the portal has no
 *     clean clinician-readable view of that flag, so we always render the
 *     button and lean on this 403 to message the flag-off case).
 *   - 409 → "Recording isn't available for this session yet."
 *   - other → a generic error; the button stays so the physician can retry.
 *
 * The status mapping mirrors the regex-on-message convention the other
 * portal cards use (see PatientSummaryCard) — fetchWithAuth throws
 * `API {status}: …`, so a `\b403\b` / `\b409\b` test on the message is
 * enough to branch.
 */

interface EncounterAudioCardProps {
  sessionId: string;
}

type AudioState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; url: string }
  | { kind: "unavailable" }
  | { kind: "not_enabled" }
  | { kind: "wrong_state" }
  | { kind: "error" };

export default function EncounterAudioCard({
  sessionId,
}: EncounterAudioCardProps) {
  const t = useTranslations("NoteReview.recording");
  const [state, setState] = useState<AudioState>({ kind: "idle" });

  async function onPlay() {
    setState({ kind: "loading" });
    try {
      const res = await getAudioReplayUrl(sessionId);
      if (res.audio_url) {
        // Hold the presigned URL in state only — it is never logged.
        setState({ kind: "ready", url: res.audio_url });
      } else {
        setState({ kind: "unavailable" });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (/\b403\b/.test(msg)) {
        setState({ kind: "not_enabled" });
      } else if (/\b409\b/.test(msg)) {
        setState({ kind: "wrong_state" });
      } else {
        // 404 (not owner) and anything else collapse to the generic
        // error so we never leak status detail into the UI.
        setState({ kind: "error" });
      }
    }
  }

  const message =
    state.kind === "unavailable"
      ? t("unavailable")
      : state.kind === "not_enabled"
        ? t("notEnabled")
        : state.kind === "wrong_state"
          ? t("wrongState")
          : state.kind === "error"
            ? t("error")
            : null;

  return (
    <Card>
      <section aria-label={t("title")}>
        <div className="mb-2 flex items-center gap-2 text-aurion-headline">
          <AudioLines className="h-4 w-4 text-gold-500" aria-hidden />
          {t("title")}
        </div>
        <p className="aurion-callout text-navy-500 mb-3">{t("description")}</p>

        {message && (
          <div
            className="mb-3 rounded-aurion-md bg-canvas border border-hairline px-3 py-2 text-aurion-caption text-navy-600"
            role="status"
          >
            {message}
          </div>
        )}

        {state.kind === "ready" ? (
          <audio
            src={state.url}
            controls
            autoPlay
            data-testid="encounter-audio-player"
            aria-label={t("playerAria")}
            className="w-full"
          >
            {t("playerFallback")}
          </audio>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            loading={state.kind === "loading"}
            disabled={state.kind === "loading"}
            onClick={() => void onPlay()}
          >
            <Play className="h-4 w-4 mr-1.5" aria-hidden />
            {t("play")}
          </Button>
        )}
      </section>
    </Card>
  );
}
