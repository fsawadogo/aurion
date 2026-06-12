environment       = "dev"
multi_az          = false
db_instance_class = "db.t3.medium"

# Media retention review window (#338). Audio + frames S3 buckets expire after
# 7 days in dev so the eval team can review recent captures. Raw audio is PHI,
# so the window is capped intentionally — this is only the max-window backstop;
# app-level purge-on-approval still deletes media on the precise path.
media_retention_days = 7

# DNS + TLS (Phase 2). Each env owns its own Route 53 zone for its
# subdomain — apex (aurionclinical.com) stays at Cloudflare.
# After the first apply, take the `route53_nameservers` output and
# create 4 NS records at Cloudflare for `api-dev.aurionclinical.com`.
api_domain = "api-dev.aurionclinical.com"

# Web admin portal — single-tenant pilot, so we use the friendlier
# `portal.aurionclinical.com` (no `-dev` suffix) even in dev. When prod
# comes online, rename this to `portal-dev.` and reserve `portal.` for
# prod via prod.tfvars. CTO decision 2026-06-03.
web_portal_subdomain = "portal.aurionclinical.com"

# Email delivery recipients (#76 / #77) — ACTIVATE the CRITICAL operational-
# alert email sink + the scheduled compliance-report delivery on the live
# Resend sender. Same ops mailbox already used for CloudWatch alarms
# (var.alerts_email). Comma-separate to add more, or split alerts vs
# compliance later. Empty (the variable default) keeps them dormant.
alert_email_recipients       = "faical.sawadogo@aurionclinical.com"
compliance_report_recipients = "faical.sawadogo@aurionclinical.com"

# api_image_tag is INTENTIONALLY not set here (matches prod.tfvars). It used to
# be "latest", which is the footgun behind the 2026-06-07 incident: a bare
# `terraform apply -var-file=dev.tfvars` (no -var override) shipped a STALE
# :latest image whose `alembic upgrade head` failed on the live DB migration.
# CI's deploy-dev always passes `-var "api_image_tag=<sha>"` (CLI > tfvars), so
# CI is unaffected; any out-of-band apply must now pass the CURRENTLY-DEPLOYED
# SHA explicitly (read it from `aws ecs describe-task-definition`). See #326.
