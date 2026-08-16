"""Capture one end-to-end run of the knee visit into the local eval harness.

The harness is deliberately OUTSIDE the PeriTwin app: it is a plain folder of
JSON plus a static page, so a run is reviewable without a server, a login, or
the pipeline being up.

Three artefacts per run, which is the comparison the loop needs:
  * ``/notes/{id}/stage1``  -> the AUDIO-ONLY note (before Stage 2 merges vision)
  * ``/notes/{id}/full``    -> the VISION-ENRICHED note
  * ``/notes/{id}/detail``  -> transcript + frame citations (for citation checks)

Usage:
    set AURION_TOKEN=<aurion_token cookie value>
    python capture.py --session <uuid> --label "gemini-2.5-pro, MSK template"

The token is the ``aurion_token`` cookie from the portal. It is read from the
environment and never written into a run file.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import sys
import urllib.request

HERE = pathlib.Path(__file__).parent
RUNS = HERE / "runs"
API = os.getenv("AURION_API", "https://api-dev.aurionclinical.com/api/v1")


def _get(path: str, token: str):
    """GET a JSON endpoint. Returns (status, parsed_or_text)."""
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # noqa: PERF203 — want the body
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def rebuild_runs_js() -> int:
    """Regenerate runs.js from answer-key.json + every runs/*.json.

    A .js file (not .json) so index.html works from file:// with no server —
    fetch() would be blocked by CORS, a script tag is not.
    """
    key = json.loads((HERE / "answer-key.json").read_text(encoding="utf-8"))
    runs = []
    for f in sorted(RUNS.glob("*.json")):
        runs.append(json.loads(f.read_text(encoding="utf-8")))
    runs.sort(key=lambda r: r.get("captured_at", ""), reverse=True)
    body = (
        "window.ANSWER_KEY = "
        + json.dumps(key, ensure_ascii=False)
        + ";\nwindow.RUNS = "
        + json.dumps(runs, ensure_ascii=False)
        + ";\n"
    )
    io.open(HERE / "runs.js", "w", encoding="utf-8").write(body)
    return len(runs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="session UUID from the portal")
    ap.add_argument("--label", default="", help="short label for this run")
    ap.add_argument("--captured-at", default="", help="timestamp (else supplied by caller)")
    ap.add_argument("--rebuild-only", action="store_true", help="just regenerate runs.js")
    args = ap.parse_args()

    RUNS.mkdir(exist_ok=True)

    if args.rebuild_only or not args.session:
        n = rebuild_runs_js()
        print(f"runs.js rebuilt — {n} run(s). Open index.html.")
        return 0

    token = os.getenv("AURION_TOKEN", "").strip()
    if not token:
        print("AURION_TOKEN not set. Copy the aurion_token cookie from the portal.")
        return 2

    sid = args.session
    print(f"capturing {sid[:8]} ...")

    st_s, stage1 = _get(f"/notes/{sid}/stage1", token)
    st_f, full = _get(f"/notes/{sid}/full", token)
    st_d, detail = _get(f"/notes/{sid}/detail", token)
    print(f"  stage1={st_s}  full={st_f}  detail={st_d}")

    if st_s != 200 and st_f != 200:
        print("  nothing to capture — is the session past Stage 1?")
        print(f"  stage1 said: {stage1}")
        return 1

    run = {
        "session_id": sid,
        "label": args.label or sid[:8],
        "captured_at": args.captured_at or "",
        "note_audio": stage1 if st_s == 200 else None,
        "note_vision": full if st_f == 200 else None,
        "detail": detail if st_d == 200 else None,
        "provider_note": (full or stage1 or {}).get("provider_used")
        if isinstance(full or stage1, dict)
        else None,
        "template_key": (full or stage1 or {}).get("specialty")
        if isinstance(full or stage1, dict)
        else None,
    }
    stem = (args.captured_at or sid[:8]).replace(":", "-").replace(" ", "_")
    out = RUNS / f"{stem}-{sid[:8]}.json"
    io.open(out, "w", encoding="utf-8").write(json.dumps(run, ensure_ascii=False, indent=1))
    print(f"  wrote {out.name}")

    n = rebuild_runs_js()
    print(f"runs.js rebuilt — {n} run(s). Open index.html.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
