"""Eval A — Audio-only pipeline end-to-end test.

Validates Journey 1 headlessly against the running backend:
1. Create session
2. Confirm consent
3. Start recording
4. Stop recording → triggers Stage 1
5. Verify health check + provider config
6. Check session state transitions

Run with: python scripts/test_pipeline.py
Requires: docker-compose up (backend on localhost:8080)
"""

import json
import sys
import time

import httpx

BASE_URL = "http://localhost:8080"
API = f"{BASE_URL}/api/v1"
TOKEN = "CLINICIAN"  # Dev token format: role

# Track results
results: list[dict] = []


def step(name: str, fn):
    """Run a test step and record pass/fail."""
    try:
        result = fn()
        results.append({"step": name, "status": "PASS", "detail": str(result)[:100]})
        print(f"  ✓ {name}")
        return result
    except Exception as e:
        results.append({"step": name, "status": "FAIL", "detail": str(e)[:200]})
        print(f"  ✗ {name}: {e}")
        return None


def headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }


def main():
    print("\n" + "=" * 60)
    print("AURION EVAL A — Audio-Only Pipeline Test")
    print("=" * 60 + "\n")

    client = httpx.Client(timeout=30.0)

    # ── Step 1: Health Check ──────────────────────────────────────
    print("1. Health Check")
    health = step("GET /health", lambda: client.get(f"{BASE_URL}/health").json())
    if not health:
        print("\n  Backend not reachable. Is docker-compose up?")
        sys.exit(1)

    step("Status is OK", lambda: assert_eq(health["status"], "ok"))
    step("Providers configured", lambda: assert_eq(
        set(health["providers"].keys()),
        {"transcription", "note_generation", "vision"}
    ))

    # ── Step 2: Create Session ────────────────────────────────────
    print("\n2. Create Session")
    session = step("POST /sessions", lambda: client.post(
        f"{API}/sessions",
        headers=headers(),
        json={"specialty": "orthopedic_surgery"},
    ).json())

    if not session:
        print("  Cannot continue without session.")
        sys.exit(1)

    session_id = session["id"]
    step("Session ID assigned", lambda: assert_truthy(session_id))
    step("State is CONSENT_PENDING", lambda: assert_eq(session["state"], "CONSENT_PENDING"))

    # ── Step 3: Verify Consent Hard Block ─────────────────────────
    print("\n3. Consent Hard Block")
    resp = client.post(f"{API}/sessions/{session_id}/start", headers=headers())
    step("Start without consent → blocked", lambda: assert_truthy(
        resp.status_code in (403, 409)
    ))

    # ── Step 4: Confirm Consent ───────────────────────────────────
    print("\n4. Confirm Consent")
    consent = step("POST /sessions/{id}/consent", lambda: client.post(
        f"{API}/sessions/{session_id}/consent",
        headers=headers(),
    ).json())

    step("State still CONSENT_PENDING", lambda: assert_eq(consent["state"], "CONSENT_PENDING"))

    # ── Step 5: Start Recording ───────────────────────────────────
    print("\n5. Start Recording")
    recording = step("POST /sessions/{id}/start", lambda: client.post(
        f"{API}/sessions/{session_id}/start",
        headers=headers(),
    ).json())

    step("State is RECORDING", lambda: assert_eq(recording["state"], "RECORDING"))

    # ── Step 6: Pause and Resume ──────────────────────────────────
    print("\n6. Pause and Resume")
    paused = step("POST /sessions/{id}/pause", lambda: client.post(
        f"{API}/sessions/{session_id}/pause",
        headers=headers(),
    ).json())
    step("State is PAUSED", lambda: assert_eq(paused["state"], "PAUSED"))

    resumed = step("POST /sessions/{id}/resume", lambda: client.post(
        f"{API}/sessions/{session_id}/resume",
        headers=headers(),
    ).json())
    step("State is RECORDING", lambda: assert_eq(resumed["state"], "RECORDING"))

    # ── Step 7: Stop Recording ────────────────────────────────────
    print("\n7. Stop Recording → Processing")
    stopped = step("POST /sessions/{id}/stop", lambda: client.post(
        f"{API}/sessions/{session_id}/stop",
        headers=headers(),
    ).json())
    step("State is PROCESSING_STAGE1", lambda: assert_eq(stopped["state"], "PROCESSING_STAGE1"))

    # ── Step 8: Verify Session Retrieval ──────────────────────────
    print("\n8. Session Retrieval")
    fetched = step("GET /sessions/{id}", lambda: client.get(
        f"{API}/sessions/{session_id}",
        headers=headers(),
    ).json())
    step("Correct session returned", lambda: assert_eq(fetched["id"], session_id))
    step("Specialty is orthopedic_surgery", lambda: assert_eq(fetched["specialty"], "orthopedic_surgery"))

    # ── Step 9: Invalid Transition Rejected ───────────────────────
    print("\n9. Invalid Transition Rejected")
    step("Pause from PROCESSING_STAGE1 → 409", lambda: assert_eq(
        client.post(f"{API}/sessions/{session_id}/pause", headers=headers()).status_code,
        409
    ))

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")

    if failed == 0:
        print("STATUS: ✓ EVAL A — All checks passed")
        print("\nJourney 1 backend flow validated:")
        print("  Session create → consent block → consent → record →")
        print("  pause → resume → stop → processing")
        print("\nNext: Submit audio to transcription endpoint for")
        print("  full note generation validation.")
    else:
        print("STATUS: ✗ EVAL A — Some checks failed")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  FAILED: {r['step']} — {r['detail']}")

    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


def assert_eq(actual, expected):
    if actual != expected:
        raise AssertionError(f"Expected {expected}, got {actual}")
    return actual


def assert_truthy(value):
    if not value:
        raise AssertionError(f"Expected truthy, got {value}")
    return value


if __name__ == "__main__":
    sys.exit(main())
