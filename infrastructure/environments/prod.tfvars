environment       = "prod"
multi_az          = true
db_instance_class = "db.t3.medium"

# DNS + TLS (Phase 2). Prod reads the shared hosted zone created by
# the dev env (see manage_root_zone in dev.tfvars). `api_domain` is
# the production-facing FQDN — TLS cert is issued for this name.
root_domain      = "aurionclinical.com"
api_domain       = "api.aurionclinical.com"
manage_root_zone = false

# api_image_tag is INTENTIONALLY not set here. Prod deploys MUST pass
# an immutable commit SHA at apply time:
#   terraform apply -var-file=environments/prod.tfvars \
#                   -var="api_image_tag=<7-char-or-full-sha>"
# CI/CD (Phase 3) wires this automatically. Leaving the default
# ("latest") active in prod is a deploy-pipeline bug — flag it in
# review if a prod apply is happening without the explicit -var.
