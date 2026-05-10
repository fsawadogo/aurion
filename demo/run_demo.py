#!/usr/bin/env python3
"""
End-to-end Aurion demo runner. Drives the iOS Simulator from login through
final note via idb so a video recorder running in parallel captures the
entire journey.

Usage:
    python3 run_demo.py

Prereqs (already done in this session):
    - Simulator booted at $UDID
    - App freshly installed (no auth state)
    - idb companion connected
    - Backend running at localhost:8080

The runner explicitly avoids substring-matching pitfalls (e.g. "Don't Allow"
matching for "Allow") by either tapping by exact label or by coordinate.
"""

from __future__ import annotations
import json, os, subprocess, sys, time

UDID = "64B2A3A9-1943-4BEA-8FF8-6C4E8AF51111"


def idb(*args, check=True, capture=True):
    cmd = ["idb", *args, "--udid", UDID]
    res = subprocess.run(cmd, capture_output=capture, text=True)
    if check and res.returncode != 0:
        raise SystemExit(f"idb failed: {' '.join(cmd)}\n{res.stderr}")
    return res.stdout


def describe():
    return json.loads(idb("ui", "describe-all"))


def tap(x: int, y: int, dur: float = 0.12):
    idb("ui", "tap", "--duration", str(dur), str(x), str(y))


def find(label: str, exact: bool = False, kind: str | None = None) -> dict | None:
    needle = label.lower()
    for el in describe():
        if kind and el.get("type") != kind:
            continue
        ax = (el.get("AXLabel") or "").lower()
        if (ax == needle) if exact else (needle in ax):
            return el
    return None


def find_exact(label: str) -> dict | None:
    return find(label, exact=True)


def tap_label(label: str, exact: bool = False, kind: str | None = None,
              timeout: float = 8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        el = find(label, exact=exact, kind=kind)
        if el:
            f = el["frame"]
            x, y = int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2)
            tap(x, y)
            print(f"  tapped {'='*1 if exact else '~'} {label!r} @ ({x},{y})")
            return
        time.sleep(0.3)
    raise SystemExit(f"timeout: could not find {label!r}")


def wait_for(label: str, timeout: float = 10.0):
    """Wait for `label` to appear. Auto-dismisses iOS system permission
    prompts that block the underlying view (mic / camera / speech). Without
    this sweep, a prompt that fires asynchronously would freeze the flow."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if find(label):
            return
        # Sweep system Allow prompts each poll cycle — exact-match only so
        # we never pick "Don't Allow".
        for el in describe():
            if el.get("type") == "Button" and (el.get("AXLabel") or "").lower() == "allow":
                f = el["frame"]
                tap(int(f["x"] + f["width"] / 2),
                    int(f["y"] + f["height"] / 2))
                print("  (auto-granted Allow prompt during wait)")
                time.sleep(0.6)
                break
        time.sleep(0.3)
    raise SystemExit(f"timeout waiting for {label!r}")


def shot(name: str):
    path = f"/tmp/aurion-demo/{name}.png"
    subprocess.run(["xcrun", "simctl", "io", UDID, "screenshot", path],
                   check=True, capture_output=True)


def section(title: str):
    print(f"\n=== {title} ===")


def grant_pending_permissions(rounds: int = 6):
    """Tap any visible iOS system 'Allow' button. Permissions for mic /
    camera / speech are requested at runtime by the app when consent is
    confirmed, so we sweep for them once after entering the capture screen."""
    for _ in range(rounds):
        time.sleep(0.4)
        for el in describe():
            if el.get("type") != "Button":
                continue
            ax = (el.get("AXLabel") or "").lower()
            if ax == "allow":
                f = el["frame"]
                tap(int(f["x"] + f["width"] / 2),
                    int(f["y"] + f["height"] / 2))
                print("  granted system Allow prompt")
                time.sleep(0.8)
                break
        else:
            return  # no Allow button found this round → done


# ── The journey ────────────────────────────────────────────────────────────


def login_and_register():
    section("Register new account")
    wait_for("Sign In")
    time.sleep(1.5)  # give the splash time to fade
    tap_label("Create account")
    wait_for("Create your account")
    time.sleep(0.8)

    # Four fields, top-to-bottom: name, email, password, confirm
    email = f"demo{int(time.time())}@aurion.health"
    fields = [
        (62, 296, "Dr. Demo Roberts"),
        (62, 377, email),
        (62, 457, "Demo1234!"),
        (62, 536, "Demo1234!"),
    ]
    for x, y, txt in fields:
        tap(x, y)
        time.sleep(0.25)
        idb("ui", "text", txt)
        time.sleep(0.3)
    print(f"  registered as {email}")
    shot("01-register-filled")
    # Submit
    tap_label("Create Account", exact=True)


def pair_wearable():
    section("Pair wearable")
    wait_for("Connect Your Glasses")
    time.sleep(1.5)
    shot("02-pair-intro")
    tap_label("Scan for Devices")
    wait_for("Ray-Ban Meta Wayfarer")
    time.sleep(1.5)
    shot("03-pair-list")
    tap_label("Ray-Ban Meta Wayfarer")
    time.sleep(2.0)


def skip_voice():
    section("Skip voice enrollment")
    wait_for("Help Aurion recognize your voice")
    time.sleep(1.5)
    shot("04-voice-intro")
    tap_label("Skip for now", exact=True)


def profile_setup():
    section("Profile setup — 6 steps")
    wait_for("What type of practice")
    time.sleep(1.0)
    shot("05-step-practice")
    tap_label("Continue", exact=True)

    wait_for("Primary specialty")
    time.sleep(0.7)
    shot("06-step-specialty")
    tap_label("Continue", exact=True)

    wait_for("Common visit types")
    time.sleep(0.7)
    shot("07-step-visits")
    tap_label("Continue", exact=True)

    wait_for("Preferred templates")
    time.sleep(0.7)
    shot("08-step-templates")
    # Tap the orthopedic_surgery row (gold check the most likely template)
    el = find("Orthopedic Surgery")
    if el:
        f = el["frame"]
        tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
        time.sleep(0.5)
    tap_label("Continue", exact=True)

    wait_for("Output language")
    time.sleep(0.7)
    shot("09-step-language")
    tap_label("Continue", exact=True)

    wait_for("Recording preferences")
    time.sleep(1.5)
    shot("10-step-prefs")
    # Settle on default prefs and finish
    tap_label("Get Started", exact=True)


def start_encounter():
    section("Start an encounter")
    wait_for("New Patient", timeout=15)
    time.sleep(2.0)
    shot("11-dashboard")
    # Quickstart card label is e.g. "Orthopedic Surgery, New Patient" — match
    # by substring rather than exact.
    tap_label("New Patient")

    wait_for("Who")
    time.sleep(1.0)
    shot("12-encounter-type")
    tap_label("With Team Member")
    time.sleep(1.0)
    shot("13-encounter-team")
    # Continue to context
    tap_label("Continue", exact=True)

    wait_for("Capture mode")
    time.sleep(1.5)
    shot("14-context-multimodal")
    # Demo the picker by tapping each option in turn so the VO has visual
    # variety: tap Audio Only, then Smart Dictation, then back to Multimodal.
    tap_label("Audio Only")
    time.sleep(1.2)
    shot("15-context-audio-only")
    tap_label("Smart Dictation")
    time.sleep(1.2)
    shot("16-context-smart-dictation")
    tap_label("Multimodal")
    time.sleep(1.2)
    # Type some context
    el = find("e.g. Right knee pain")
    if el:
        f = el["frame"]
        tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
        time.sleep(0.5)
        idb("ui", "text", "Right knee pain — 1 year, post soccer injury")
        time.sleep(0.6)
    shot("17-context-typed")
    tap_label("Start Session")


def consent_and_record():
    section("Consent + record")
    wait_for("Confirm Patient Consent")
    time.sleep(2.0)
    shot("18-consent")
    tap_label("Patient Has Consented")
    # iOS fires mic / camera / speech prompts in sequence the first time the
    # capture pipeline runs. Speech in particular can take a couple seconds
    # to appear AFTER the record button is tapped, so we sweep aggressively
    # before the record tap, after, and again mid-recording.
    grant_pending_permissions(rounds=10)
    wait_for("Recording", timeout=15)
    time.sleep(2.5)
    shot("19-capture-pre-rec")
    tap(201, 760, dur=0.18)
    # Speech prompt is the slowest — sometimes ~3s after record tap. Sweep
    # for ~6s before settling into the demo timer footage.
    grant_pending_permissions(rounds=15)
    time.sleep(2.0)
    grant_pending_permissions(rounds=4)
    # Now record clean for ~12s — should be no more prompts after.
    time.sleep(12.0)
    shot("20-capture-recording")
    # Stop is the right circle (~ x=298, y=760)
    tap(298, 760, dur=0.18)
    time.sleep(3.0)


def post_encounter_and_note():
    section("Post-encounter → Stage 1")
    # Post-encounter screen: confirms template, language, then Generate Note
    wait_for("Generate Note", timeout=15)
    time.sleep(2.0)
    shot("22-post-encounter")
    # Two elements share this label: the nav-bar title (StaticText) and the
    # gold submit button (Button). Filter to Button so we hit the right one.
    tap_label("Generate Note", exact=True, kind="Button")
    # Anthropic Stage 1 generation takes ~8–15 s. Wait generously.
    wait_for("Note Ready", timeout=120)
    time.sleep(2.0)
    shot("23-note-ready")
    tap_label("Review Now")
    # Stage 1 review screen — sections + Approve button
    wait_for("Approve", timeout=20)
    time.sleep(2.5)
    shot("24-stage1-note")
    # Slow scroll through the note to give the VO content to land on
    for _ in range(3):
        idb("ui", "swipe", "200", "650", "200", "300", "--duration", "0.6")
        time.sleep(1.5)
    shot("25-stage1-scrolled")
    # Scroll back to top so Approve is on screen
    for _ in range(3):
        idb("ui", "swipe", "200", "300", "200", "650", "--duration", "0.6")
        time.sleep(0.8)


def stage2_and_final():
    section("Stage 2 → Final Note")
    # The Stage 1 review screen has an "Approve" button that triggers Stage 2.
    tap_label("Approve")
    # Stage 2 vision pipeline runs server-side; iOS shows a processing spinner.
    # Frames are empty (simulator has no camera), so vision returns no
    # citations but the pipeline still completes and the note transitions
    # to REVIEW_COMPLETE.
    time.sleep(3.0)
    shot("26-stage2-processing")
    # Wait for the final note view — usually < 30s without frames.
    wait_for("Approve", timeout=180)
    time.sleep(2.5)
    shot("27-final-note")
    # Slow scroll through the final note for the VO
    for _ in range(4):
        idb("ui", "swipe", "200", "650", "200", "300", "--duration", "0.6")
        time.sleep(1.5)
    shot("28-final-note-scrolled")


def main():
    login_and_register()
    pair_wearable()
    skip_voice()
    profile_setup()
    start_encounter()
    consent_and_record()
    try:
        post_encounter_and_note()
        stage2_and_final()
    except SystemExit as e:
        # Stage 1 / 2 require the backend's AURION_DEMO_TRANSCRIPT mode and
        # a working note-gen provider. If either fails, we capture the
        # deepest screen reached and exit cleanly without aborting the take.
        print(f"  (stopped: {e})")
    print("\n✓ Demo run complete.")


if __name__ == "__main__":
    main()
