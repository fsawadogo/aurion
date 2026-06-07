import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import EncounterAudioCard from "@/components/portal/EncounterAudioCard";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import { withIntl } from "./helpers/intl";

/**
 * Encounter audio replay card (#338).
 *
 * Validates the physician-own-session replay flow:
 *   - NO auto-fetch on mount (each fetch writes an EVIDENCE_REPLAYED audit
 *     row, so the URL is requested only on the explicit button click).
 *   - url present → inline <audio> with the presigned src + autoplay.
 *   - audio_url null / 403 / 409 / other error → localized copy, no crash.
 *   - replay only — no download affordance is rendered.
 *
 * The API client is mocked at the module boundary so the card is
 * deterministic regardless of network state.
 */

vi.mock("@/lib/portal-api", () => ({
  getAudioReplayUrl: vi.fn(),
}));

import { getAudioReplayUrl } from "@/lib/portal-api";

const SESSION_ID = "11111111-1111-1111-1111-111111111111";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("EncounterAudioCard — no auto-fetch (audit hygiene)", () => {
  it("does NOT call the endpoint on mount", () => {
    render(withIntl(<EncounterAudioCard sessionId={SESSION_ID} />));
    expect(getAudioReplayUrl).not.toHaveBeenCalled();
    // The play button is the only affordance until the user acts.
    expect(
      screen.getByRole("button", { name: /Play recording/i }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("encounter-audio-player")).toBeNull();
  });
});

describe("EncounterAudioCard — successful replay", () => {
  it("renders an <audio> player with the presigned URL on click", async () => {
    vi.mocked(getAudioReplayUrl).mockResolvedValue({
      audio_url: "https://signed.example/audio.m4a?sig=abc",
      expires_in: 3600,
    });

    render(withIntl(<EncounterAudioCard sessionId={SESSION_ID} />));
    await userEvent.click(
      screen.getByRole("button", { name: /Play recording/i }),
    );

    const audio = (await screen.findByTestId(
      "encounter-audio-player",
    )) as HTMLAudioElement;
    expect(audio.tagName.toLowerCase()).toBe("audio");
    expect(audio).toHaveAttribute("src", "https://signed.example/audio.m4a?sig=abc");
    expect(audio).toHaveAttribute("controls");
    expect(audio).toHaveAttribute("autoplay");
    expect(getAudioReplayUrl).toHaveBeenCalledTimes(1);
    expect(getAudioReplayUrl).toHaveBeenCalledWith(SESSION_ID);

    // Replay only — no download affordance: no download button/link, and
    // the <audio> element carries no `download` control attribute.
    expect(
      screen.queryByRole("button", { name: /download|télécharger/i }),
    ).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(audio).not.toHaveAttribute("download");
  });
});

describe("EncounterAudioCard — graceful non-playable outcomes", () => {
  it("shows the unavailable copy when audio_url is null", async () => {
    vi.mocked(getAudioReplayUrl).mockResolvedValue({
      audio_url: null,
      expires_in: 0,
    });

    render(withIntl(<EncounterAudioCard sessionId={SESSION_ID} />));
    await userEvent.click(
      screen.getByRole("button", { name: /Play recording/i }),
    );

    expect(
      await screen.findByText("Recording not available for this session."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("encounter-audio-player")).toBeNull();
  });

  it("shows the not-enabled copy on a 403", async () => {
    vi.mocked(getAudioReplayUrl).mockRejectedValue(
      new Error("API 403: Media review retention is not enabled."),
    );

    render(withIntl(<EncounterAudioCard sessionId={SESSION_ID} />));
    await userEvent.click(
      screen.getByRole("button", { name: /Play recording/i }),
    );

    expect(
      await screen.findByText("Recording playback isn't enabled."),
    ).toBeInTheDocument();
  });

  it("shows the wrong-state copy on a 409", async () => {
    vi.mocked(getAudioReplayUrl).mockRejectedValue(
      new Error("API 409: session not in a reviewable state"),
    );

    render(withIntl(<EncounterAudioCard sessionId={SESSION_ID} />));
    await userEvent.click(
      screen.getByRole("button", { name: /Play recording/i }),
    );

    expect(
      await screen.findByText("Recording isn't available for this session yet."),
    ).toBeInTheDocument();
  });

  it("shows the generic error and keeps the retry button on other errors", async () => {
    vi.mocked(getAudioReplayUrl).mockRejectedValue(
      new Error("API 500: boom"),
    );

    render(withIntl(<EncounterAudioCard sessionId={SESSION_ID} />));
    await userEvent.click(
      screen.getByRole("button", { name: /Play recording/i }),
    );

    expect(
      await screen.findByText("Couldn't load the recording. Please try again."),
    ).toBeInTheDocument();
    // Retry is still possible.
    expect(
      screen.getByRole("button", { name: /Play recording/i }),
    ).toBeInTheDocument();
  });
});

describe("EncounterAudioCard i18n catalog parity", () => {
  const REQUIRED_KEYS = [
    "title",
    "description",
    "play",
    "playerAria",
    "playerFallback",
    "unavailable",
    "notEnabled",
    "wrongState",
    "error",
  ] as const;

  it("EN catalog has every recording key", () => {
    const en = enMessages.NoteReview.recording as Record<string, string>;
    for (const k of REQUIRED_KEYS) {
      expect(en).toHaveProperty(k);
      expect(typeof en[k]).toBe("string");
      expect(en[k].length).toBeGreaterThan(0);
    }
  });

  it("FR catalog has every recording key", () => {
    const fr = frMessages.NoteReview.recording as Record<string, string>;
    for (const k of REQUIRED_KEYS) {
      expect(fr).toHaveProperty(k);
      expect(typeof fr[k]).toBe("string");
      expect(fr[k].length).toBeGreaterThan(0);
    }
  });

  it("EN and FR recording keys are at parity (no English bleed in FR)", () => {
    const en = enMessages.NoteReview.recording as Record<string, string>;
    const fr = frMessages.NoteReview.recording as Record<string, string>;
    expect(Object.keys(en).sort()).toEqual(Object.keys(fr).sort());
    expect(fr.play).not.toBe(en.play);
    expect(fr.title).not.toBe(en.title);
  });

  it("renders the FR copy when the FR catalog is active", async () => {
    vi.mocked(getAudioReplayUrl).mockResolvedValue({
      audio_url: null,
      expires_in: 0,
    });

    render(withIntl(<EncounterAudioCard sessionId={SESSION_ID} />, "fr"));
    await userEvent.click(
      screen.getByRole("button", { name: /Écouter l’enregistrement/i }),
    );

    await waitFor(() =>
      expect(
        screen.getByText("Aucun enregistrement disponible pour cette session."),
      ).toBeInTheDocument(),
    );
  });
});
