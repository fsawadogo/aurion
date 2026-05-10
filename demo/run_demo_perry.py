#!/usr/bin/env python3
"""
Dr. Perry demo runner — login flow (vs. registration flow in run_demo.py).

Two phases:
  Phase 1 (silent): Fresh install → login as perry@creoq.ca → skip
    onboarding → reach dashboard. This sets `aurion.onboarding_complete`
    and `aurion.profile_setup_complete` per-user UserDefaults flags so
    the next login skips onboarding entirely.
  Phase 2 (recorded): Wipe keychain (logs out, keeps UserDefaults) →
    login as Perry → straight to dashboard → tour Profile tab → start
    encounter → consent → record → Stage 1 review.

The recorder script wraps Phase 2 only, so the master.mp4 captures the
clean Perry flow without the silent setup pass.
"""

from __future__ import annotations
import json, os, subprocess, sys, time

UDID = os.environ.get("AURION_UDID", "64B2A3A9-1943-4BEA-8FF8-6C4E8AF51111")
BUNDLE = "com.faical.aurion"
APP = "/Users/fsawadogo/Library/Developer/Xcode/DerivedData/Aurion-dublmqatvhuacuevthwsymtdcdtk/Build/Products/Debug-iphonesimulator/Aurion.app"
EMAIL = "perry@creoq.ca"
PASSWORD = "perry"


def idb(*args, check=True, capture=True):
    cmd = ["idb", *args, "--udid", UDID]
    res = subprocess.run(cmd, capture_output=capture, text=True)
    if check and res.returncode != 0:
        raise SystemExit(f"idb failed: {' '.join(cmd)}\n{res.stderr}")
    return res.stdout


def simctl(*args, check=True):
    cmd = ["xcrun", "simctl", *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0 and "found nothing" not in res.stderr:
        # Tolerate "nothing to terminate" etc.
        print(f"  simctl warn: {res.stderr.strip()}")
    return res.stdout


def describe():
    return json.loads(idb("ui", "describe-all"))


def find(label, exact=False, kind=None):
    needle = label.lower()
    for el in describe():
        if kind and el.get("type") != kind:
            continue
        ax = (el.get("AXLabel") or "").lower()
        if (ax == needle) if exact else (needle in ax):
            return el
    return None


def tap(x, y, dur=0.12):
    idb("ui", "tap", "--duration", str(dur), str(x), str(y))


def tap_label(label, exact=False, kind=None, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        el = find(label, exact=exact, kind=kind)
        if el:
            f = el["frame"]
            x, y = int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2)
            tap(x, y)
            print(f"  tapped {'=' if exact else '~'} {label!r} @ ({x},{y})")
            return
        time.sleep(0.3)
    raise SystemExit(f"timeout: {label!r}")


def wait_for(label, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if find(label):
            return
        # auto-grant any system Allow prompt
        for el in describe():
            if el.get("type") == "Button" and (el.get("AXLabel") or "").lower() == "allow":
                f = el["frame"]
                tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
                print("  (auto-granted Allow)")
                time.sleep(0.6)
                break
        time.sleep(0.3)
    raise SystemExit(f"timeout waiting for {label!r}")


def shot(name):
    path = f"/tmp/aurion-demo/{name}.png"
    subprocess.run(["xcrun", "simctl", "io", UDID, "screenshot", path],
                   check=True, capture_output=True)


def section(title):
    print(f"\n=== {title} ===")


def grant_pending_permissions(rounds=10):
    for _ in range(rounds):
        time.sleep(0.4)
        for el in describe():
            if el.get("type") == "Button" and (el.get("AXLabel") or "").lower() == "allow":
                f = el["frame"]
                tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
                print("  granted Allow")
                time.sleep(0.6)
                break
        else:
            return


def login_as_perry():
    """Type Perry's credentials into the login screen.
    Uses triple-tap-to-select-all so any pre-filled text in the field
    (placeholder rendering or stale value) is replaced cleanly. Tapping
    once focuses; three taps select; then `text` replaces selection."""
    wait_for("Sign In")
    time.sleep(1.5)
    # Email — triple-tap to select-all, then type to replace
    for _ in range(3):
        idb("ui", "tap", "--duration", "0.05", "200", "402")
    time.sleep(0.3)
    idb("ui", "text", EMAIL)
    time.sleep(0.4)
    # Password — same pattern
    for _ in range(3):
        idb("ui", "tap", "--duration", "0.05", "200", "482")
    time.sleep(0.3)
    idb("ui", "text", PASSWORD)
    time.sleep(0.4)
    tap_label("Sign In", exact=True)


# ── Phase 1 — silent setup ───────────────────────────────────────────────


def phase1_setup():
    section("Phase 1 — silent onboarding skip for Perry")
    # Reset everything
    simctl("terminate", UDID, BUNDLE)
    simctl("uninstall", UDID, BUNDLE)
    simctl("keychain", UDID, "reset")
    simctl("install", UDID, APP)
    simctl("launch", UDID, BUNDLE)
    time.sleep(3)
    grant_pending_permissions(rounds=4)

    login_as_perry()
    # Pair wearable → Skip
    wait_for("Connect Your Glasses")
    time.sleep(1.0)
    tap_label("Skip")  # "Skip — Use Phone Camera"
    # Voice intro → Skip for now
    wait_for("Help Aurion recognize your voice")
    time.sleep(1.0)
    tap_label("Skip for now", exact=True)
    # Profile setup → tap Skip in the header (top right)
    wait_for("What type of practice")
    time.sleep(1.0)
    tap_label("Skip", exact=True)
    # Should now be on dashboard
    wait_for("New Patient", timeout=15)
    time.sleep(1.5)
    print("  ✓ Perry is on dashboard, onboarding flags persisted")


def force_logout_keep_flags():
    """Wipe keychain (logs out) but keep UserDefaults flags. Auth flag
    in UserDefaults is also cleared by AppState.clearAuth(), but since the
    app process is alive when we kill it, we need to also flip the
    aurion.is_authenticated bit in the simulator's shared defaults."""
    section("Force logout (keep onboarding flags)")
    simctl("terminate", UDID, BUNDLE)
    # Reset keychain — clears the auth token. AppState reads
    # `defaults.bool(auth) && hasToken`, so missing token → unauth.
    simctl("keychain", UDID, "reset")
    # Also clear the UserDefaults auth flag so AppState doesn't try to
    # auto-restore. Use `simctl spawn defaults` to write into the app's
    # NSUserDefaults plist within the simulator container.
    simctl("spawn", UDID, "defaults", "write", BUNDLE,
           "aurion.is_authenticated", "-bool", "NO")
    print("  ✓ keychain reset + auth flag cleared")


# ── Phase 2 — recorded run ────────────────────────────────────────────────


def phase2_record():
    section("Phase 2 — recorded Perry flow")
    simctl("launch", UDID, BUNDLE)
    time.sleep(3)
    grant_pending_permissions(rounds=4)

    login_as_perry()

    # With Perry's onboarding flags set, this should land on dashboard.
    wait_for("New Patient", timeout=20)
    time.sleep(2.5)
    shot("perry-01-dashboard")
    print("  ✓ Perry on dashboard (onboarding skipped)")

    # ── Profile tab tour ──────────────────────────────────────────────
    section("Profile tab tour")
    tap_label("Profile", exact=True, kind="Button")
    time.sleep(2.0)
    shot("perry-02-profile-top")
    # Slow scroll down to show practice / specialty / templates / team /
    # devices / language
    for i in range(3):
        idb("ui", "swipe", "540", "1300", "540", "500", "--duration", "0.6")
        time.sleep(1.5)
    shot("perry-03-profile-mid")
    # back to top
    for _ in range(3):
        idb("ui", "swipe", "540", "500", "540", "1300", "--duration", "0.6")
        time.sleep(0.8)

    # ── Back to home + start an encounter ─────────────────────────────
    section("Start encounter")
    tap_label("Home", exact=True, kind="Button")
    time.sleep(1.5)
    # Perry has a backlog of pending-review sessions that push the quickstart
    # cards below the fold. Scroll down so "New Patient" is hit-tappable.
    idb("ui", "swipe", "540", "1400", "540", "300", "--duration", "0.8")
    time.sleep(1.0)
    idb("ui", "swipe", "540", "1400", "540", "300", "--duration", "0.8")
    time.sleep(1.5)
    tap_label("New Patient")
    time.sleep(1.5)
    # Encounter type sheet
    tap_label("With Team Member")
    time.sleep(1.5)
    # Perry has Sarah Chen in his allied health team — should appear
    # automatically. If a checkbox row is rendered, tap it to select.
    sarah = find("Sarah")
    if sarah:
        f = sarah["frame"]
        tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
        time.sleep(0.5)
    tap_label("Continue", exact=True)
    # Context sheet — capture mode picker + context field
    wait_for("Capture mode")
    time.sleep(1.5)
    shot("perry-04-context-multimodal")
    tap_label("Audio Only")
    time.sleep(1.2)
    tap_label("Smart Dictation")
    time.sleep(1.2)
    tap_label("Multimodal")
    time.sleep(1.0)
    el = find("e.g. Right knee pain")
    if el:
        f = el["frame"]
        tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
        time.sleep(0.5)
        idb("ui", "text", "Right knee pain — 1 year, post soccer injury")
        time.sleep(0.6)
    tap_label("Start Session")

    # ── Consent + record ──────────────────────────────────────────────
    section("Consent + record")
    wait_for("Confirm Patient Consent")
    time.sleep(2.0)
    shot("perry-05-consent")
    tap_label("Patient Has Consented")
    grant_pending_permissions(rounds=10)
    wait_for("Recording", timeout=15)
    time.sleep(2.5)
    shot("perry-06-capture")
    tap(201, 760, dur=0.18)  # gold record button
    grant_pending_permissions(rounds=15)
    time.sleep(2.0)
    grant_pending_permissions(rounds=4)
    time.sleep(12.0)
    shot("perry-07-recording")
    tap(298, 760, dur=0.18)  # stop
    time.sleep(3.0)

    # ── Generate note + Stage 1 ───────────────────────────────────────
    section("Generate note + Stage 1")
    wait_for("Generate Note", timeout=15)
    time.sleep(2.0)
    shot("perry-08-post-encounter")
    tap_label("Generate Note", exact=True, kind="Button")
    wait_for("Note Ready", timeout=120)
    time.sleep(1.5)
    shot("perry-09-note-ready")
    tap_label("Review Now")
    wait_for("Approve", timeout=20)
    # Dwell on Stage 1 long enough that the master has 25+ seconds of clean
    # review-screen footage to back the MULTIMODAL + FINAL OUTPUT VO sections.
    # Slow scroll cycle: hold → scroll → hold → scroll → hold → scroll back.
    time.sleep(4.0)
    shot("perry-10-stage1-top")
    # Slow first scroll
    idb("ui", "swipe", "200", "700", "200", "350", "--duration", "1.2")
    time.sleep(3.0)
    shot("perry-11-stage1-mid")
    # Second scroll
    idb("ui", "swipe", "200", "700", "200", "350", "--duration", "1.2")
    time.sleep(3.0)
    shot("perry-12-stage1-deeper")
    # Third scroll
    idb("ui", "swipe", "200", "700", "200", "350", "--duration", "1.2")
    time.sleep(3.0)
    # Scroll back to top so the closing shot shows section overview
    idb("ui", "swipe", "200", "350", "200", "700", "--duration", "1.0")
    idb("ui", "swipe", "200", "350", "200", "700", "--duration", "1.0")
    idb("ui", "swipe", "200", "350", "200", "700", "--duration", "1.0")
    time.sleep(4.0)
    shot("perry-13-stage1-final")
    print("  ✓ Stage 1 dwell captured (~25s of review content)")


def main():
    phase1_setup()
    force_logout_keep_flags()
    print("\n*** Phase 2 (recorded) — start video recording NOW. Sleeping 3s. ***")
    time.sleep(3)
    phase2_record()
    print("\n✓ Done.")


if __name__ == "__main__":
    main()
