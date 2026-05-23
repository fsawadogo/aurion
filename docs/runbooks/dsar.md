# DSAR — Data Subject Access / Deletion Requests

Quebec Law 25 requires you to respond to data subject requests within
**30 days**. This runbook walks through both access (Article 27,
"give me my data") and deletion (Article 28, "delete my data")
requests for both physicians and — when the architecture eventually
supports patient identifiers — patients.

## Two channels, two scopes

| Requester | Scope |
|---|---|
| **Physician** (clinician account holder) | Their account record, sessions they created, notes they authored, voice biometric (on-device — see below) |
| **Patient** | All sessions / notes / frames that contain their PHI. Identification by name + DOB + visit window — patients do not have account credentials in the pilot. |

## Step-by-step — physician request

### 1. Identify the requester

Requester emails support / pilot ops with proof of identity (clinic
badge photo + cleartext name + email on file). **Match against the
Cognito user pool**, not by reply email alone (someone could spoof
a request).

```bash
AWS_PROFILE=aurion-dev aws cognito-idp admin-get-user \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username <claimed email> \
  --query '{Username:Username,Status:UserStatus,Created:UserCreateDate}'
```

If `Status` is `UNCONFIRMED` or the user doesn't exist, treat with
suspicion — bounce back asking for additional verification.

### 2. Decide: access or deletion

- **Access**: physician wants a copy of their data. Generate the
  bundle, encrypt, email a download link.
- **Deletion**: physician wants their account + PHI authored by them
  removed. Critically — sessions containing patient PHI are **not
  unilaterally deletable** by the physician under Quebec medical
  records retention rules; we delete the *account* and *their
  voice biometric*, mark their sessions as orphaned. Clinical
  safety lead reviews per-session.

### 3a. Access — generate the bundle

The backend exposes the privileged endpoint (admin role required).
Run from a trusted laptop with SSO:

```bash
AWS_PROFILE=aurion-dev curl -sS \
  -H "Authorization: Bearer <ADMIN_ID_TOKEN>" \
  -X POST \
  https://api-dev.aurionclinical.com/api/v1/privacy/dsar-export \
  -d '{"user_id":"<user-uuid>"}' \
  --output /tmp/dsar-<user-uuid>.zip
```

The export contains:
- `profile.json` — Cognito + UserModel attributes
- `sessions.csv` — all session IDs + states + timestamps the user owned
- `notes/*.json` — all immutable note versions (vFinal + history)
- `audit-events.csv` — all DynamoDB audit rows attributable to this user
- `voice-biometric-note.txt` — explicit statement that the voice
  embedding is on-device-only and never transmitted (so no bundle
  contains it — the user controls deletion via the iOS app's "Delete
  voice profile" button).

Send via 1Password Share or encrypted email. Never plain email.

Log the export to the audit table:

```bash
AWS_PROFILE=aurion-dev aws dynamodb put-item \
  --table-name aurion-audit-log-dev \
  --item '{
    "session_id": {"S": "_dsar_'$(uuidgen)'"},
    "event_timestamp": {"S": "'"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"'"},
    "event_type": {"S": "dsar_access_export"},
    "event_id":   {"S": "'$(uuidgen)'"},
    "user_id":    {"S": "<user-uuid>"},
    "requester":  {"S": "<your-admin-id>"}
  }'
```

### 3b. Deletion — purge sequence

```bash
# Disable the Cognito user FIRST. Stops new activity from the account
# while you complete the purge.
AWS_PROFILE=aurion-dev aws cognito-idp admin-disable-user \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username <email>

# Run the backend's purge endpoint. Cascades:
#   - sets UserModel.deleted_at, scrubs PII columns to NULL
#   - purges audio S3 keys owned by the user
#   - purges frame S3 keys owned by the user
#   - retains AUDIT log + note versions (legally required; PII is
#     already separated from audit events by design)
AWS_PROFILE=aurion-dev curl -sS \
  -H "Authorization: Bearer <ADMIN_ID_TOKEN>" \
  -X POST \
  https://api-dev.aurionclinical.com/api/v1/privacy/dsar-delete \
  -d '{"user_id":"<user-uuid>"}'

# Verify the purge — DynamoDB audit event "dsar_delete_completed"
# must exist with the user_id field. The backend writes this on success.
AWS_PROFILE=aurion-dev aws dynamodb query \
  --table-name aurion-audit-log-dev \
  --key-condition-expression "session_id = :sid" \
  --filter-expression "event_type = :et" \
  --expression-attribute-values '{":sid":{"S":"_dsar_<id>"},":et":{"S":"dsar_delete_completed"}}'
```

Then **delete the Cognito user** (after confirming the purge):

```bash
AWS_PROFILE=aurion-dev aws cognito-idp admin-delete-user \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username <email>
```

Voice biometric: the embedding lives in the iOS Keychain only and
was never transmitted. The user can delete it themselves via Profile
→ Voice Profile → Delete. There's nothing for us to delete server-
side. Note this in the response.

### 4. Respond to the requester

Within 30 days of the original request. Email template lives in
`docs/runbooks/templates/dsar-response-{access,deletion}.md` (TODO —
clinical safety lead reviews template wording).

### 5. Audit yourself

Every DSAR action you take is logged via the backend. After resolution:

```bash
# Pull the full audit trail for the request
AWS_PROFILE=aurion-dev aws dynamodb query \
  --table-name aurion-audit-log-dev \
  --key-condition-expression "session_id = :sid" \
  --expression-attribute-values '{":sid":{"S":"_dsar_<id>"}}'
```

Stash a printout in the clinic's DSAR register so a future Law 25
audit can verify response time + completeness.

## Patient request (when patient identification is wired)

The MVP pilot deliberately does not assign patient identifiers — every
session is "physician-owned" with no patient name field. Until the
WB20 PatientModel / patient-workspace work ships:

- A patient request requires the **clinician**'s assistance to
  identify which sessions reference them (by visit date + verbal
  context match).
- Once sessions are identified, purge per-session via
  `/privacy/purge-session`.
- This is awkward; the clinical safety committee accepted it for
  the 5-physician pilot. Patient-facing DSAR is a Tier-B
  prerequisite — closes when WB20 lands.

## SLA tracking

Quebec Law 25: 30 calendar days. Set a calendar reminder when the
request lands. If you can't meet the deadline (e.g., complex case),
write the requester before day 30 with a status update and revised
ETA — that itself is required by the law.
