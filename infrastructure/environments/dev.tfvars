environment       = "dev"
multi_az          = false
db_instance_class = "db.t3.medium"

# DNS + TLS (Phase 2). Dev owns the Route 53 hosted zone; prod data-
# sources it. After the first dev apply, take the `route53_nameservers`
# output and delegate from the registrar.
root_domain      = "aurionclinical.com"
api_domain       = "api-dev.aurionclinical.com"
manage_root_zone = true

# Mutable tag is fine in dev — image_tag_mutability on the ECR repo
# allows it. Prod overrides via `-var="api_image_tag=<sha>"` at deploy.
api_image_tag = "latest"
