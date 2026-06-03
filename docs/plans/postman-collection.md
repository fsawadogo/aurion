# Postman Collection for the Aurion Dev API

**Backlog item:** "Postman collection + Aurion env for live dev API" (Task #156).

**Author:** lane-backend/postman-collection

---

## Goal

Ship a single Postman Collection v2.1 JSON file + matching
Postman Environment JSON files (`Aurion Dev`, `Aurion Local`) so any
contributor — backend, eval, compliance, web — can import the file,
paste a Cognito JWT, and exercise every endpoint of the live deployed
dev API at `https://api-dev.aurionclinical.com` without any further
manual wiring.

The collection must explicitly cover the new probe endpoint added in
the `P1-FU-GEMINI-PROBE` slice
(`POST /api/v1/admin/probe/vision-clip`), since that is the first
endpoint where multipart-with-file-upload + admin-only auth + a
synchronous provider call all converge.

---

## Source of truth

The collection is **mechanically derived** from the deployed dev API's
OpenAPI v3 spec. There is no hand-curated request list.

```bash
curl https://api-dev.aurionclinical.com/openapi.json \
  > docs/dev/postman/source-openapi.json
python3 scripts/build_postman_collection.py
```

The spec snapshot used for this PR was downloaded on 2026-06-03 from
`https://api-dev.aurionclinical.com/openapi.json` and contains 92
paths across 15 tags.

---

## Approach

### 1. Builder script (`scripts/build_postman_collection.py`)

A single Python module with no third-party dependencies (stdlib only —
the script needs to run in CI without a requirements install). It:

* Reads OpenAPI from `docs/dev/postman/source-openapi.json` (path
  overridable via argv).
* Walks `paths.*.<method>`, buckets each operation under its first
  `tag`.
* Emits a Postman Collection v2.1 JSON to
  `docs/dev/postman/Aurion-API.postman_collection.json`.
* Emits two Postman Environment JSONs:
  - `Aurion-Dev.postman_environment.json` (`base_url = https://api-dev.aurionclinical.com`)
  - `Aurion-Local.postman_environment.json` (`base_url = http://localhost:8080`)
* Idempotent: sorted keys, stable IDs derived from path+method
  hashes, identical output on re-run (byte-for-byte).

### 2. Postman v2.1 structure

* **Info block** carries name, schema URL, description, and a pointer
  to `docs/dev/postman/README.md`.
* **Auth** is declared once at the collection root as Bearer
  `{{jwt}}`. Every nested request inherits this; no per-request auth
  override needed.
* **Variables** at the collection root cover every `{path_param}` the
  OpenAPI declares — `session_id`, `note_id`, `template_key`,
  `provider_type`, `user_id`, `report_id`, `template_id`, `macro_id`,
  `order_id`, `suggestion_id`, `claim_id`, `identifier` — each
  defaulted to a placeholder UUID or string.
* **Folders** match OpenAPI tags. We expect at minimum: `health`,
  `auth`, `admin`, `me`, `sessions`, `notes`, `transcription`,
  `vision`, `clips`, `frames`, `screen`, `export`, `privacy`,
  `config`, `profile`.
* **Each request** uses Postman colon-style path params
  (`{{base_url}}/api/v1/clips/:session_id`) which Postman binds
  automatically to the matching collection variable.
* For `multipart/form-data` operations, we emit `formdata` body
  entries. Fields where the OpenAPI schema declares
  `contentMediaType: application/octet-stream` become `type: file`
  with `src: []` (Postman will prompt the user to attach a local
  file). All other fields are plain `text` entries with the example
  or schema default as the value.
* For `application/json` operations, we synthesize a minimal JSON
  skeleton from the referenced schema (resolving `$ref`,
  using the first listed `example` when present, otherwise zero-values
  matching `type`).

### 3. Pre-request script

A single collection-level pre-request script warns once if `{{jwt}}`
is empty:

```js
if (!pm.environment.get("jwt")) {
  console.warn("[Aurion] No JWT set. See docs/dev/postman/README.md → 'Mint a JWT'.");
}
```

We deliberately do **not** try to mint JWTs from Postman — Cognito's
`InitiateAuth` against a SRP-protected pool requires the AWS SDK
crypto bundle, which doesn't fit in Postman's sandbox. The README
points users at the same AWS CLI flow that `scripts/provision_pilot_users.sh`
uses.

### 4. README (`docs/dev/postman/README.md`)

Covers:

* What the collection covers (every endpoint of the deployed dev API
  + the new vision-clip probe).
* Import steps (drag the collection JSON, drag the env JSON, select
  the env).
* How to mint a Cognito JWT via the AWS CLI (`USER_POOL_ID =
  ca-central-1_jWbQUgzbS`, the value `provision_pilot_users.sh` writes
  against).
* How to regenerate the collection after the spec changes.
* A sample workflow: probe the Gemini vision-clip path end-to-end.

### 5. Tests (`scripts/test_build_postman_collection.py`)

A self-contained pytest-style module (also runnable as
`python3 scripts/test_build_postman_collection.py`) that exercises:

* Generator runs without error.
* Every OpenAPI path appears in the generated collection (search by
  url.raw).
* Every `{path_param}` appears as a collection variable.
* The probe endpoint has a `formdata` body with a `clip` file field
  plus an optional `provider_override` text field.
* Re-running the generator produces byte-identical output
  (idempotence).
* The generated collection's top-level keys match the Postman v2.1
  shape (`info`, `item`, `auth`, `variable`, `event`).

We do **not** pull the official JSON-schema for v2.1 over the network
during tests — schemas hosted externally are flaky in CI. Instead we
assert the structural invariants Postman itself validates on import
(the keys above, plus folder/request item discrimination via
`item.request` vs `item.item`).

---

## Out of scope

* Newman runner / CI integration. Postman has good CLI tooling but
  the goal of this PR is just the static artifact; Newman runs are
  follow-up work if we want a contract-test gate.
* Automated JWT minting. Cognito SRP auth requires the AWS SDK; not
  worth bundling. README documents the CLI path.
* Per-environment Cognito user pool IDs. The dev pool is the only
  cloud pool in scope for the pilot.
* Web-portal-specific endpoints — those live behind the Next.js
  proxy and are exercised through the browser, not Postman.

---

## Verification gate

1. `python3 scripts/build_postman_collection.py` runs cleanly from a
   fresh clone with stdlib only.
2. `python3 scripts/test_build_postman_collection.py` passes.
3. Manual: `jq '.item | length' docs/dev/postman/Aurion-API.postman_collection.json`
   ≥ 6 (at least one folder per major tag).
4. Manual: `jq '.. | .request? // empty | select(.url.raw // "" | contains("probe/vision-clip"))' docs/dev/postman/Aurion-API.postman_collection.json`
   returns a non-empty match.
5. Manual: import the collection + dev environment into a fresh
   Postman workspace, paste a JWT minted via the CLI flow in the
   README, send `GET /health` → 200.

---

## Files touched

| File | Purpose |
|---|---|
| `docs/plans/postman-collection.md` | This plan. |
| `docs/dev/postman/source-openapi.json` | The exact OpenAPI snapshot the artifact was built from. |
| `scripts/build_postman_collection.py` | Converter, stdlib-only, idempotent. |
| `scripts/test_build_postman_collection.py` | Generator tests. |
| `docs/dev/postman/Aurion-API.postman_collection.json` | Generated artifact — committed for one-click import. |
| `docs/dev/postman/Aurion-Dev.postman_environment.json` | Dev environment. |
| `docs/dev/postman/Aurion-Local.postman_environment.json` | LocalStack environment. |
| `docs/dev/postman/README.md` | Import + JWT + regeneration docs. |
