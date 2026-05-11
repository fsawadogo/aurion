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

# Wall-clock anchor for Phase 2 — set when the recordVideo subprocess
# attaches, then every milestone in phase2_record is paced against it via
# wait_until(t). The trim script reads milestones.json and lifts each
# scene from the master at the wall-clock window between two anchors.
REC_T0 = None
MILESTONES: list[tuple[str, float]] = []


def now_rel() -> float:
    """Seconds since the recording subprocess attached (REC_T0)."""
    return 0.0 if REC_T0 is None else (time.time() - REC_T0)


def mark(name: str) -> float:
    """Record a milestone at the current wall-clock time. Returns the
    relative seconds since REC_T0 for logging."""
    t = now_rel()
    MILESTONES.append((name, t))
    print(f"  ⟢ milestone [{name}] @ {t:.2f}s", flush=True)
    return t


def wait_until(t: float) -> None:
    """Sleep until `t` seconds have elapsed since REC_T0. Prints a warning
    if we're already past the target (action ran longer than budgeted)."""
    delta = t - now_rel()
    if delta < 0:
        print(f"  ⚠ wait_until({t:.2f}) — already at {now_rel():.2f}s "
              f"(overran by {-delta:.2f}s)", flush=True)
        return
    time.sleep(delta)


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


def wait_for_optional(label, timeout=6.0) -> bool:
    """Like wait_for, but returns False on timeout instead of crashing.
    Used for onboarding screens that may be skipped automatically if the
    user's UserDefaults flags are already set from a prior install."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if find(label):
            return True
        for el in describe():
            if el.get("type") == "Button" and (el.get("AXLabel") or "").lower() == "allow":
                f = el["frame"]
                tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
                time.sleep(0.4)
                break
        time.sleep(0.3)
    return False


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
    Resolves the email + password TextField positions dynamically via
    accessibility so the script keeps working when the UI is restyled
    (the login form moves vertically with the logo block / safe area).
    """
    wait_for("Sign In")
    time.sleep(1.5)

    fields = [el for el in describe() if el.get("type") == "TextField"]
    if len(fields) < 2:
        raise SystemExit(f"login form expected ≥2 TextFields, found {len(fields)}")
    # The login view stacks Email above Password — sort top-to-bottom.
    fields.sort(key=lambda el: el["frame"]["y"])
    email_f, pass_f = fields[0]["frame"], fields[1]["frame"]
    ex, ey = int(email_f["x"] + email_f["width"] / 2), int(email_f["y"] + email_f["height"] / 2)
    px, py = int(pass_f["x"] + pass_f["width"] / 2), int(pass_f["y"] + pass_f["height"] / 2)
    print(f"  login fields: email @({ex},{ey})  password @({px},{py})")

    # Email — triple-tap to select-all, then type to replace any stale
    # placeholder/value left from the previous session.
    for _ in range(3):
        idb("ui", "tap", "--duration", "0.05", str(ex), str(ey))
    time.sleep(0.3)
    idb("ui", "text", EMAIL)
    time.sleep(0.4)
    # Password — same pattern
    for _ in range(3):
        idb("ui", "tap", "--duration", "0.05", str(px), str(py))
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
    # Onboarding pages are optional — if Perry's onboarding flags were
    # somehow preserved we may land straight on dashboard. wait_for_optional
    # lets each step skip gracefully.
    if wait_for_optional("Connect Your Glasses", timeout=8):
        time.sleep(0.8)
        tap_label("Skip")  # "Skip — Use Phone Camera"
    if wait_for_optional("Help Aurion recognize your voice", timeout=6):
        time.sleep(0.8)
        tap_label("Skip for now", exact=True)
    if wait_for_optional("What type of practice", timeout=6):
        time.sleep(0.8)
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
    """Recorded run — deliberately paced so each screen lines up with the
    matching narration sentence in the final video.

    Every meaningful screen transition gets a `mark("name")` so the trim
    script can lift the right window out of master.mp4. The narration is
    locked in audio/narration.wav (~128 s) and starts +4 s into the
    composition timeline (intro card), so the master-time targets below
    correspond to (composition_time − 4 + 2) where +2 is the recordVideo
    attach buffer.

    Scene boundaries (composition time → master target):
      s1-intro        4.0 → M2.0  (login → dashboard)
      s2-profile     12.5 → M10.5 (profile top + scroll templates/langs/devices)
      s3-capture     30.2 → M28.2 (capture mode picker — 3 options)
      s4-encounter   43.5 → M41.5 (back, New Patient, team, context, start)
      s5-recording   63.5 → M61.5 (recording dwell)
      s6-live-note   83.0 → M81.0 (stop → Note Ready)
      s7-multimodal  92.5 → M_review (Stage 1 review top + scroll)
      s8-final      111.0 → M_review+18.5 (continue scrolling + approve)
      s9-ending     128.0 → M_review+35.5 (final state)
    """
    section("Phase 2 — recorded Perry flow")
    mark("rec_attached")
    simctl("launch", UDID, BUNDLE)
    time.sleep(2.5)
    grant_pending_permissions(rounds=4)
    mark("login_visible")

    # ── s1-intro window — login flow + transition to dashboard ────────
    # Target: dashboard visible by M=10s (so s1 covers M2–M10.5).
    login_as_perry()
    wait_for("New Patient", timeout=20)
    mark("dashboard_visible")
    wait_until(10.5)
    shot("perry-01-dashboard")

    # ── s2-profile window — Profile tab tour ──────────────────────────
    # Target window: M10.5–M28.2 (17.7s of profile content). Show top,
    # then 3 slow scrolls landing on templates, languages, devices.
    section("Profile tab tour")
    tap_label("Profile", exact=True, kind="Button")
    mark("profile_open")
    wait_until(13.5)
    shot("perry-02-profile-top")
    # Dwell on top for ~3s — VO is saying "physician profile"
    wait_until(17.0)
    # Slow scroll #1 — reveal templates / preferred visit types
    idb("ui", "swipe", "540", "1300", "540", "650", "--duration", "0.9")
    wait_until(20.5)
    shot("perry-02b-templates")
    # Slow scroll #2 — languages / recording prefs
    idb("ui", "swipe", "540", "1300", "540", "650", "--duration", "0.9")
    wait_until(24.0)
    shot("perry-02c-langs")
    # Slow scroll #3 — connected devices
    idb("ui", "swipe", "540", "1300", "540", "650", "--duration", "0.9")
    wait_until(27.5)
    shot("perry-02d-devices")
    # Tiny pause before navigating away — gives a clean s2 cut frame
    wait_until(28.0)

    # ── s3-capture-mode window — pick capture mode in encounter sheet ─
    # Target window: M28.2–M41.5 (13.3s). Navigate Home → New Patient →
    # With Team Member → Sarah → Continue → Context sheet, then dwell on
    # the capture mode picker tapping Audio Only → Smart Dictation →
    # Multimodal so each option is briefly highlighted as the VO names it.
    section("Capture mode picker")
    tap_label("Home", exact=True, kind="Button")
    # The dashboard may have a long pending-review list pushing the
    # quickstart below the fold — scroll up to bring New Patient on screen.
    idb("ui", "swipe", "540", "1400", "540", "400", "--duration", "0.7")
    idb("ui", "swipe", "540", "1400", "540", "400", "--duration", "0.7")
    tap_label("New Patient")
    tap_label("With Team Member")
    sarah = find("Sarah")
    if sarah:
        f = sarah["frame"]
        tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
    tap_label("Continue", exact=True)
    wait_for("Capture mode")
    mark("capture_mode_visible")
    shot("perry-03-capture-top")
    # 3 capture mode options highlighted in sequence — line up with VO
    # "smart dictation, audio only, or multimodal".
    wait_until(33.0)
    tap_label("Audio Only")
    wait_until(35.5)
    tap_label("Smart Dictation")
    wait_until(38.0)
    tap_label("Multimodal")
    shot("perry-03b-multimodal-active")
    # Slight pause before s3 cut
    wait_until(41.0)

    # ── s4-encounter window — finish context + consent ────────────────
    # Target window: M41.5–M61.5 (20s). Type the chief complaint, tap
    # Start Session, consent screen, confirm consent.
    section("Encounter context + consent")
    el = find("e.g. Right knee pain")
    if el:
        f = el["frame"]
        tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
        time.sleep(0.4)
        idb("ui", "text", "Right knee pain — 1 year, post soccer injury")
    mark("context_typed")
    wait_until(47.0)
    shot("perry-04-context")
    tap_label("Start Session")
    wait_for("Confirm Patient Consent")
    mark("consent_visible")
    wait_until(53.0)
    shot("perry-05-consent")
    tap_label("Patient Has Consented")
    grant_pending_permissions(rounds=10)
    wait_for("Recording", timeout=15)
    mark("recording_screen_ready")
    wait_until(60.5)
    shot("perry-06-pre-record")

    # ── s5-recording window — 20s of recording dwell ──────────────────
    # Target window: M61.5–M81.0 (19.5s). Tap record, hold for ~18s
    # showing waveform + camera preview, then tap stop right at the end.
    section("Recording dwell")
    tap(201, 760, dur=0.18)  # gold record button
    mark("record_started")
    grant_pending_permissions(rounds=15)
    wait_until(80.5)
    shot("perry-07-recording")
    tap(298, 760, dur=0.18)  # stop button
    mark("record_stopped")

    # ── Generate Note → Note Ready (real time, will be compressed) ────
    # The ML pipeline takes 20-60s. We trim that out — only the very tail
    # of this window appears in the final video (s6-live-note = the
    # "Note Ready" notification + tap → Stage 1 entry).
    section("Generate note + Stage 1")
    wait_for("Generate Note", timeout=20)
    time.sleep(1.0)
    shot("perry-08-post-encounter")
    tap_label("Generate Note", exact=True, kind="Button")
    mark("generate_tapped")
    wait_for("Note Ready", timeout=120)
    mark("note_ready")
    time.sleep(1.5)
    shot("perry-09-note-ready")
    tap_label("Review Now")
    wait_for("Approve", timeout=20)
    mark("stage1_open")

    # ── s7+s8 — Stage 1 review scrolling (target ~36s total) ──────────
    # The s7 (multimodal) + s8 (final) clips both come from this dwell.
    # Slow scroll cycle: hold → scroll → hold → scroll → hold → return.
    time.sleep(4.0)
    shot("perry-10-stage1-top")
    idb("ui", "swipe", "200", "750", "200", "350", "--duration", "1.4")
    time.sleep(4.0)
    shot("perry-11-stage1-mid")
    idb("ui", "swipe", "200", "750", "200", "350", "--duration", "1.4")
    time.sleep(4.0)
    shot("perry-12-stage1-deeper")
    idb("ui", "swipe", "200", "750", "200", "350", "--duration", "1.4")
    time.sleep(4.0)
    # Scroll back toward top so the final shot shows the section overview
    idb("ui", "swipe", "200", "350", "200", "750", "--duration", "1.2")
    idb("ui", "swipe", "200", "350", "200", "750", "--duration", "1.2")
    time.sleep(3.0)
    shot("perry-13-stage1-final")
    # ── s9-ending — Approve & Sign for the closing beat ───────────────
    # Keep dwelling on the approved state long enough that the trim
    # script can lift a clean 4 s closing clip out of master.mp4 without
    # running off the end. The post-approve "Note Approved" toast is a
    # static frame, so 10 s of dwell is plenty.
    approve = find("Approve")
    if approve:
        f = approve["frame"]
        tap(int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2))
        mark("approve_tapped")
        time.sleep(2.5)
        shot("perry-14-approved")
        # Hold on the approved state — gives master room for s8 tail +
        # full 4 s s9-ending clip.
        time.sleep(10.0)
        mark("approve_dwell_end")
    print("  ✓ Stage 1 dwell + approve captured")


def main():
    global REC_T0
    phase1_setup()
    force_logout_keep_flags()

    out_path = os.environ.get(
        "AURION_MASTER_PATH",
        "/Users/fsawadogo/Documents/GitHub/Aurion/demo/master.mp4",
    )
    milestones_path = os.environ.get(
        "AURION_MILESTONES_PATH",
        "/Users/fsawadogo/Documents/GitHub/Aurion/demo/milestones.json",
    )
    if os.path.exists(out_path):
        os.remove(out_path)
    if os.path.exists(milestones_path):
        os.remove(milestones_path)

    # Start recording in a subprocess BEFORE phase2 begins. SIGINT to stop and
    # finalize the .mp4. No buffer race — recording starts and stops inline.
    print(f"\n*** Phase 2 — starting recordVideo → {out_path} ***", flush=True)
    rec = subprocess.Popen(
        ["xcrun", "simctl", "io", UDID, "recordVideo",
         "--codec=h264", "--force", out_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2.0)  # give recordVideo a moment to attach
    REC_T0 = time.time()  # ← anchor: everything in phase2 is paced from here
    try:
        phase2_record()
    finally:
        print("  stopping recordVideo (SIGINT)…", flush=True)
        rec.send_signal(2)  # SIGINT → graceful finalize
        try:
            rec.wait(timeout=10)
        except subprocess.TimeoutExpired:
            rec.terminate()
            rec.wait(timeout=5)
        if os.path.exists(out_path):
            size_mb = os.path.getsize(out_path) / (1024 * 1024)
            print(f"  ✓ master.mp4 written ({size_mb:.1f} MB) → {out_path}",
                  flush=True)
        else:
            print("  ⚠️  master.mp4 not found — recordVideo failed", flush=True)
        # Persist milestones so the trim script can lift each scene out
        # of master.mp4 at exactly the right window.
        with open(milestones_path, "w") as fh:
            json.dump(
                {"rec_t0": REC_T0, "milestones": MILESTONES},
                fh,
                indent=2,
            )
        print(f"  ✓ milestones.json written ({len(MILESTONES)} entries) "
              f"→ {milestones_path}", flush=True)
    print("\n✓ Done.")


if __name__ == "__main__":
    main()
