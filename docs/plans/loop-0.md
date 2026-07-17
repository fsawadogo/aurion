# Plan — loop-0

## Task

loop-0 — the local stack cannot boot: `_ssl_connect_args` forces TLS against the local Postgres.

## Why

`docker compose up` brings up postgres/localstack/whisper/mailhog healthy, then `aurion-api` exits at startup:

```
ConnectionError: PostgreSQL server at "postgres:5432" rejected SSL upgrade
ERROR:    Application startup failed. Exiting.
```

`backend/app/core/database.py:68` decides local-vs-RDS by substring:

```python
is_local = any(h in url for h in ("@localhost", "@127.0.0.1", "@db:", "@db/"))
```

The compose service is named **`postgres`** (`backend/docker-compose.yml:49`, `container_name: aurion-postgres`) and `docker-compose.yml:16` sets `DATABASE_URL=postgresql+asyncpg://aurion:aurion@postgres:5432/aurion`. `@postgres:` is not in the allowlist → `ssl=require` → the local Postgres has no TLS → boot fails.

The existing test encodes the mistake: `tests/unit/test_database_ssl.py:25` is named `test_docker_compose_host_stays_plaintext` and asserts `@db:` — a service name that does not exist in this repo. So the allowlist has never matched the real compose host, and the test agreed with it.

This blocks AURION-CODING-WORKFLOW §9d ("Stack boots — `docker compose up -d && curl -fs localhost:8080/health` returns 200 within 10s") for **every task in every lane**. loop-1 shipped with AC-12 recorded UNVERIFIED because of it (`.claude/state/verify-receipt-loop-1.json`). Cohort 6's remaining PRs (loop-2..loop-5) all need a bootable stack to verify.

Discovered by the loop-1 `/verify-acceptance` gate. Alert: `.claude/state/alerts.md` 2026-07-15 20:05.

## Approach

Don't just add `"@postgres:"` to the substring list — that repeats the failure mode that caused this (silent under-match) and leaves a latent over-match: a substring test can't tell the host from the password or the database name.

Resolve the **host** and compare it exactly, using SQLAlchemy's own URL parser (already a dependency, and the same parser `create_async_engine` uses on the very next line):

```python
_LOCAL_DB_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "127.0.0.1", "::1", "db", "postgres"}
)
```

**Fail closed.** Anything unparseable or unrecognised gets `ssl=require`. A local dev box that wrongly requires TLS is a loud, immediate boot failure; a prod task that wrongly *skips* TLS ships PHI in plaintext to RDS. The asymmetry decides the default.

Explicitly **not** keyed off `APP_ENV in {local, test}` (the approach a stale memory note proposed): any prod task with a misset env var would silently drop TLS. Host identity is the honest signal — prod RDS hostnames can never be `postgres` or `localhost`.

Files:
- `backend/app/core/database.py` — `_ssl_connect_args`.
- `backend/tests/unit/test_database_ssl.py` — cover the real compose host + the over-match guards.

## Acceptance criteria

- [ ] AC-1: `_ssl_connect_args("postgresql+asyncpg://aurion:aurion@postgres:5432/aurion")` → `{}` — `pytest tests/unit/test_database_ssl.py::TestSslConnectArgs::test_compose_postgres_host_stays_plaintext`
- [ ] AC-2: An RDS host still gets TLS — `::test_rds_host_requires_ssl` (existing, must stay green)
- [ ] AC-3: An RDS instance whose name merely *starts with* `postgres` (`@postgres.abc.ca-central-1.rds.amazonaws.com`) still gets TLS — `::test_rds_host_named_postgres_still_requires_ssl` (proves no over-match)
- [ ] AC-4: A password or db-name containing "localhost" does NOT disable TLS — `::test_local_hostname_in_password_does_not_disable_ssl` (proves the substring class is gone)
- [ ] AC-5: An unparseable URL fails CLOSED (`ssl=require`, no raise) — `::test_unparseable_url_fails_closed`
- [ ] AC-6: `localhost` / `127.0.0.1` / `db` stay plaintext — existing tests stay green
- [ ] AC-7: Full `tests/unit/` green + ruff clean
- [ ] AC-8: **The gate this exists for** — `docker compose -f backend/docker-compose.yml -f backend/docker-compose.override.yml up -d` then `curl -fs localhost:8080/health` → **200**
- [ ] AC-9: No iOS/web impact — `git diff --stat main...HEAD -- ios/ web/` empty

## DRY / SOLID check

- **Existing helpers to reuse**: `sqlalchemy.engine.url.make_url` — the parser `create_async_engine` already applies to this same URL on the next line. No hand-rolled parsing.
- **New helper introduced?**: No new function. `_LOCAL_DB_HOSTS` is a module constant replacing an inline tuple — not a new abstraction, and it's the only enumeration of "hosts that are local" in the repo (grep: no other copy).
- **iOS UI tasks only**: n/a.

## Out of scope

- `/simplify` — S-complexity task (0.2d), skipped per §17 cost control ("skip it on S-complexity tasks via the plan's out of scope line"). Two reviewers already cover a ~10-line security-adjacent diff.
- Renaming the compose service `postgres` → `db` to match the old allowlist. Wrong direction: `postgres` is the accurate name, it's referenced by `container_name: aurion-postgres` and the seed/docs, and the code should describe reality.
- The `version` attribute obsolete-warning in `docker-compose.yml`.
- Any change to prod TLS posture. RDS behaviour is byte-identical before and after.

## Test plan (executable)

1. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_database_ssl.py -v` → all pass
2. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/ -q` → full suite green
3. `cd backend && .venv/Scripts/python.exe -m ruff check app/ tests/` → clean
4. `docker compose -f backend/docker-compose.yml -f backend/docker-compose.override.yml up -d` then `curl -fs localhost:8080/health` → **200** (the AC that motivates the task)
5. `docker compose ... logs aurion-api | grep -i "rejected SSL upgrade"` → no hits
6. `git diff --stat main...HEAD -- ios/ web/` → empty

## Security implications

- **Touches TLS on the PHI database — the whole point of the file.** Prod is unaffected: RDS hostnames are not in `_LOCAL_DB_HOSTS`, so they keep `ssl=require` (AC-2, AC-3).
- The change **narrows** what counts as local: today `@localhost` matches anywhere in the URL (password, db name); after, only the parsed host counts (AC-4). Strictly safer.
- Fail-closed on parse failure (AC-5) — an unknown URL shape gets TLS, not plaintext.
- No PHI, no logs, no audit, no prompts touched.
