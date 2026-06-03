# DEPLOY-WEB — Web portal static export + Amplify manual deploy

## Task

`DEPLOY-WEB` — Ship the Aurion admin/clinician web portal to AWS
Amplify (dev environment) without requiring a GitHub PAT or any
human action in Amplify's console. The portal must be reachable at
the Amplify default URL `https://main.<APP_ID>.amplifyapp.com`
immediately after `terraform apply` + first GitHub Actions deploy.
The custom domain `portal-dev.aurionclinical.com` is a deferred
follow-up gated on Cloudflare NS records (user-only action).

## Why

The existing Terraform (`infrastructure/amplify.tf`) provisions
Amplify in `WEB_COMPUTE` (Next.js SSR) mode, which requires a
`repository` + `access_token` (GitHub PAT). Every resource in that
file is gated `count = var.amplify_github_access_token == null ? 0
: 1`, so right now `terraform apply` provisions only the Route 53
zone — no Amplify app, no branch, no domain wiring. The portal is
unreachable.

We don't have a PAT and don't want one in the loop (rotation toil,
blast radius if leaked, and Amplify's GitHub connector is finicky
about org permissions). The clean alternative is the AWS-native
**Amplify manual-deploy** path:

  1. Build the portal as a fully static bundle (`next build` with
     `output: 'export'` → `web/out/`).
  2. CI zips `out/` and uploads it to a per-deployment
     pre-signed URL via `aws amplify create-deployment` +
     `aws amplify start-deployment`.
  3. Amplify serves the static bundle through its CDN with all
     of the usual headers, custom domain, and HTTPS termination
     intact.

No PAT, no Lambda@Edge, no Amplify build runtime. The Next.js
build runs in our own CI where we already have AWS creds.

## Trade-offs of going static

Next.js 14 static export loses:

  * Server components that touch `cookies()`, `headers()`, or
    dynamic data sources at request time.
  * Server route handlers (`app/api/*/route.ts`) — we already have
    none; the Aurion API lives on the FastAPI backend.
  * `dynamic = "force-dynamic"` and on-demand revalidation.
  * Image optimisation via `next/image`'s default loader (not used
    in this portal yet).

What the portal actually uses today:

  * Server-side next-intl in `app/layout.tsx` (`getLocale()` +
    `getMessages()`) reading the `aurion-locale` cookie. **Migrated
    to client-side** by this PR — see “i18n migration” below.
  * `cognito/callback/page.tsx` declared `dynamic = "force-dynamic"`.
    The page itself is a `"use client"` component that reads
    `useSearchParams()`. The dynamic flag was a Next.js prerender
    workaround; with static export the page renders as a static
    shell that hydrates and reads the URL on mount. The flag is
    removed.
  * Dynamic routes `app/sessions/[id]`, `app/audit/[sessionId]`,
    `app/eval/[id]` — all client components fetching by ID. With
    static export we add `generateStaticParams: async () => []`
    and configure Amplify SPA-fallback rewrites so the client-side
    router handles unknown IDs.

None of the lost features were load-bearing.

## i18n migration — server → client

`web/i18n/request.ts` (the next-intl `getRequestConfig` consumer)
runs on the server and reads cookies via `next/headers`. Static
export cannot keep this — `next build` errors out because the
request config has no request to serve.

Replacement: a small client-side `LocaleProvider` that:

  1. Statically imports both `messages/en.json` and `messages/fr.json`
     at module load (≈25 KB pre-gzip combined — fine for a bundled
     admin tool).
  2. Reads the `aurion-locale` cookie on mount via
     `document.cookie` parsing.
  3. Falls back to `DEFAULT_LOCALE = "en"` when the cookie is
     missing or carries an unsupported value.
  4. Renders `<NextIntlClientProvider>` with the resolved locale +
     matching catalog.

The root layout becomes a server shell (just `<html>` + `<body>` +
`<AurionProviders>`) that delegates locale resolution to the
client provider. `lang={locale}` on `<html>` is the only piece that
moves — we set it to `DEFAULT_LOCALE` at render time and the
provider updates `<html lang>` from the cookie on mount.

`LocaleSwitcher` continues to write the cookie + call
`router.refresh()`. `router.refresh()` still works under static
export — it re-renders the React tree without a full reload, and
the cookie-aware client provider re-resolves the locale.

`web/i18n/request.ts` is deleted (dead code under static export).

The `withIntl` test helper is untouched — it's already a
client-side wrapper using `NextIntlClientProvider`.

## Approach (3 sub-goals)

### 1. Static export + i18n migration (`web/`)

Files touched:

  * `web/next.config.js` — add `output: "export"`, remove the
    next-intl plugin (unused for client-side i18n).
  * `web/app/layout.tsx` — server shell only, no `getLocale()` /
    `getMessages()`. Delegates to `LocaleProvider`.
  * `web/i18n/LocaleProvider.tsx` (new) — client component reading
    the cookie + selecting the catalog.
  * `web/i18n/request.ts` — deleted (server-only, incompatible with
    static export).
  * `web/app/api/auth/callback/cognito/page.tsx` — drop
    `export const dynamic = "force-dynamic"`.
  * `web/app/sessions/[id]/page.tsx`,
    `web/app/audit/[sessionId]/page.tsx`,
    `web/app/eval/[id]/page.tsx` — add `generateStaticParams`
    returning `[]` + `export const dynamicParams = false` (or use
    the SPA-fallback rewrite — see Amplify section).

Verification: `npm run build` produces `web/out/` containing
`index.html` + `_next/` bundle. `npm run lint` clean.
`npx vitest run` passes the existing 2 spec files.

### 2. Terraform `infrastructure/amplify.tf` rework

Drop the GitHub-source gating; the resources always exist:

  * `aws_amplify_app.web_portal`
      * `platform = "WEB"` (was `WEB_COMPUTE`)
      * remove `repository`, `access_token`,
        `enable_branch_auto_build`, `enable_branch_auto_deletion`,
        `enable_basic_auth`, `build_spec` — all GitHub-connector-only
      * keep `custom_headers` (CDN-edge — applies under manual
        deploy)
      * remove `environment_variables` (now CI-injected at
        `next build` time; single source of truth =
        `.github/workflows/web.yml`)
  * `aws_amplify_branch.main` — drop `framework = "Next.js - SSR"`,
    set `framework = "Web"`, keep `stage`
  * `aws_amplify_domain_association.portal` — unchanged (still
    works in manual mode)
  * `aws_iam_role.amplify_service` + policy attachment — unchanged

`amplify_github_access_token` variable stays in `variables.tf` for
future flip-back, marked unused in description.

Outputs (`infrastructure/outputs.tf`) — already declared with
length-guards. Remove the `length(...) > 0 ? ... : ""` ternaries
now that the resources always exist:

  * `amplify_app_id` → `aws_amplify_app.web_portal.id`
  * `amplify_default_domain` (renamed `amplify_default_url`) →
    `https://${aws_amplify_branch.main.branch_name}.${aws_amplify_app.web_portal.default_domain}`

`portal_nameservers` is unchanged.

### 3. CI deploy + local script

`.github/workflows/web.yml`:

  * existing `build` job: add `actions/upload-artifact@v4`
    publishing `web/out/` as `web-build`.
  * new `deploy` job, gated `if: github.ref == 'refs/heads/main' &&
    github.event_name == 'push'`. Reads
    `secrets.AWS_ACCESS_KEY_ID` + `secrets.AWS_SECRET_ACCESS_KEY`
    (same ones the backend `ci.yml` uses). Reads the Amplify app
    ID from `vars.AMPLIFY_APP_ID`. Steps:
      1. `actions/download-artifact@v4` → `web/out/`
      2. `zip -r out.zip out/`
      3. `aws amplify create-deployment` → JSON with
         `zipUploadUrl` + `jobId`
      4. `curl -X PUT --upload-file out.zip "$ZIP_URL"`
      5. `aws amplify start-deployment --job-id "$JOB_ID"`

`web/scripts/deploy.sh` — operator workstation version of the same
flow. Takes app ID as `$1` or `$AMPLIFY_APP_ID`.

`docs/dev/web-deploy.md` — one-page operator runbook covering:
  * Amplify default URL pattern
  * Local deploy procedure
  * How to enable the custom domain (add 4 NS records at
    Cloudflare, list them from `terraform output portal_nameservers`)
  * Post-apply Cognito callback URL addition (one `aws
    cognito-idp update-user-pool-client` invocation)
  * Future flip back to GitHub-source auto-build mode

## Acceptance criteria

1. `cd web && npm run build` succeeds, produces `web/out/` with
   `index.html` + `_next/` bundle.
2. `cd web && npm run lint` clean.
3. `cd web && npx vitest run` — existing tests pass (2 specs).
4. `cd infrastructure && terraform plan -var-file=environments/dev.tfvars
   -out=plan.out` succeeds; plan shows ~5 adds (Amplify app, branch,
   domain association, IAM role, IAM policy attachment) and no
   destroys or unexpected modifications.
5. `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/web.yml'))"`
   succeeds.
6. PR opened, not merged. Body includes the Amplify default URL
   pattern + post-apply checklist.

## Out of scope

  * Running `terraform apply` (parent loop applies after review).
  * Custom domain DNS delegation at Cloudflare (user-only action).
  * Cognito callback URL CLI step (documented in runbook, run
    after first `terraform apply` exposes the app ID).
  * Flipping back to `WEB_COMPUTE` + GitHub source mode — variable
    stays in `variables.tf` for the future flip.

## Backlog

  * Add the Amplify default URL to the Cognito client callback list
    via Terraform (currently a post-apply CLI step) — needs a
    `aws_cognito_user_pool_client` data dependency on
    `aws_amplify_app.web_portal.default_domain` which Terraform
    handles cleanly, just deferred to keep this PR focused on
    plumbing.
  * PR-preview branches (per-PR Amplify deploys) — straightforward
    once main is stable; needs a workflow job keyed on PR open/close.
