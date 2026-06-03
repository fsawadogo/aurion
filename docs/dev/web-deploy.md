# Web portal — deploy runbook

One-page operator guide for shipping the Aurion admin portal to AWS
Amplify. Covers CI deploys, ad-hoc local deploys, custom-domain
activation, Cognito callback wiring, and the future flip-back path
to GitHub-source auto-build.

## Topology

```
GitHub Actions (web.yml)  ───┐
                             ├── next build → web/out/
                             ├── zip → out.zip
                             ├── aws amplify create-deployment
                             ├── curl PUT → pre-signed S3 URL
                             └── aws amplify start-deployment
                                       │
                                       └─→ Amplify CDN
                                           https://main.<APP_ID>.amplifyapp.com   (default URL — works immediately)
                                           https://portal-dev.aurionclinical.com  (custom domain — needs NS records)
                                               ↓ /api/v1/* fetch from the browser
                                             https://api-dev.aurionclinical.com   (FastAPI on ECS)
```

Platform = WEB. No SSR, no Lambda@Edge, no GitHub source connector.
Static bundle only.

## First-deploy bootstrap (one-time)

After the first `terraform apply` for DEPLOY-WEB:

```bash
# 1. Capture the Amplify app ID from terraform.
cd infrastructure
APP_ID=$(terraform output -raw amplify_app_id)
echo "APP_ID = $APP_ID"

# 2. Capture the default URL.
DEFAULT_URL=$(terraform output -raw amplify_default_url)
echo "Default URL = $DEFAULT_URL"

# 3. Set the GitHub Actions repo variable so the deploy job knows
#    which Amplify app to ship to.
gh variable set AMPLIFY_APP_ID --body "$APP_ID"

# 4. Add the default URL to the Cognito client callback / logout
#    lists. Wildcards aren't supported, so we have to enumerate the
#    explicit URLs.
USER_POOL_ID=$(terraform output -raw cognito_user_pool_id)
CLIENT_ID=$(terraform output -raw cognito_user_pool_client_id)
CALLBACKS=$(aws cognito-idp describe-user-pool-client \
    --user-pool-id "$USER_POOL_ID" \
    --client-id "$CLIENT_ID" \
    --query 'UserPoolClient.CallbackURLs' \
    --output json)
LOGOUTS=$(aws cognito-idp describe-user-pool-client \
    --user-pool-id "$USER_POOL_ID" \
    --client-id "$CLIENT_ID" \
    --query 'UserPoolClient.LogoutURLs' \
    --output json)
NEW_CALLBACK="${DEFAULT_URL}/api/auth/callback/cognito"
NEW_LOGOUT="${DEFAULT_URL}/auth/signed-out"
UPDATED_CALLBACKS=$(echo "$CALLBACKS" | jq --arg u "$NEW_CALLBACK" '. + [$u] | unique')
UPDATED_LOGOUTS=$(echo "$LOGOUTS" | jq --arg u "$NEW_LOGOUT" '. + [$u] | unique')
aws cognito-idp update-user-pool-client \
    --user-pool-id "$USER_POOL_ID" \
    --client-id "$CLIENT_ID" \
    --callback-urls "$UPDATED_CALLBACKS" \
    --logout-urls "$UPDATED_LOGOUTS" \
    --allowed-o-auth-flows code \
    --allowed-o-auth-scopes openid email profile \
    --allowed-o-auth-flows-user-pool-client \
    --supported-identity-providers COGNITO

# 5. Trigger the first deploy. Either:
#    a) Push any web/** change to main, which fires .github/workflows/web.yml, or
#    b) Run the local deploy script (next section).
```

The Cognito update gets folded into Terraform in a follow-up PR
(see "Backlog" in `docs/plans/deploy-web.md`); doing it via CLI here
avoids a chicken-and-egg between the new Amplify resource + the
existing `aws_cognito_user_pool_client.main`.

## Recurring CI deploys

Push to `main` with any change touching `web/**` or
`.github/workflows/web.yml`. The workflow runs:

1. `build` job — `npm ci` → `npm run lint` → `npx vitest run` →
   `npm run build` → upload `web/out/` as the `web-build` artifact.
2. `deploy` job (push to main only) — download the artifact, OIDC
   into `AurionGitHubDeployerDev`, zip + upload + start the Amplify
   deployment.

Watch progress at:

```
https://ca-central-1.console.aws.amazon.com/amplify/apps/<APP_ID>/branches/main
```

## Ad-hoc local deploys

When a build needs to ship without going through CI (hotfix,
debugging a deploy edge case, etc.):

```bash
# 1. Build locally.
cd web
npm ci          # only if package-lock changed
npm run build   # produces web/out/

# 2. Make sure you have AWS creds for the dev account.
aws sso login   # or otherwise; needs amplify:* permissions

# 3. Ship.
bash scripts/deploy.sh <APP_ID>
# or
AMPLIFY_APP_ID=<APP_ID> bash scripts/deploy.sh
```

The script zips `web/out/`, calls `aws amplify create-deployment`,
uploads to the pre-signed URL, and calls
`aws amplify start-deployment`. Logs the Amplify console URL on
success.

## Enabling the custom domain

The Amplify default URL (`https://main.<APP_ID>.amplifyapp.com`)
works immediately. The custom domain
(`https://portal-dev.aurionclinical.com`) needs DNS delegation at
Cloudflare:

```bash
cd infrastructure
terraform output portal_nameservers
```

Take the 4 nameservers and create 4 NS records at Cloudflare for
`portal-dev.aurionclinical.com` pointing at those AWS nameservers.
This mirrors how `api-dev.aurionclinical.com` is delegated — apex
(`aurionclinical.com`) stays at Cloudflare; each subdomain
delegates to Route 53.

Once propagated (~30-60 minutes), Amplify's domain association
auto-verifies and the custom URL serves traffic. Cognito callback
URLs for the custom domain are already in `infrastructure/cognito.tf`
— no extra step needed.

## Flipping back to GitHub-source auto-build (future)

If we ever want Amplify's GitHub connector back (e.g. for
PR-preview deploys, or when a long-lived PAT becomes acceptable):

1. Set `TF_VAR_amplify_github_access_token=<PAT>` in the deploy
   environment (or `tfvars`).
2. In `infrastructure/amplify.tf`:
   - Flip `platform = "WEB"` → `platform = "WEB_COMPUTE"`.
   - Restore `repository`, `access_token`, `build_spec`,
     `enable_branch_auto_build`, `environment_variables`
     (NEXT_PUBLIC_*). Git history has the prior values — see the
     pre-DEPLOY-WEB commit on `amplify.tf`.
   - Drop the `custom_rule` SPA fallback (Next.js SSR routing
     handles dynamic routes server-side).
3. Remove the `deploy` job from `.github/workflows/web.yml` and the
   `output: "export"` line from `web/next.config.js`. The static
   build path stops being load-bearing.

The variable `amplify_github_access_token` stays in `variables.tf`
across both modes so the flip is a single PR, not a schema-rename
PR + a wiring PR.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `AMPLIFY_APP_ID Actions variable is empty` in the deploy job | Run `gh variable set AMPLIFY_APP_ID --body <id>` (see bootstrap §3). |
| `404 Not Found` on `/sessions/<id>` after deploy | Amplify SPA-fallback `custom_rule` missing — verify the `aws_amplify_app.web_portal.custom_rule` block exists in `amplify.tf` and that Amplify reflects it (console → Rewrites and redirects). |
| Cognito hosted-UI returns "redirect_mismatch" | The Amplify default URL isn't in the Cognito callback list — re-run the bootstrap §4 snippet. |
| Custom domain stuck "Pending" in Amplify console | Cloudflare NS records not propagated yet, or pointing at the wrong AWS nameservers. `terraform output portal_nameservers` is the source of truth. |
| Deploy job hangs at `curl PUT` | Pre-signed URL expired (TTL ~30 min) — re-run the job; create-deployment issues a fresh URL each time. |
