# Incident Response

This runbook is the single source of truth during a live production
incident. Read it top-to-bottom; do not skip the triage section even if
the cause feels obvious.

## Severity levels

| SEV | Trigger | Response | Notify |
|---|---|---|---|
| **SEV-1** | PHI exposed to unauthorised party · consent gate bypassed · masking pipeline failure leaked an un-masked frame · CloudTrail tampering · total platform outage | Drop everything. Page the on-call. Engage kill switch immediately if data is actively flowing. | CTO, clinical safety lead, pilot clinicians, legal counsel within 4h. Law 25 may require regulator notification within 72h. |
| **SEV-2** | Single physician can't sign in · Stage 1 latency > 60s sustained · ALB 5xx > 10/min · RDS CPU pegged · ECS task crash loop | Stop new work, investigate. Restore service. | Internal Slack / mailbox. Pilot physicians if outage > 30 min. |
| **SEV-3** | Cosmetic UI bug, slow non-PHI screen, stale Spotlight result | Open backlog item, prioritise normally. | None. |

## SEV-1 immediate actions (the first 15 minutes)

### Stop the bleeding — kill switch

If you suspect PHI is actively flowing to an unauthorised destination,
**scale ECS to zero** so the backend stops accepting requests. iOS
clients will start returning errors immediately; that's the desired
behaviour. The clinician sees "couldn't reach Aurion", their session
data stays on-device.

```bash
AWS_PROFILE=aurion-dev aws ecs update-service \
  --cluster aurion-dev --service aurion-api-dev --desired-count 0 \
  --query 'service.{name:serviceName,desired:desiredCount}'
```

WAF is also available as a softer kill switch if you only want to
block external traffic but keep internal services running. Add a
deny-all rule to the web ACL via the AWS console.

### Preserve evidence

Before you start fixing anything: **do not touch CloudTrail, Flow
Logs, or DynamoDB audit-log entries**. The bucket is intentionally
versioned + KMS-locked + log-file-validation-enabled so an attacker
who somehow got write access can't cover their tracks. Don't help
them.

If you must rotate credentials (e.g., a leaked AI provider key), do
it via `aws secretsmanager rotate-secret` — never delete the old
secret version, which would destroy the audit trail of when the
compromised value was active.

### Capture state

```bash
# Snapshot the running task definition revision + ECS service state
AWS_PROFILE=aurion-dev aws ecs describe-services \
  --cluster aurion-dev --services aurion-api-dev \
  > /tmp/aurion-svc-snapshot-$(date +%Y%m%d-%H%M%S).json

# Snapshot the most recent CloudWatch alarms
AWS_PROFILE=aurion-dev aws cloudwatch describe-alarms \
  --state-value ALARM --query 'MetricAlarms[*].{name:AlarmName,state:StateValue,reason:StateReason}'

# Snapshot RDS state (in case the issue is DB-side)
AWS_PROFILE=aurion-dev aws rds describe-db-instances \
  --db-instance-identifier aurion-db-dev \
  --query 'DBInstances[0].{status:DBInstanceStatus,cpu:DBInstanceClass,storage:AllocatedStorage}'
```

## Triage decision tree

```
┌─ Did the API stop responding (/health returns non-200)?
│
├─ Yes → ECS or ALB problem
│         → Check `aws ecs describe-services` for running task count
│         → If 0: read CloudWatch Logs at /aurion/dev/api for the
│             stop reason, check IAM permissions, KMS access
│         → If ≥1 but unhealthy: read recent container logs, look
│             for OOM, panic, exception traces
│
├─ No → API healthy, something at a higher layer
│        → Check WAF metrics — sudden rate-limit lockout?
│        → Check Cognito — sign-in failures?
│        → Check the alarm that fired (`aws cloudwatch describe-alarms`)
│
└─ Suspected PHI exposure?
   → SEV-1 kill switch (above), then:
     → CloudTrail query: who accessed the affected S3 prefix recently?
       (See "CloudTrail investigation" below.)
     → Audit log query: which session ID is affected?
     → Notify clinical safety lead + legal within 4 hours.
```

## CloudTrail investigation

CloudTrail logs live in `s3://aurion-audit-logs-dev-366034225426/cloudtrail/`.
For a quick "who accessed bucket X in the last hour" query:

```bash
AWS_PROFILE=aurion-dev aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=aurion-frames-dev-366034225426 \
  --start-time "$(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ)" \
  --query 'Events[].{Time:EventTime,User:Username,Action:EventName,Source:SourceIPAddress}'
```

For deeper analysis, set up Athena over the CloudTrail bucket (~10
min one-time setup). Required for SOC2 + Law 25 audits.

## VPC Flow Logs

Flow Logs live in `s3://aurion-audit-logs-dev-366034225426/flowlogs/`.
Same Athena setup if needed. Useful for: "did anything talk to a
suspicious IP in the window of the incident."

## Rollback procedure

If the incident was caused by a recent deploy:

1. **Identify the last-known-good image tag** from CloudWatch logs
   timeline OR from `git log --oneline` to find the prior commit.

   ```bash
   AWS_PROFILE=aurion-dev aws ecr describe-images \
     --repository-name aurion-backend-dev \
     --query 'imageDetails[*].{tags:imageTags,pushed:imagePushedAt}' \
     --output table
   ```

2. **Pin the task definition to the previous tag** via Terraform
   (this is what CI does on a normal deploy):

   ```bash
   cd infrastructure
   AWS_PROFILE=aurion-dev terraform init -reconfigure \
     -backend-config=backends/dev.s3.tfbackend
   AWS_PROFILE=aurion-dev terraform apply \
     -var-file=environments/dev.tfvars \
     -var="api_image_tag=<7-char-sha>" \
     -auto-approve
   ```

3. **Verify**: `curl https://api-dev.aurionclinical.com/health` → 200.

Do NOT skip Terraform and run `aws ecs update-service` directly —
Terraform state will drift and the next CI deploy will revert you to
the broken image.

## Communication template

Post in the pilot ops channel / mailbox within 30 min:

```
SUBJECT: [Aurion SEV-{N}] {one-line description} — {STATUS}

Status:        Investigating | Identified | Mitigating | Resolved
Severity:      SEV-1 | SEV-2 | SEV-3
Started:       {YYYY-MM-DD HH:MM UTC}
Detected via:  {alarm name | physician report | health check}
Impact:        {N physicians cannot {action} | data flow halted | …}
Mitigation:    {ECS scaled to 0 | rolled back to {sha} | WAF rule added}
Next update:   {YYYY-MM-DD HH:MM UTC}
```

## Post-mortem template (within 48h of resolution)

1. **What happened** — sequence of events with timestamps from
   CloudTrail / app logs.
2. **Why it happened** — the chain of root causes, not the proximate
   one. Five whys is fine.
3. **What we did** — the actions taken, in order, including the ones
   that didn't help.
4. **What we'd do differently** — process or code changes that would
   have prevented this, caught it sooner, or shortened recovery.
5. **Action items** — concrete tickets with owners and deadlines.

Land the post-mortem as a doc in `docs/incidents/YYYY-MM-DD-{slug}.md`.
Required reading at the next pilot ops review.
