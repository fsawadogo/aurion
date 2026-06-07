environment       = "dev"
multi_az          = false
db_instance_class = "db.t3.medium"

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

# api_image_tag is INTENTIONALLY not set here (matches prod.tfvars). It used to
# be "latest", which is the footgun behind the 2026-06-07 incident: a bare
# `terraform apply -var-file=dev.tfvars` (no -var override) shipped a STALE
# :latest image whose `alembic upgrade head` failed on the live DB migration.
# CI's deploy-dev always passes `-var "api_image_tag=<sha>"` (CLI > tfvars), so
# CI is unaffected; any out-of-band apply must now pass the CURRENTLY-DEPLOYED
# SHA explicitly (read it from `aws ecs describe-task-definition`). See #326.
