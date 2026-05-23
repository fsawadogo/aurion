# Web Portal Deployment

The admin portal lives at `var.web_portal_subdomain`
(default: `portal-dev.aurionclinical.com`) and is hosted on AWS
Amplify with the Next.js app sourced from `web/` in this repo.

This runbook covers first-time provisioning and the steady-state
deploy / rollback flow. For everyday code pushes, you do not run
any command — Amplify auto-builds on every push to `main`.

## First-time provisioning

Assumes Phase 2 (DNS + ACM for the API subdomain) is already done.

### 1. Mint a GitHub Personal Access Token for Amplify

Amplify's GitHub source connector needs a classic PAT with `repo`
scope. (The modern GitHub App connector isn't supported by the
`aws_amplify_app` Terraform resource at the time of writing.)

- Go to https://github.com/settings/tokens (classic, not fine-grained)
- Generate new token, scope: `repo`
- Set expiry to **90 days** — calendar a rotation
- Copy the token; you only see it once

### 2. Inject the token into the Terraform run

Do **not** put the token in `dev.tfvars` (committed file). Pass via
env var only:

```bash
export TF_VAR_amplify_github_access_token='ghp_xxxxxxxxxxxxxxxx'

cd infrastructure
terraform plan  -var-file=environments/dev.tfvars
terraform apply -var-file=environments/dev.tfvars
```

The plan should show 5 new resources:

- `aws_route53_zone.portal`
- `aws_amplify_app.web_portal[0]`
- `aws_amplify_branch.main[0]`
- `aws_amplify_domain_association.portal[0]`
- `aws_iam_role.amplify_service[0]` + role attachment

### 3. Delegate the subdomain at Cloudflare

After apply, grab the new nameservers:

```bash
terraform output portal_nameservers
```

In Cloudflare DNS for `aurionclinical.com`, add **4 NS records** for
the subdomain (`portal-dev`) — one per nameserver from the output.
TTL 5 min for the first delegation, raise after it's stable. Same
delegation pattern as `api-dev` from Phase 2.

Verify with:

```bash
dig +short NS portal-dev.aurionclinical.com
# expect: 4 ns-XXX.awsdns-XX.* lines from AWS
```

### 4. Wait for Amplify domain verification

Amplify creates the verification records inside the Route 53 zone
automatically. Once the NS delegation propagates (~5–30 min),
verification finishes:

```bash
aws amplify get-domain-association \
  --app-id $(terraform output -raw amplify_app_id) \
  --domain-name $(terraform output -raw portal_url | sed 's|https://||') \
  --query 'domainAssociation.domainStatus'
# expect: AVAILABLE
```

### 5. Smoke-test

```bash
curl -I "$(terraform output -raw portal_url)"
# expect: HTTP/2 200 with the X-Robots-Tag noindex header
```

Open in a browser; you should land on the login page.

## Deploy a code change

Push to `main`. Amplify webhook fires, build kicks off (~3-5 min for
a clean build, ~1 min with cache). Watch:

```bash
aws amplify list-jobs \
  --app-id $(terraform output -raw amplify_app_id) \
  --branch-name main \
  --max-results 5 \
  --query 'jobSummaries[].{id:jobId,status:status,start:startTime}'
```

If the build fails, check the job's logs:

```bash
aws amplify get-job \
  --app-id $(terraform output -raw amplify_app_id) \
  --branch-name main \
  --job-id <id>
```

## Rollback

Two options, fastest first.

### Option A — pin to a previous green commit

Force Amplify to redeploy the previous successful job:

```bash
aws amplify start-job \
  --app-id $(terraform output -raw amplify_app_id) \
  --branch-name main \
  --job-type RETRY \
  --job-id <previous-green-job-id>
```

This takes ~3 min and doesn't require a code revert.

### Option B — revert the commit on `main`

```bash
git revert <bad-sha>
git push origin main
```

Triggers a fresh build with the reverted code. Takes ~5 min.

If both fail and you need to stop serving traffic:

```bash
# Stop auto-builds while you investigate
aws amplify update-branch \
  --app-id $(terraform output -raw amplify_app_id) \
  --branch-name main \
  --no-enable-auto-build

# To remove serving entirely (drastic), remove the domain
# association — DNS lookups return NXDOMAIN-equivalent at the
# Amplify edge:
#   terraform destroy -target=aws_amplify_domain_association.portal
```

## Rotation: the GitHub PAT

PATs expire. To rotate:

1. Mint a new PAT (step 1 above)
2. `export TF_VAR_amplify_github_access_token='ghp_new'`
3. `terraform apply -var-file=environments/dev.tfvars`

Terraform updates the token in-place on the existing
`aws_amplify_app`. No downtime; the next build uses the new token.

Schedule the next rotation 90 days out.

## Cost notes

Amplify hosting at pilot scale (~5 users, low traffic):

- Build minutes: ~5 builds/week × 4 min × $0.01/min ≈ $0.20/week
- Hosting: ~100 MB/month egress × $0.15/GB ≈ $0.02/month
- Lambda@Edge (SSR): negligible (~$0.01/month)

Total: well under $5/month for the pilot window. The bigger cost
once we scale is request volume — keep an eye on `data served`
and `data stored` in the Amplify console.

## Failure modes seen historically

(empty — fill in once the portal has been running for a quarter)
