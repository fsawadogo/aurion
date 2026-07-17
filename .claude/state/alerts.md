# Aurion Autonomous Loop — Alerts

Append-only file. The monitor cron writes here when state changes; the
driver loop reads this at the top of every tick and handles new entries
before any new task work.

Format:

    ## YYYY-MM-DD HH:MM [severity] {source}
    {one-line summary}
    {optional details}

Severity: INFO | WARN | ALERT (loop pauses + Linear post)

Loops MUST NOT delete entries from this file. Mark handled by appending
a `→ resolved YYYY-MM-DD HH:MM` line under the entry.

---

## 2026-07-15 19:55 [ALERT] /simplify §9f (altitude) — loop-1
`append-recording` silently destroys Stage-2 work — the same laundering hole loop-1 just closed on `regenerate-note`, through the sibling door.

`POST /transcription/{session_id}/append-recording` (`backend/app/api/v1/transcription.py:437`) calls `generate_stage1_note` with **no state precondition and no loss gate**. Its own docstring (`transcription.py:377-381`) says so deliberately: *"Deliberately bypasses `run_stage1` / the PROCESSING_STAGE1 gate… so an AWAITING_REVIEW / **REVIEW_COMPLETE** encounter can gain a second clip… we reuse the regenerate pattern (no state precondition)."*

A `REVIEW_COMPLETE` session is exactly one that has been through Stage 2. Appending a clip → `generate_stage1_note` → `create_note_version` → new `max(version)` → `get_latest_note` returns a Stage-1-only note. Every visual/screen/measurement claim and every physician edit drops out of the latest note. Including **unresolved `conflict_*` claims** — and `approve_note` (`note_gen/service.py:1448`) refuses to sign over those, so this turns an unapprovable note into an approvable one. Same feature flag as regenerate (`note_options_enabled`), same destruction, no confirmation, no audit of the loss.

Not introduced by loop-1 — pre-existing. Found by the §9f altitude agent; **both correctness reviewers missed it.**

Why this is an ALERT and not an auto-fix (§6c: *"if the fix would change the acceptance contract — halts and posts to alerts.md for human review"*):
- The correct fix moves the gate INTO `generate_stage1_note` so all three callers inherit it. That gives `append_recording` a new 409 + a new `confirm_discard` field — **a second endpoint's contract**, beyond loop-1's AC.
- It needs an iOS decision: iOS calls append behind `note_options_enabled` and would have to handle the 409 (→ folds into loop-5's wiring contract).
- Naive placement wastes a Whisper call: append transcribes the clip BEFORE calling note-gen, so a 409 there discards a paid transcription and the physician must re-upload. The gate likely has to run before `transcribe_audio`.

Mitigating: `note_options_enabled` ships **dark**, so nothing is live in production today.

Tracked as `loop-1b` in backlog.md (Cohort 6). Needs a human call on the append UX before implementation.
→ awaiting human review — Uzziel

## 2026-07-15 20:05 [WARN] /verify-acceptance §9d — loop-1
Local stack cannot boot: `aurion-api` exits at startup with `ConnectionError: PostgreSQL server at "postgres:5432" rejected SSL upgrade`.

Root cause `backend/app/core/database.py:68`:
```python
is_local = any(h in url for h in ("@localhost", "@127.0.0.1", "@db:", "@db/"))
```
The compose service is named **`postgres`** (`aurion-postgres`), not `db`, so `@postgres:5432` misses the local allowlist → `ssl=require` → the local Postgres (no TLS) rejects the upgrade. Pre-existing on main, unrelated to loop-1, and it blocks the §9d "stack boots" gate for **every** task in every lane.

Fix is one allowlist entry (`"@postgres:"`, `"@postgres/"`), matching the shape of the existing `@db:` entry. Deliberately NOT keyed off `APP_ENV in {local,test}` as previously sketched — that would disable TLS on any prod task whose APP_ENV was misset, which is a worse failure than a broken local boot.

Tracked as `loop-0` in backlog.md (Cohort 6). loop-1's AC-12 is recorded UNVERIFIED rather than passed.
→ resolved 2026-07-15 21:00 — fixed on `lane-backend/loop-0-db-ssl-local`. `_ssl_connect_args` now PARSES the host (SQLAlchemy `make_url`) and compares it exactly against `_LOCAL_DB_HOSTS`, failing closed on anything unparseable — rather than adding one more substring entry. Verified: `curl localhost:8080/health` → **200**, zero "rejected SSL upgrade" in the API logs.

Writing the tests turned up the substring version's other direction: a REMOTE host merely starting with a local name (`localhost.internal.example.com`) matched `"@localhost"` and got NO TLS. **Latent, never live** — independent review traced `infrastructure/ecs.tf:571`, which sets `DB_HOST = aws_db_instance.main.address` (the RDS FQDN), so no deployment could reach it; `service_discovery.tf` registers only `whisper`, so there is no `postgres`/`db` VPC alias either. Recording it as a real defect in the matcher, NOT as a PHI exposure — no plaintext PHI was ever sent. Both directions are now pinned by regression tests, and prod TLS behaviour is byte-identical before and after.
