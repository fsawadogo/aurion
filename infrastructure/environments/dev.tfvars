environment       = "dev"
multi_az          = false
db_instance_class = "db.t3.medium"

# DNS + TLS (Phase 2). Each env owns its own Route 53 zone for its
# subdomain — apex (aurionclinical.com) stays at Cloudflare.
# After the first apply, take the `route53_nameservers` output and
# create 4 NS records at Cloudflare for `api-dev.aurionclinical.com`.
api_domain = "api-dev.aurionclinical.com"

# Mutable tag is fine in dev — image_tag_mutability on the ECR repo
# allows it. Prod overrides via `-var="api_image_tag=<sha>"` at deploy.
api_image_tag = "latest"
