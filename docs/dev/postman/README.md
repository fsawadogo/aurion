# Aurion API — Postman Collection

A one-click Postman bundle for exercising every endpoint of the
deployed dev API at `https://api-dev.aurionclinical.com`, including
the new `POST /api/v1/admin/probe/vision-clip` admin probe.

| File | Purpose |
|---|---|
| `Aurion-API.postman_collection.json` | The Postman v2.1 collection. 15 folders, one per OpenAPI tag, ~92 requests in total. |
| `Aurion-Dev.postman_environment.json` | Environment pointing at `https://api-dev.aurionclinical.com`. |
| `Aurion-Local.postman_environment.json` | Environment pointing at `http://localhost:8080` (docker-compose). |
| `source-openapi.json` | The exact OpenAPI v3 snapshot used to generate the above. Regen-source-of-truth. |

The collection is **mechanically generated** from
`source-openapi.json` by `scripts/build_postman_collection.py`. Don't
hand-edit the JSON — your changes will be lost on the next regen.

---

## Import

1. **Postman → File → Import** → drag
   `Aurion-API.postman_collection.json` into the drop zone.
2. **Postman → Environments → Import** → drag
   `Aurion-Dev.postman_environment.json` (use
   `Aurion-Local.postman_environment.json` instead if you're hitting
   `docker-compose` locally).
3. In the environment dropdown (top-right of the Postman window),
   select **Aurion Dev** (or **Aurion Local**).
4. Mint a Cognito access token (steps below) and paste it into the
   `jwt` environment variable.
5. Click any request → **Send**. You should get a 200 (or a 4xx with
   a clear validation error — both confirm the auth + transport layer
   are healthy).

> **PHI rule:** the path-parameter placeholders ship as
> `00000000-0000-0000-0000-000000000000`. Replace them with real IDs
> only inside your own workspace, and never commit a Postman variable
> override containing a real `session_id` back into the repo.

---

## Mint a JWT

The collection's auth is **Bearer `{{jwt}}`** at the root level, so
every nested request inherits one token from the environment. We
deliberately do not auto-mint inside Postman — Cognito's `InitiateAuth`
requires the AWS SDK's SRP crypto, which doesn't fit in Postman's
sandbox.

**User pool:** `ca-central-1_jWbQUgzbS` (the dev pool —
see `scripts/provision_pilot_users.sh`).

### Option A: AWS CLI (admin-initiated, no SRP)

If the user pool has the `ALLOW_ADMIN_USER_PASSWORD_AUTH` flow
enabled on its app client, you can mint a token straight from the
CLI:

```bash
aws cognito-idp admin-initiate-auth \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --client-id <APP_CLIENT_ID> \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=faical.sawadogo@aurionclinical.com,PASSWORD=$AURION_DEV_PASSWORD \
  --query 'AuthenticationResult.AccessToken' \
  --output text
```

Paste the output into the `jwt` environment variable.

If MFA is enabled on your account (default for the dev pool), the
first call returns a `MFA_REQUIRED` challenge — respond with
`admin-respond-to-auth-challenge` and the 6-digit TOTP code, then
copy the `AccessToken` from the response.

### Option B: Web portal session storage

If you're already signed in at `portal-dev.aurionclinical.com`:

1. DevTools → **Application** → **Local Storage** → the entry under
   `aurion.session`.
2. Copy the `accessToken` value.
3. Paste into Postman's `jwt` variable.

This works around the SRP-via-CLI complication for users who haven't
enabled `ADMIN_USER_PASSWORD_AUTH`.

### Token lifetime

The dev pool issues 1-hour access tokens. When you see a 401, repeat
the mint step — the collection doesn't refresh automatically.

---

## Sample workflow: end-to-end Gemini vision-clip probe

This is the canonical "is dev healthy?" check.

1. Open the **Admin** folder → **Probe Vision Clip** request.
2. Click the **Body** tab. You'll see two `formdata` rows:
   - `clip` — type `file`. Click **Select Files** and choose
     `backend/tests/fixtures/probe_clip.mp4` from this repo. The
     committed fixture is a 5 KB, 2 s, H.264 blue test card with no
     audio and no clinical content.
   - `provider_override` — disabled by default. Tick the box and set
     the value to `gemini`, `openai`, or `anthropic` if you want to
     test a specific provider; leave disabled to use the currently-
     configured `vision_clip` provider from AppConfig.
3. Click **Send**. Expect a 200 with `success: true` if the provider
   is healthy, or `success: false` with a classified `error_type` if
   not.

The probe always deletes the temp S3 object in a `finally` block
and always emits a `vision_clip_probed` audit event — see
`docs/dev/gemini-probe.md` for the full failure-type matrix.

---

## Regenerating the collection after the API changes

The collection is a **derived artifact**. Whenever a router gains,
loses, or reshapes an endpoint:

```bash
# 1. Refresh the source snapshot from the deployed dev API.
curl https://api-dev.aurionclinical.com/openapi.json \
  > docs/dev/postman/source-openapi.json

# 2. Re-run the generator.
python3 scripts/build_postman_collection.py

# 3. (Optional) Re-run the generator tests.
python3 scripts/test_build_postman_collection.py
```

The generator is **idempotent** — if no endpoint changed since the
last regen, the JSON files end up byte-identical and `git status`
shows them clean.

Commit the regenerated artifacts in the same PR that changed the
router. The build script is stdlib-only and runs in a few hundred ms,
so there's no excuse to skip it.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| Every request returns 401 | `jwt` variable is empty or expired. Re-mint and paste. |
| `{{base_url}}` shows up literally in the URL | No environment selected — pick **Aurion Dev** in the top-right dropdown. |
| `:session_id` is sent literally instead of expanding | A collection variable has been deleted. Re-import the collection, or recreate the variable manually. |
| Probe request returns `success=false, error_type=ProviderError, "GOOGLE_AI_API_KEY not configured"` | Local dev shell has no Gemini key — expected. Use the dev environment instead, or set the secret in `backend/.env`. |
| `Permission denied: ADMIN role required` | Your JWT belongs to a CLINICIAN. Admin endpoints require ADMIN or COMPLIANCE_OFFICER. |

---

## See also

* `docs/dev/gemini-probe.md` — full probe operator manual.
* `docs/plans/postman-collection.md` — the design doc for this lane.
* `scripts/provision_pilot_users.sh` — the script that creates the
  dev Cognito users this collection authenticates as.
