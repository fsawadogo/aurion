environment       = "prod"
multi_az          = true
db_instance_class = "db.t3.medium"

# Media retention (#338). Prod stays at the original 1-day S3 lifecycle TTL —
# set explicitly so the per-env intent is visible (the variable default is also
# 1, but prod is unchanged on purpose).
media_retention_days = 1

# DNS + TLS (Phase 2). Prod owns its own Route 53 hosted zone for
# api.aurionclinical.com — apex stays at Cloudflare. After the first
# prod apply, create 4 NS records at Cloudflare for the prod subdomain
# (a separate set from dev's).
api_domain = "api.aurionclinical.com"

# api_image_tag is INTENTIONALLY not set here. Prod deploys MUST pass
# an immutable commit SHA at apply time:
#   terraform apply -var-file=environments/prod.tfvars \
#                   -var="api_image_tag=<7-char-or-full-sha>"
# CI/CD (Phase 3) wires this automatically. Leaving the default
# ("latest") active in prod is a deploy-pipeline bug — flag it in
# review if a prod apply is happening without the explicit -var.
