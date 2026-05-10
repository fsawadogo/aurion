#!/usr/bin/env python3
"""
Idb-driven demo runner for Aurion. Drives the iOS Simulator via Meta's
`idb` so we can capture the demo journey end-to-end without manual taps.

Usage:
    python3 drive.py describe                # dump current screen elements
    python3 drive.py find "Sign In"         # find an element by label
    python3 drive.py tap "Sign In"          # tap by label
    python3 drive.py wait_for "Aurion" 10   # wait up to 10s for label
    python3 drive.py shot path.png          # screenshot
    python3 drive.py text "hello"           # type text into focused field

Composable building blocks for an end-to-end demo script.
"""

from __future__ import annotations
import json, os, subprocess, sys, time

UDID = os.environ.get("AURION_UDID", "64B2A3A9-1943-4BEA-8FF8-6C4E8AF51111")


def run(cmd: list[str], capture: bool = True, check: bool = True) -> str:
    full = ["idb"] + cmd + ["--udid", UDID]
    res = subprocess.run(full, capture_output=capture, text=True)
    if check and res.returncode != 0:
        raise SystemExit(f"idb failed ({res.returncode}): {' '.join(full)}\n{res.stderr}")
    return res.stdout


def describe() -> list[dict]:
    raw = run(["ui", "describe-all"])
    return json.loads(raw)


def find(label: str, kind: str | None = None) -> dict | None:
    """Find first element with an exact-or-substring label match. Optionally
    constrain by accessibility role (Button, StaticText, TextField, ...)."""
    needle = label.lower()
    for el in describe():
        if kind and el.get("type") != kind:
            continue
        ax = (el.get("AXLabel") or "")
        if needle == ax.lower() or needle in ax.lower():
            return el
    return None


def center(el: dict) -> tuple[int, int]:
    f = el["frame"]
    return int(f["x"] + f["width"] / 2), int(f["y"] + f["height"] / 2)


def tap_xy(x: int, y: int, duration: float = 0.12) -> None:
    """Tap at coordinates with a short hold — SwiftUI gesture recognizers
    miss the default ~0 ms idb tap, so we always use ~120 ms."""
    run(["ui", "tap", "--duration", str(duration), str(x), str(y)])


def tap_label(label: str, kind: str | None = None) -> None:
    el = find(label, kind)
    if not el:
        raise SystemExit(f"could not find element: {label!r}")
    x, y = center(el)
    tap_xy(x, y)
    print(f"tapped '{el.get('AXLabel')}' @ ({x},{y})")


def wait_for(label: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        el = find(label)
        if el:
            return el
        time.sleep(0.4)
    raise SystemExit(f"timeout waiting for {label!r}")


def text(s: str) -> None:
    run(["ui", "text", s])


def shot(path: str) -> None:
    subprocess.run(
        ["xcrun", "simctl", "io", UDID, "screenshot", path],
        check=True, capture_output=True,
    )


# ── CLI shim ───────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, args = argv[0], argv[1:]
    if cmd == "describe":
        for el in describe():
            ax = el.get("AXLabel") or ""
            t = el.get("type") or "?"
            f = el.get("frame", {})
            if ax and t != "Application":
                print(f"{t:>16} | {f.get('x',0):>4.0f},{f.get('y',0):>4.0f} {f.get('width',0):>4.0f}x{f.get('height',0):>4.0f} | {ax[:80]}")
    elif cmd == "find":
        el = find(args[0], args[1] if len(args) > 1 else None)
        print(json.dumps(el, indent=2) if el else "<not found>")
    elif cmd == "tap":
        tap_label(args[0], args[1] if len(args) > 1 else None)
    elif cmd == "wait_for":
        wait_for(args[0], float(args[1]) if len(args) > 1 else 10.0)
        print(f"found {args[0]!r}")
    elif cmd == "shot":
        shot(args[0])
        print(f"saved {args[0]}")
    elif cmd == "text":
        text(args[0])
    else:
        print(f"unknown: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
