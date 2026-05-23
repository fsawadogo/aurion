# RDS Backup-Restore Drill

A backup you've never restored is not a backup. This SOP proves the
RDS PITR retention actually restores by exercising it end-to-end.
Run **once pre-pilot launch**, then **quarterly**.

The drill takes ~30 minutes and costs roughly $0.10 in RDS instance
hours (one db.t3.medium for ~15 min).

## Pre-flight

```bash
# Confirm PITR is configured on the live DB
AWS_PROFILE=aurion-dev aws rds describe-db-instances \
  --db-instance-identifier aurion-db-dev \
  --query 'DBInstances[0].{retention:BackupRetentionPeriod,window:PreferredBackupWindow,latestPITR:LatestRestorableTime,storageEncrypted:StorageEncrypted}'
```

Expect:
- `BackupRetentionPeriod` ≥ 30 (dev currently set to 7d default,
  prod to 30d — note any drift)
- `LatestRestorableTime` within the last 5 minutes
- `StorageEncrypted` = `true`

If any of those fail, **fix before running the drill** — the drill
will not catch a missing backup.

## Run the drill

### 1. Pick a target time

Use a timestamp from at least 5 minutes ago to ensure the WAL log
has flushed to the backup store:

```bash
TARGET_TIME=$(date -u -v-15M +%Y-%m-%dT%H:%M:%S)
echo "Restoring to: $TARGET_TIME"
```

### 2. Restore to a NEW instance (never overwrite production)

```bash
AWS_PROFILE=aurion-dev aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier aurion-db-dev \
  --target-db-instance-identifier aurion-db-restore-drill \
  --restore-time "$TARGET_TIME" \
  --db-subnet-group-name aurion-db-subnet-group-dev \
  --vpc-security-group-ids $(AWS_PROFILE=aurion-dev aws ec2 describe-security-groups \
      --filters Name=group-name,Values=aurion-db-sg-dev --query 'SecurityGroups[0].GroupId' --output text) \
  --no-publicly-accessible \
  --no-multi-az \
  --db-instance-class db.t3.medium \
  --query 'DBInstance.{id:DBInstanceIdentifier,status:DBInstanceStatus}'
```

Restoration takes 10–20 minutes. Poll:

```bash
until [ "$(AWS_PROFILE=aurion-dev aws rds describe-db-instances \
    --db-instance-identifier aurion-db-restore-drill \
    --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null)" = "available" ]; do
  echo "waiting... ($(date +%H:%M:%S))"
  sleep 30
done
echo "available"
```

### 3. Validate

Connect from a one-off ECS task or your laptop via the bastion (if
one exists; otherwise SSM into an ECS task and use psql there):

```bash
# Get the restored endpoint
RESTORED_ENDPOINT=$(AWS_PROFILE=aurion-dev aws rds describe-db-instances \
  --db-instance-identifier aurion-db-restore-drill \
  --query 'DBInstances[0].Endpoint.Address' --output text)
echo "Restored endpoint: $RESTORED_ENDPOINT"

# The restored DB has the SAME master credentials as the source.
# Pull them from the SOURCE's master_user_secret:
RESTORED_PASSWORD=$(AWS_PROFILE=aurion-dev aws secretsmanager get-secret-value \
  --secret-id $(AWS_PROFILE=aurion-dev aws rds describe-db-instances \
      --db-instance-identifier aurion-db-dev \
      --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text) \
  --query SecretString --output text | python3 -c 'import sys,json; print(json.load(sys.stdin)["password"])')

# Test the restore (locally, with a temporary route through SSM port-forward
# OR from an ECS exec session). Confirm schema + a sample row count.
PGPASSWORD="$RESTORED_PASSWORD" psql -h "$RESTORED_ENDPOINT" -U aurion -d aurion -c "
SELECT
  (SELECT count(*) FROM users)         AS user_count,
  (SELECT count(*) FROM sessions)      AS session_count,
  (SELECT count(*) FROM note_versions) AS note_count,
  (SELECT max(version) FROM alembic_version) AS migration_head;
"
```

Expected: counts > 0, `migration_head` matches `alembic upgrade
head`'s expectation, no schema errors.

### 4. Tear down (do not leave the restored instance running)

```bash
AWS_PROFILE=aurion-dev aws rds delete-db-instance \
  --db-instance-identifier aurion-db-restore-drill \
  --skip-final-snapshot \
  --delete-automated-backups \
  --query 'DBInstance.DBInstanceStatus'
```

Verify it's actually gone after ~5 min:

```bash
AWS_PROFILE=aurion-dev aws rds describe-db-instances \
  --db-instance-identifier aurion-db-restore-drill 2>&1 | head -3
```

Should return `DBInstanceNotFound` — that's the success signal.

### 5. Log the drill

Add a row to `docs/incidents/backup-drills.md` (create if missing):

```markdown
| Date       | Operator | Target time         | Result | Notes |
|------------|----------|---------------------|--------|-------|
| 2026-05-23 | faical   | 2026-05-23T01:30:00 | PASS   | 11 users, 0 sessions (fresh dev) |
```

## Failure modes seen historically

- **`InsufficientDBInstanceCapacity`** — AWS doesn't have a db.t3.medium
  in the chosen AZ at the moment. Wait a few minutes, retry. If
  persistent, try a different instance class for the drill (e.g.
  db.t3.small) — the drill validates the BACKUP not the production
  instance class.
- **`SourceDBInstanceArnFault`** — backup retention was 0 (point-in-time
  restore disabled). Fix `backup_retention_period` in `rds.tf`.
- **Restore completes but psql connection times out** — security
  group on the restored instance doesn't allow the connection. The
  restore command above explicitly attaches the existing db sg, so
  this means your client isn't inside the VPC. Run psql from an
  ECS exec session instead.

## When to escalate

If the drill **fails**, that's a SEV-2 incident. Open a ticket,
investigate root cause, retry. Do **not** clear pilot launch until
a drill passes.
