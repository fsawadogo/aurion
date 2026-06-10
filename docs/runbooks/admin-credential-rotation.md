# Admin / service-account credential rotation (dev)

**Why this runbook exists (issue #398):** the 2026-06-08 admin bootstrap ran
as an ECS run-task whose command **echoed the credential into CloudWatch**
(`/aurion/dev/api`). The credential had to be rotated and the log stream
deleted. The rule this runbook encodes: **a credential must never reach
argv, stdout, or a log group — not in run-task commands, not in shell
one-liners.**

## The safe rotation recipe (what to do instead)

Rotation goes through the backend's own admin API — the new value travels
only inside the TLS response body and is written straight to Secrets
Manager:

1. **Login** as any ADMIN → `POST /api/v1/auth/login` → bearer token.
2. **Resolve the target** → `GET /api/v1/admin/users` → `user_id`.
3. **Rotate** → `POST /api/v1/admin/users/{user_id}/reset-password`
   (no body). The response carries a server-generated `temp_password`;
   the endpoint also clears lockouts and writes
   `ADMIN_PASSWORD_RESET_ISSUED` + `PASSWORD_CHANGED` audit events.
4. **Store** the value in Secrets Manager **via `file://` indirection or
   stdin — never `--secret-string '<value>'` on the command line** (argv
   is visible to `ps` and shell history):

   ```bash
   # secret JSON written to a temp file by the calling script, then:
   aws secretsmanager put-secret-value \
     --region ca-central-1 \
     --secret-id aurion/dev/portal-admin-credential \
     --secret-string file:///tmp/cred.json && rm -f /tmp/cred.json
   ```

5. **Verify** old value rejected / new value accepted via two login
   attempts. Never print either value; assert on the presence of
   `access_token` only.

The dev portal admin credential lives at
**`aurion/dev/portal-admin-credential`** (Secrets Manager, ca-central-1).
Read it with:

```bash
aws secretsmanager get-secret-value --region ca-central-1 \
  --secret-id aurion/dev/portal-admin-credential \
  --query SecretString --output text
```

## If a credential ever lands in CloudWatch again

1. Locate it: `aws logs filter-log-events --log-group-name /aurion/dev/api
   --filter-pattern '"<the-value>"'` → note the stream name(s).
2. **Rotate first** (recipe above) — deletion without rotation leaves a
   live credential that was already read by whoever saw the log.
3. Delete the stream(s): `aws logs delete-log-stream …`. (`/aurion/dev/api`
   has 7-day retention, but do not wait it out.)
4. Re-run the filter to confirm zero events, and sweep for siblings
   (e.g. `--filter-pattern '"temp_password"'`).
5. Fix the source so it cannot recur, and record the incident on a
   GitHub issue (pattern: #398).

## What must never appear in a run-task command

ECS run-task `command` overrides are stored in the task's CloudWatch logs
and visible in the ECS console + `describe-tasks`. Treat them like a
public channel: parameters yes, secrets never. If a bootstrap script needs
a credential, have it **generate** one internally and write it to Secrets
Manager itself, or read it from a Secrets-Manager-injected env var.
