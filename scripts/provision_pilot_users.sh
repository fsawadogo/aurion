#!/usr/bin/env bash
# Provision pilot physician + admin Cognito accounts.
#
# Each user gets a temporary password (must be changed on first sign-in)
# and is added to the matching role group. They enroll TOTP MFA inside
# Cognito's hosted UI on their first sign-in — no QR scan over Slack.
#
# Usage:
#   scripts/provision_pilot_users.sh
#
# Idempotent: running twice is safe — AdminCreateUser returns
# UsernameExistsException, which we swallow.

set -euo pipefail

export AWS_PROFILE=aurion-dev
USER_POOL_ID="ca-central-1_jWbQUgzbS"

# Generate a temporary password that meets the user pool's policy:
# >= 12 chars, upper + lower + digit + symbol.
gen_password() {
  python3 -c '
import secrets, string
alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
print("".join(secrets.choice(alphabet) for _ in range(16)))
'
}

provision() {
  local email="$1" full_name="$2" group="$3"
  local password
  password=$(gen_password)

  echo "→ ${email}  (${group})"

  if aws cognito-idp admin-create-user \
       --user-pool-id "${USER_POOL_ID}" \
       --username "${email}" \
       --user-attributes Name=email,Value="${email}" Name=email_verified,Value=true Name=name,Value="${full_name}" \
       --temporary-password "${password}" \
       --message-action SUPPRESS >/dev/null 2>&1
  then
    echo "  created. temporary password: ${password}"
  else
    echo "  already exists, skipping creation"
  fi

  aws cognito-idp admin-add-user-to-group \
    --user-pool-id "${USER_POOL_ID}" \
    --username "${email}" \
    --group-name "${group}" >/dev/null
  echo "  added to group: ${group}"
}

provision "perry@creoq.ca"            "Dr. Perry Gdalevitch"   "CLINICIAN"
provision "marie@creoq.ca"            "Dr. Marie Gdalevitch"   "CLINICIAN"
provision "faical@aurionclinical.com" "Faical Sawadogo"        "ADMIN"

echo
echo "Done. Distribute the temporary passwords through a secure channel"
echo "(1Password Share, encrypted email, in-person). On first sign-in, each"
echo "physician will:"
echo "  1. Enter the temp password"
echo "  2. Set their permanent password (≥12 chars + upper/lower/digit/symbol)"
echo "  3. Scan a QR with their authenticator app to enroll TOTP MFA"
echo "  4. Enter the 6-digit code to confirm enrollment"
echo "From then on: password + 6-digit code on every sign-in."
