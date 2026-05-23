# Cognito User Management

Common operational tasks against the `aurion-dev` Cognito user pool.
Each task assumes `AWS_PROFILE=aurion-dev` and the operator has
ADMIN role.

The user pool ID is `ca-central-1_jWbQUgzbS` (run `terraform output
cognito_user_pool_id` to confirm if it ever changes).

## Add a new pilot user

For the initial 3 pilot users, run `scripts/provision_pilot_users.sh`.
For a one-off new user, run the same admin-create-user flow manually:

```bash
EMAIL="newdoctor@creoq.ca"
FULL_NAME="Dr. New Doctor"
ROLE="CLINICIAN"   # or ADMIN, COMPLIANCE_OFFICER, EVAL_TEAM
TEMP_PW="$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters+string.digits+"!@#$%^&*") for _ in range(16)))')"

AWS_PROFILE=aurion-dev aws cognito-idp admin-create-user \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username "$EMAIL" \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true Name=name,Value="$FULL_NAME" \
  --temporary-password "$TEMP_PW" \
  --message-action SUPPRESS

AWS_PROFILE=aurion-dev aws cognito-idp admin-add-user-to-group \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username "$EMAIL" \
  --group-name "$ROLE"

echo "Temp password: $TEMP_PW"
# Share via 1Password Share / secure channel. Never plain email / Slack DM.
```

## Reset MFA when a doctor loses their phone

This is **the most common operational request**. Their authenticator
app is gone, they can't sign in, you need to wipe the TOTP secret
so they can re-enroll on a new device.

### 1. Verify identity out-of-band

Phone call / video confirmation. **Do not skip this** — anyone can
email "I lost my phone, please reset."

### 2. Wipe the TOTP secret

```bash
EMAIL="perry@creoq.ca"

# Remove the user's software-token MFA. They keep the same Cognito
# account + password, but the TOTP enrollment is gone.
AWS_PROFILE=aurion-dev aws cognito-idp admin-set-user-mfa-preference \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username "$EMAIL" \
  --software-token-mfa-settings Enabled=false,PreferredMfa=false
```

Verify:

```bash
AWS_PROFILE=aurion-dev aws cognito-idp admin-get-user \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username "$EMAIL" \
  --query 'UserMFASettingList'
# expect: null or []
```

### 3. Tell the user

> "MFA reset. Sign in with your existing password. Cognito will
> prompt you to enroll a new authenticator app — scan the QR with
> 1Password / Authy / etc. and you're back in."

The user pool's `mfa_configuration = ON` means re-enrollment is
mandatory on their next sign-in. They cannot bypass it.

### 4. Log the action

The admin-set-user-mfa-preference call is automatically logged in
CloudTrail. For belt-and-suspenders, also add an audit row:

```bash
AWS_PROFILE=aurion-dev aws dynamodb put-item \
  --table-name aurion-audit-log-dev \
  --item '{
    "session_id": {"S": "_user_'"$EMAIL"'"},
    "event_timestamp": {"S": "'"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"'"},
    "event_type":  {"S": "mfa_reset_by_admin"},
    "event_id":    {"S": "'$(uuidgen)'"},
    "user_email":  {"S": "'"$EMAIL"'"},
    "performed_by":{"S": "<your-admin-email>"}
  }'
```

## Force a password reset

When you suspect a password may be compromised:

```bash
AWS_PROFILE=aurion-dev aws cognito-idp admin-reset-user-password \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username "$EMAIL"
```

The user's status flips to `RESET_REQUIRED`. On next sign-in,
Cognito prompts them to set a new password. MFA enrollment remains
intact.

## Deactivate a user (without deleting)

For sabbaticals, terminations-pending-investigation, etc. The user
account survives, but they can't sign in. All their historical
data + audit trail stays linked to them.

```bash
AWS_PROFILE=aurion-dev aws cognito-idp admin-disable-user \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username "$EMAIL"
```

To re-enable later: `admin-enable-user`.

## Force a user's existing sessions to expire

If you've just disabled / deactivated someone, also revoke their
active tokens so the disable is immediate (otherwise their existing
session keeps working until token expiry — up to 1h for access,
30 days for refresh).

```bash
AWS_PROFILE=aurion-dev aws cognito-idp admin-user-global-sign-out \
  --user-pool-id ca-central-1_jWbQUgzbS \
  --username "$EMAIL"
```

The next API call from their iOS app will return 401; the app should
re-route to the login screen.

## Permanent delete (DSAR)

Use the DSAR runbook — never delete a user without first running
the data-purge flow. Deletion alone leaves orphan PHI in S3 + DB.

## Common questions answered

> **Q**: A clinician's email changed (married name, new clinic email).
> Do I update Cognito or create a new user?
>
> **A**: The Cognito username field is the email and is immutable
> in our config (`username_attributes = ["email"]`). Create a new
> user with the new email, add them to the same group, then
> deactivate (NOT delete) the old one to preserve their session
> audit history under the old identity.

> **Q**: A user enrolled MFA but is locked out before the first
> sign-in (entered the wrong code 6 times during setup).
>
> **A**: Wipe their MFA (above). They get a fresh QR code on next
> sign-in. The same flow as "lost their phone."

> **Q**: Can I see who confirmed an MFA challenge / signed in?
>
> **A**: Yes — CloudTrail logs every Cognito API call. Query at
> `s3://aurion-audit-logs-dev-366034225426/cloudtrail/` (set up
> Athena for SQL-style queries).
