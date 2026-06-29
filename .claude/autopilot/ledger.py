#!/usr/bin/env python3
"""Autopilot ledger + gate CLI — the hardening spine.

Stdlib-only (runs in headless scheduled contexts with no deps). Single source
of truth is policy.json next to this file. State lives in the git-ignored
state_dir.

Subcommands:
  fingerprint <loop> <key...>     stable id for a finding (so loops never refile)
  seen <fingerprint>              exit 0 if already recorded, 1 if new
  record <loop> ...               persist a finding (skips if fingerprint seen)
  gate [--files f...| -]          exit NONZERO if any path is protected (kill switch)
  resolve <fingerprint> --status accepted|rejected
  stats [--loop L]                per-loop accept rate + cost-per-accepted
  log-run <loop> ...              append a run record
  init                            create the state dir layout

Exit codes: gate → 0 clear / 2 protected. seen → 0 seen / 1 new. others → 0 ok.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY_PATH = HERE / "policy.json"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def state_dir(policy: dict) -> Path:
    # AUTOPILOT_STATE_DIR wins (isolated dry-runs / the supervised first run);
    # otherwise state_dir in policy is repo-relative, resolved against the repo
    # root (two up from .claude/autopilot/). Allows running from anywhere.
    override = os.environ.get("AUTOPILOT_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    repo_root = HERE.parent.parent
    d = (repo_root / policy["state_dir"]).resolve()
    return d


def findings_dir(policy: dict) -> Path:
    return state_dir(policy) / "findings"


# ── glob matching (supports **, *, ?) ───────────────────────────────────────

def _glob_to_re(glob: str) -> re.Pattern:
    i, out = 0, ["^"]
    while i < len(glob):
        if glob[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif glob[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def protected_match(path: str, protected: list[str]) -> str | None:
    """Return the first protected glob that matches `path`, else None."""
    p = path.strip()
    if p.startswith("./"):  # drop the relative-path marker only — NOT leading dots (.github!)
        p = p[2:]
    for g in protected:
        if _glob_to_re(g).match(p):
            return g
    return None


# ── fingerprint ──────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def fingerprint(loop: str, key_parts: list[str]) -> str:
    """Stable, deterministic id. Build it from STABLE identity (loop + file +
    rule/title), NOT volatile line numbers, so the same finding fingerprints
    identically across runs."""
    basis = loop.strip().lower() + "::" + "::".join(_normalize(k) for k in key_parts)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_init(policy: dict, _a) -> int:
    findings_dir(policy).mkdir(parents=True, exist_ok=True)
    runs = state_dir(policy) / "runs.jsonl"
    runs.touch(exist_ok=True)
    print(f"state ready: {state_dir(policy)}")
    return 0


def cmd_fingerprint(_policy: dict, a) -> int:
    print(fingerprint(a.loop, a.key))
    return 0


def cmd_seen(policy: dict, a) -> int:
    exists = (findings_dir(policy) / f"{a.fingerprint}.json").exists()
    print("seen" if exists else "new")
    return 0 if exists else 1


def cmd_record(policy: dict, a) -> int:
    findings_dir(policy).mkdir(parents=True, exist_ok=True)
    fp = a.fingerprint or fingerprint(a.loop, a.key or [a.title])
    path = findings_dir(policy) / f"{fp}.json"
    if path.exists():
        print(f"dup {fp} (already recorded) — skipping")
        return 0
    rec = {
        "fingerprint": fp,
        "loop": a.loop,
        "title": a.title,
        "severity": a.severity,
        "files": a.files or [],
        "cost_usd": a.cost,
        "status": "open",
        "pr": a.pr,
        "issue": a.issue,
        "recorded_at": _now(),
        "resolved_at": None,
    }
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print(f"recorded {fp}")
    return 0


def cmd_gate(policy: dict, a) -> int:
    if a.stdin:
        files = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    else:
        files = a.files or []
    protected = policy["protected_paths"]
    hits = [(f, protected_match(f, protected)) for f in files]
    blocked = [(f, g) for f, g in hits if g]
    if blocked:
        print("PROTECTED — escalate to needs-human (auto-merge blocked):")
        for f, g in blocked:
            print(f"  {f}  ⟵  {g}")
        return 2
    print(f"clear — {len(files)} file(s), none protected")
    return 0


def cmd_resolve(policy: dict, a) -> int:
    path = findings_dir(policy) / f"{a.fingerprint}.json"
    if not path.exists():
        print(f"no such finding: {a.fingerprint}", file=sys.stderr)
        return 1
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["status"] = a.status
    rec["resolved_at"] = _now()
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print(f"{a.fingerprint} -> {a.status}")
    return 0


def cmd_stats(policy: dict, a) -> int:
    recs = [json.loads(p.read_text()) for p in findings_dir(policy).glob("*.json")]
    if a.loop:
        recs = [r for r in recs if r["loop"] == a.loop]
    by_loop: dict[str, dict] = {}
    for r in recs:
        b = by_loop.setdefault(r["loop"], {"accepted": 0, "rejected": 0, "open": 0, "cost": 0.0})
        b[r["status"]] = b.get(r["status"], 0) + 1
        b["cost"] += float(r.get("cost_usd") or 0)
    min_rate = policy.get("min_accept_rate", 0.5)
    out = {}
    # --json prints ONLY JSON (consumers like digest.js JSON.parse it); the human
    # table is suppressed so nothing is prepended to the parseable output.
    if not a.json:
        print(f"{'loop':<16} {'acc':>4} {'rej':>4} {'open':>5} {'accept_rate':>12} {'$/accepted':>11}  flag")
    for loop, b in sorted(by_loop.items()):
        decided = b["accepted"] + b["rejected"]
        rate = (b["accepted"] / decided) if decided else None
        cpa = (b["cost"] / b["accepted"]) if b["accepted"] else None
        flag = ""
        if rate is not None and rate < min_rate:
            flag = f"BELOW {min_rate:.0%} — throttle/tune"
        if not a.json:
            rate_s = f"{rate:.0%}" if rate is not None else "n/a"
            cpa_s = f"${cpa:.2f}" if cpa is not None else "n/a"
            print(f"{loop:<16} {b['accepted']:>4} {b['rejected']:>4} {b['open']:>5} {rate_s:>12} {cpa_s:>11}  {flag}")
        out[loop] = {"accepted": b["accepted"], "rejected": b["rejected"], "open": b["open"],
                     "accept_rate": rate, "cost_per_accepted": cpa, "below_min": bool(flag)}
    if a.json:
        print(json.dumps(out, indent=2))
    return 0


def cmd_log_run(policy: dict, a) -> int:
    state_dir(policy).mkdir(parents=True, exist_ok=True)
    rec = {"ts": _now(), "loop": a.loop, "status": a.status,
           "tokens": a.tokens, "cost_usd": a.cost, "note": a.note}
    with (state_dir(policy) / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"logged run: {a.loop} {a.status}")
    return 0


def main() -> int:
    policy = load_policy()
    p = argparse.ArgumentParser(prog="ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("fingerprint"); s.add_argument("loop"); s.add_argument("key", nargs="+"); s.set_defaults(fn=cmd_fingerprint)
    s = sub.add_parser("seen"); s.add_argument("fingerprint"); s.set_defaults(fn=cmd_seen)
    s = sub.add_parser("record")
    s.add_argument("loop"); s.add_argument("--title", required=True); s.add_argument("--severity", default="medium")
    s.add_argument("--fingerprint"); s.add_argument("--key", nargs="*"); s.add_argument("--files", nargs="*")
    s.add_argument("--cost", type=float, default=0.0); s.add_argument("--pr"); s.add_argument("--issue")
    s.set_defaults(fn=cmd_record)
    s = sub.add_parser("gate"); s.add_argument("--files", nargs="*"); s.add_argument("--stdin", action="store_true"); s.set_defaults(fn=cmd_gate)
    s = sub.add_parser("resolve"); s.add_argument("fingerprint"); s.add_argument("--status", required=True, choices=["accepted", "rejected"]); s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("stats"); s.add_argument("--loop"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_stats)
    s = sub.add_parser("log-run"); s.add_argument("loop"); s.add_argument("--status", required=True); s.add_argument("--tokens", type=int, default=0); s.add_argument("--cost", type=float, default=0.0); s.add_argument("--note", default=""); s.set_defaults(fn=cmd_log_run)
    s = sub.add_parser("init"); s.set_defaults(fn=cmd_init)

    a = p.parse_args()
    return a.fn(policy, a)


if __name__ == "__main__":
    sys.exit(main())
