"""Build the Take 8 demo video.

Composition (in order):
  1. Logo.png (Aurion) held for 3s — intro splash (silent).
  2. Take 8.mov segment up through voice enrollment — narration block A.
  3. Logo.png (Aurion) held for 4s — brand-beat between personalization
     and clinical workflow (silent).
  4. Take 8.mov from the dashboard onward — narration block B.

The narration is generated with HyperFrames TTS (Kokoro-82M, `af_heart`
voice) — same engine the previous demo-video.mp4 used so pronunciation
matches. Each block plays back-to-back with a small inter-scene gap so
nothing sits in long silence.

Output: demo/take8-demo.mp4
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEMO_DIR = Path(__file__).parent
REPO_ROOT = DEMO_DIR.parent
TAKE8 = DEMO_DIR / "Take 8.mov"
# Square Aurion logo (1024×1024 on navy #0C1B37) used for the intro and
# the mid-splash. Padded to the phone frame at render time.
LOGO = REPO_ROOT / "Logo.png"
LOGO_BG = "0x0C1B37"
WORK = DEMO_DIR / ".take8-build"
OUT = DEMO_DIR / "take8-demo.mp4"

# Intro logo before Take 8 begins.
INTRO_SECONDS = 3.0
# Brand-beat logo inserted between voice enrollment and the dashboard.
# Replaces the awkward stale-state dashboard frames that were appearing
# at this point in the prior cut.
MIDSPLASH_SECONDS = 4.0
# Where to cut Take 8 to drop in the mid-splash logo. ~57s is right
# after "Creating your voice profile" finishes loading.
TAKE8_SPLIT_AT = 57.0
# Where to resume Take 8 after the mid-splash. ~60s is the first frame
# of the dashboard / profile-setup screen.
TAKE8_RESUME_AT = 60.0

# Kokoro voice for HyperFrames TTS — `af_heart` matches the prior
# demo-video.mp4 narration (warm, professional American female).
VOICE = "af_heart"
# Where to invoke `npx hyperframes` from — the existing HyperFrames
# project directory has the right node_modules + model cache.
HF_PROJECT = DEMO_DIR / "video"


@dataclass
class Scene:
    """One narration line. `block` selects which video segment it plays over.

    Block A is everything up to the mid-splash (intro through voice
    enrollment). Block B is everything after (dashboard through approval).
    """
    block: str  # "A" or "B"
    text: str


# Scene narration in the order screens appear in Take 8. Scenes flow
# back-to-back with a small inter-scene gap — no anchoring to specific
# Take 8 timestamps, which is what caused the long silent pauses in the
# previous build. Brand name is spelled "Orion" because that is what
# Kokoro reads cleanly (matches the prior demo-video.mp4 narration).
SCENES: list[Scene] = [
    # ── Block A: intro + onboarding (Take 8 0 → split) ───────────────
    Scene("A",
          "Orion. A multimodal clinical AI platform designed to reduce "
          "documentation burden and enhance clinical workflow."),
    Scene("A",
          "Onboarding begins with the wearable. Orion scans for a Ray-Ban Meta "
          "or any approved capture device over Bluetooth."),
    Scene("A",
          "Once paired, the wearable becomes the encounter's eyes and ears. "
          "If no wearable is available, the phone takes over."),
    Scene("A",
          "Before voice enrollment, the physician reviews how their voice "
          "profile is created and stored — entirely on this device."),
    Scene("A",
          "The physician reads four short clinical phrases. Orion uses them "
          "to build an on-device voice embedding."),
    Scene("A",
          "That embedding lets Orion distinguish physician speech from the "
          "patient's, without storing the raw recording and without ever "
          "transmitting biometrics off the device."),
    Scene("A",
          "The voice profile is generated locally and stored in the secure "
          "Keychain. The raw audio is deleted immediately."),

    # ── Block B: workflow (after mid-splash, Take 8 resume → end) ────
    Scene("B",
          "A short profile setup follows — practice type, visit types, and "
          "recording preferences. Orion uses this to pick the right "
          "specialty template."),
    Scene("B",
          "The dashboard surfaces today's sessions, pending reviews, and "
          "quick-start tiles tuned to the physician's specialty."),
    Scene("B",
          "Starting a session, Orion asks who is in the room — a standard "
          "visit, a team member, or a trainee. Consent and capture adapt."),
    Scene("B",
          "Capture mode is per-session. Multimodal captures audio and video "
          "for full vision enrichment."),
    Scene("B",
          "Context is required — a few words about what brings the patient "
          "in today. Orion uses it to focus the note on the right template."),
    Scene("B",
          "Recording is hard-blocked behind patient consent. iOS permissions "
          "are requested in-context — never at app launch."),
    Scene("B",
          "While recording, the physician sees a live waveform, the running "
          "timer, and the camera preview. Frames are masked before any "
          "network upload."),
    Scene("B",
          "On stop, the physician confirms the template and language. "
          "Audio uploads to Whisper; the Stage 1 note is delivered in under "
          "thirty seconds."),
    Scene("B",
          "The physician is notified the moment the note is ready."),
    Scene("B",
          "The note reads as continuous clinical prose with every claim "
          "traceable to its source. Optional sections never block approval. "
          "One tap to Approve and Sign."),
]

# Gap inserted between consecutive scenes (seconds). Small enough that
# narration flows naturally; large enough that scenes don't bleed into
# each other.
SCENE_GAP = 0.35


def run(*args: str | os.PathLike, **kw) -> subprocess.CompletedProcess:
    """Run a command, raising on non-zero exit."""
    result = subprocess.run(args, check=False, capture_output=True, text=True, **kw)
    if result.returncode != 0:
        sys.stderr.write(f"\nCommand failed: {' '.join(map(str, args))}\n")
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def synthesize_scenes() -> list[Path]:
    """Generate one WAV per scene via `npx hyperframes tts` (Kokoro).

    Returns the list of WAV paths in scene order. Each clip is resampled
    to 48 kHz stereo so ffmpeg can mix without on-the-fly conversion.
    """
    wavs: list[Path] = []
    for i, scene in enumerate(SCENES):
        raw = WORK / f"scene_{i:02d}_raw.wav"
        wav = WORK / f"scene_{i:02d}.wav"
        # Kokoro outputs 24 kHz mono PCM; matches what the prior demo used.
        run(
            "npx", "hyperframes", "tts", scene.text,
            "--voice", VOICE,
            "--output", str(raw),
            cwd=str(HF_PROJECT),
        )
        run("ffmpeg", "-y", "-i", str(raw),
            "-ar", "48000", "-ac", "2", str(wav))
        wavs.append(wav)
    return wavs


def probe_duration(path: Path) -> float:
    """Return media duration in seconds."""
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], text=True).strip()
    return float(out)


def render_silence(duration: float, path: Path) -> Path:
    """Render a stereo 48 kHz silent WAV of the given duration."""
    run(
        "ffmpeg", "-y",
        "-f", "lavfi", "-t", f"{duration:.3f}",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        str(path),
    )
    return path


def concat_scenes(
    scene_wavs: list[Path],
    *,
    target_duration: float,
    label: str,
) -> Path:
    """Concatenate scene WAVs back-to-back with SCENE_GAP between each,
    then pad with trailing silence so the result equals `target_duration`.

    Scenes are emitted in the order given. The caller is responsible for
    passing only the scenes that belong in this block.
    """
    gap = WORK / f"gap_{label}.wav"
    render_silence(SCENE_GAP, gap)

    list_path = WORK / f"{label}_concat.txt"
    lines: list[str] = []
    for i, wav in enumerate(scene_wavs):
        lines.append(f"file '{wav.resolve()}'")
        if i < len(scene_wavs) - 1:
            lines.append(f"file '{gap.resolve()}'")
    list_path.write_text("\n".join(lines) + "\n")

    raw = WORK / f"{label}_concat.wav"
    run(
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-ar", "48000", "-ac", "2",
        str(raw),
    )

    padded = WORK / f"{label}_padded.wav"
    run(
        "ffmpeg", "-y",
        "-i", str(raw),
        "-af", f"apad=whole_dur={target_duration:.3f}",
        "-t", f"{target_duration:.3f}",
        "-ar", "48000", "-ac", "2",
        str(padded),
    )
    return padded


def render_image_clip(
    image: Path, duration: float, audio: Path, out: Path
) -> Path:
    """Encode a still image as a video clip of the given duration with
    the supplied audio (silent or narration).

    The image is scaled so its longer edge fits inside the 1206×2622
    phone frame, then padded with the Aurion navy `LOGO_BG`. Keeps the
    square logo intact instead of stretching it to a phone aspect ratio.
    """
    vf = (
        "scale=1206:2622:force_original_aspect_ratio=decrease,"
        f"pad=1206:2622:(ow-iw)/2:(oh-ih)/2:{LOGO_BG},"
        "format=yuv420p"
    )
    run(
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{duration:.3f}", "-i", str(image),
        "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", vf,
        "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-t", f"{duration:.3f}",
        str(out),
    )
    return out


def render_video_clip(
    src: Path, start: float, end: float, audio: Path, out: Path
) -> Path:
    """Re-encode a slice of `src` with `audio` replacing its track."""
    duration = end - start
    run(
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-an", "-i", str(src),
        "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", "scale=1206:2622,format=yuv420p",
        "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-t", f"{duration:.3f}",
        str(out),
    )
    return out


def compose_final(block_a: Path, block_b: Path) -> Path:
    """Compose the final video as four concatenated clips.

    Clip 1: Aurion logo (silent) — intro.
    Clip 2: Take 8 [0 → TAKE8_SPLIT_AT] with block A narration.
    Clip 3: Aurion logo (silent) — brand-beat after voice enrollment.
    Clip 4: Take 8 [TAKE8_RESUME_AT → end] with block B narration.

    Each clip is re-encoded with the same codec parameters, so the final
    concat is a stream copy (fast + lossless).
    """
    take8_duration = probe_duration(TAKE8)

    # Silent audio tracks for the two logo clips.
    silent_intro = WORK / "silent_intro.wav"
    silent_mid = WORK / "silent_mid.wav"
    render_silence(INTRO_SECONDS, silent_intro)
    render_silence(MIDSPLASH_SECONDS, silent_mid)

    clip1 = WORK / "clip1_intro.mp4"
    clip2 = WORK / "clip2_blockA.mp4"
    clip3 = WORK / "clip3_midsplash.mp4"
    clip4 = WORK / "clip4_blockB.mp4"

    render_image_clip(LOGO, INTRO_SECONDS, silent_intro, clip1)
    render_video_clip(TAKE8, 0.0, TAKE8_SPLIT_AT, block_a, clip2)
    render_image_clip(LOGO, MIDSPLASH_SECONDS, silent_mid, clip3)
    render_video_clip(TAKE8, TAKE8_RESUME_AT, take8_duration, block_b, clip4)

    concat_list = WORK / "concat.txt"
    concat_list.write_text(
        f"file '{clip1.resolve()}'\n"
        f"file '{clip2.resolve()}'\n"
        f"file '{clip3.resolve()}'\n"
        f"file '{clip4.resolve()}'\n"
    )
    run(
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(OUT),
    )
    return OUT


def main() -> None:
    if not TAKE8.exists():
        raise SystemExit(f"Missing: {TAKE8}")
    if not LOGO.exists():
        raise SystemExit(f"Missing: {LOGO}")
    WORK.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Synthesizing {len(SCENES)} narration scenes via Kokoro ({VOICE})…")
    scene_wavs = synthesize_scenes()

    print("[2/4] Building narration blocks A (pre-splash) and B (post-splash)…")
    block_a_wavs = [w for s, w in zip(SCENES, scene_wavs) if s.block == "A"]
    block_b_wavs = [w for s, w in zip(SCENES, scene_wavs) if s.block == "B"]
    take8_duration = probe_duration(TAKE8)
    block_a_dur = TAKE8_SPLIT_AT
    block_b_dur = take8_duration - TAKE8_RESUME_AT
    block_a = concat_scenes(block_a_wavs, target_duration=block_a_dur, label="blockA")
    block_b = concat_scenes(block_b_wavs, target_duration=block_b_dur, label="blockB")

    print("[3/4] Composing intro logo + block A + mid splash + block B…")
    final = compose_final(block_a, block_b)

    final_duration = probe_duration(final)
    print(f"[4/4] Done — {final} ({final_duration:.1f}s)")


if __name__ == "__main__":
    main()
