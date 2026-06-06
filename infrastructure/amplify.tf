# =============================================================================
# Web Admin Portal — AWS Amplify Hosting (manual-deploy mode)
# =============================================================================
# W010 / DEPLOY-WEB — provisions the Next.js admin portal at
# var.web_portal_subdomain.
#
# Architecture (manual-deploy mode):
#   GitHub Actions (.github/workflows/web.yml) ─┐
#                                               ├─ next build → web/out/
#                                               ├─ zip → out.zip
#                                               ├─ aws amplify create-deployment
#                                               │     → pre-signed S3 URL + job ID
#                                               ├─ curl PUT out.zip → URL
#                                               └─ aws amplify start-deployment
#                                                       │
#                                                       └─→ Amplify CDN
#                                                           main.<APP_ID>.amplifyapp.com
#                                                           portal-<env>.aurionclinical.com
#                                                              ↓ /api/v1/* calls
#                                                            api-<env>.aurionclinical.com (existing ALB)
#
# DEPLOY-WEB switched away from the GitHub source connector
# (platform = WEB_COMPUTE → WEB) for two reasons:
#   1. The source connector requires a long-lived GitHub PAT
#      (var.amplify_github_access_token) which adds rotation toil +
#      a leak-blast-radius surface for a 5-clinician pilot.
#   2. WEB_COMPUTE invokes Lambda@Edge for SSR, which the portal
#      doesn't need — every route either pre-renders or hydrates +
#      fetches from the FastAPI backend.
#
# Trade-off documented in docs/plans/deploy-web.md: lose server
# components touching cookies/headers at request time. i18n
# migrated to client-side LocaleProvider; cognito callback hydrates
# on mount; dynamic routes use SPA-fallback rewrites (see
# custom_rules below).
#
# DNS pattern mirrors api domain: apex stays at Cloudflare, this
# subdomain delegates 4 NS records to a per-env Route 53 zone.
# After `terraform apply`, surface the new nameservers via
# `output portal_nameservers` and add them to Cloudflare as NS
# records for var.web_portal_subdomain. Custom domain is OPTIONAL —
# the Amplify default URL (main.<APP_ID>.amplifyapp.com) works
# immediately after the first deploy.

# -----------------------------------------------------------------------------
# Route 53 hosted zone for the portal subdomain
# -----------------------------------------------------------------------------

resource "aws_route53_zone" "portal" {
  name = var.web_portal_subdomain

  tags = {
    Name = var.web_portal_subdomain
  }
}

# -----------------------------------------------------------------------------
# Amplify App (manual-deploy mode)
# -----------------------------------------------------------------------------
# `platform = "WEB"` is the static-hosting platform that supports
# manual deployments via `aws amplify create-deployment`. No
# `repository` / `access_token` / `build_spec` — Amplify doesn't
# build anything in this mode; GitHub Actions does.
#
# `environment_variables` are intentionally absent. NEXT_PUBLIC_*
# values get baked into the static bundle at `next build` time in
# CI, where they're sourced from GitHub Actions repo variables /
# secrets. Single source of truth = `.github/workflows/web.yml`.
# Keeping them here would be misleading (Amplify never reads them
# under platform = WEB) and would invite drift.

resource "aws_amplify_app" "web_portal" {
  name        = "aurion-portal-${var.environment}"
  description = "Aurion admin / compliance / eval web portal (${var.environment}). Manual-deploy via aws amplify create-deployment; see .github/workflows/web.yml + web/scripts/deploy.sh."

  platform             = "WEB"
  iam_service_role_arn = aws_iam_role.amplify_service.arn

  # SPA-fallback rewrite. Static export bakes `index.html` files
  # only for routes Next.js knew about at build time. Dynamic
  # routes (`/sessions/[id]`, `/portal/notes/[id]`, etc.) get a
  # single `/.../_/index.html` placeholder. This rewrite serves
  # `/index.html` (with a 200) for any path that doesn't match a
  # baked file or static asset; the React Router on the client
  # then parses the URL via `useParams()` and fetches the right
  # data. Pattern below is the Amplify-recommended SPA rule —
  # matches everything *except* known static asset extensions.
  #
  # Per-route rewrites for Next.js dynamic segments — Amplify's
  # default `<*>` SPA fallback only matches single-segment unknowns,
  # so multi-segment URLs like `/portal/notes/{uuid}` hit a hard 404
  # without these. Each route is exported by Next.js to a sentinel
  # `[id]` directory (`out/portal/notes/_/index.html`), and the
  # rewrite below routes any nested path to that placeholder. The
  # client-side router reads the URL and renders the right content.
  # Order matters: more specific rules MUST come before the catch-all.
  custom_rule {
    source = "/portal/notes/<*>"
    target = "/portal/notes/_/index.html"
    status = "200"
  }
  custom_rule {
    source = "/portal/patients/<*>"
    target = "/portal/patients/_/index.html"
    status = "200"
  }
  custom_rule {
    source = "/portal/templates/<*>"
    target = "/portal/templates/_/index.html"
    status = "200"
  }
  custom_rule {
    source = "/audit/<*>"
    target = "/audit/_/index.html"
    status = "200"
  }
  custom_rule {
    source = "/eval/<*>"
    target = "/eval/_/index.html"
    status = "200"
  }
  custom_rule {
    source = "/sessions/<*>"
    target = "/sessions/_/index.html"
    status = "200"
  }

  # AASA file (Universal Links) — Apple's swcd daemon NEVER follows
  # redirects when fetching `apple-app-site-association`, but Next.js'
  # `trailingSlash: true` setting (next.config.js:40) makes Amplify
  # auto-301 every extensionless path to add `/`. Result: a request to
  # `/.well-known/apple-app-site-association` → 301 →
  # `/.well-known/apple-app-site-association/` → 404 (HTML), and iOS
  # rejects the Universal Link claim.
  #
  # Three prior PRs tried to fix this in place:
  #   - PR #240 added an Amplify custom_rule rewrite for the canonical
  #     URL → same path, status 200. The rule deployed but never fired
  #     because the file was missing from the bundle (next two PRs).
  #   - PR #241 added a postbuild `cp -r public/.well-known out/.well-known`
  #     — fixed Next.js static export silently dropping hidden dirs.
  #   - PR #242 added `include-hidden-files: true` to the upload-artifact
  #     step — fixed the artifact tar stripping hidden dirs.
  # After all three: file IS in the deploy artifact at
  # `out/.well-known/apple-app-site-association` (474 bytes, correct
  # content), the rewrite rule IS deployed at position 7 of 8. Yet
  # curl still shows S3 origin 301 → trailing-slash variant, fresh
  # CloudFront miss. Amplify bypasses custom_rule rewrites for paths
  # under `.well-known/` at the CDN tier and hands them to S3, which
  # then applies its own trailing-slash redirect. Undocumented but
  # reproducible on 2026-06-05.
  #
  # Workaround: ship the same payload at a NON-HIDDEN path with an
  # EXPLICIT FILE EXTENSION (`out/aurion-aasa-payload.json`, copied from
  # `public/aurion-aasa-payload.json` by Next.js' standard static-export
  # behaviour) and rewrite the canonical Apple URL to it with status 200.
  #
  # PR #246 first tried the non-hidden path WITHOUT an extension
  # (`/aurion-aasa-payload`). Amplify still 301'd that to
  # `/aurion-aasa-payload/` because its CDN treats every extensionless
  # URL as a directory-style route (driven by Next.js' `trailingSlash:
  # true` config) and auto-adds the trailing slash BEFORE evaluating
  # custom_rules. Adding `.json` makes Amplify recognise the URL as a
  # static file and skip the trailing-slash redirect.
  #
  # Header block below still matches on the SOURCE URL
  # (`/.well-known/apple-app-site-association`), so
  # Content-Type: application/json applies untouched even though the
  # backing file already has `.json`. The hidden-path copy at
  # `out/.well-known/...` is intentionally kept as a belt-and-suspenders
  # fallback until the pilot confirms Universal Links resolve end-to-end.
  custom_rule {
    source = "/.well-known/apple-app-site-association"
    target = "/aurion-aasa-payload.json"
    status = "200"
  }

  # Catch-all SPA fallback for single-segment routes (`/login`,
  # `/dashboard`, etc.) — kept last so the explicit rules above win.
  custom_rule {
    source = "/<*>"
    target = "/index.html"
    status = "404-200"
  }

  # Disallow indexing the portal — it's an admin tool, not public.
  #
  # The path-specific rule for `/.well-known/apple-app-site-association`
  # (AUTH-UNIVERSAL-LINKS) forces `Content-Type: application/json` on
  # that single file. Apple's swcd daemon will REJECT the AASA file
  # unless it's served with a JSON content type — and the file
  # deliberately has no extension, so Amplify's auto-MIME detection
  # would otherwise serve it as `application/octet-stream` and break
  # Universal Links app-claim resolution. `nosniff` keeps Safari /
  # iOS from second-guessing the override. The path-specific block
  # is listed AFTER the catch-all because YAML headers under
  # Amplify's customHeaders are additive — every matching rule's
  # headers merge, with later rules overriding earlier same-keyed
  # entries; placing it last guarantees the Content-Type win.
  custom_headers = <<-HEADERS
    customHeaders:
      - pattern: '**/*'
        headers:
          - key: 'X-Robots-Tag'
            value: 'noindex, nofollow'
          - key: 'Strict-Transport-Security'
            value: 'max-age=63072000; includeSubDomains; preload'
          - key: 'X-Content-Type-Options'
            value: 'nosniff'
          - key: 'X-Frame-Options'
            value: 'DENY'
          - key: 'Referrer-Policy'
            value: 'strict-origin-when-cross-origin'
      - pattern: '/.well-known/apple-app-site-association'
        headers:
          - key: 'Content-Type'
            value: 'application/json'
          - key: 'X-Content-Type-Options'
            value: 'nosniff'
  HEADERS

  tags = {
    Name = "aurion-portal-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Amplify branch — main only for now. PR-preview branches deferred to a
# follow-up once the portal stabilises.
# -----------------------------------------------------------------------------
# `framework = "Web"` matches platform = WEB (was "Next.js - SSR"
# under WEB_COMPUTE). `enable_auto_build` is irrelevant in
# manual-deploy mode (no source connector to listen to) but kept
# default-false for clarity. Manual deploys land here regardless.

resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.web_portal.id
  branch_name = "main"

  framework = "Web"
  stage     = var.environment == "prod" ? "PRODUCTION" : "DEVELOPMENT"

  enable_auto_build = false
}

# -----------------------------------------------------------------------------
# Custom domain — portal-<env>.aurionclinical.com → Amplify default subdomain
# -----------------------------------------------------------------------------
# Domain association is independent of deploy mode. Becomes
# reachable once the 4 NS records from `output portal_nameservers`
# are added at Cloudflare for var.web_portal_subdomain (user-only
# action). Until then, use the Amplify default URL (also exported).

resource "aws_amplify_domain_association" "portal" {
  app_id                = aws_amplify_app.web_portal.id
  domain_name           = var.web_portal_subdomain
  wait_for_verification = false

  sub_domain {
    branch_name = aws_amplify_branch.main.branch_name
    prefix      = "" # apex of the zone — i.e. portal-dev.aurionclinical.com itself
  }
}

# -----------------------------------------------------------------------------
# IAM service role for Amplify (build + log access)
# -----------------------------------------------------------------------------
# Amplify still needs a service role even in manual-deploy mode —
# it owns the CloudFront distribution + writes to its own log
# streams. AdministratorAccess-Amplify is the AWS-managed policy
# scoped to Amplify-owned resources.

data "aws_iam_policy_document" "amplify_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["amplify.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "amplify_service" {
  name               = "AurionAmplifyService-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.amplify_assume.json
}

resource "aws_iam_role_policy_attachment" "amplify_backend" {
  role       = aws_iam_role.amplify_service.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess-Amplify"
}
