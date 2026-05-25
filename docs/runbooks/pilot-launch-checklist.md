# Pilot Launch Checklist

Run before the first physician signs in for a real patient encounter.
Each item is binary — either it's true now, or pilot launch waits.
Do not let "good enough" pass; clinical safety and Quebec Law 25
have no graceful-degradation mode.

## Sign-off owners

| Section | Owner |
|---|---|
| Infrastructure | CTO (Faical) |
| Clinical safety | Clinical safety lead |
| Legal / compliance | Legal counsel + DPO if appointed |
| Operations | On-call rotation owner |

## Infrastructure

- [ ] `terraform plan` against `dev.tfvars` returns **No changes**
      (no drift between code and AWS)
- [ ] `curl https://api-dev.aurionclinical.com/health` returns 200
      with a fresh deploy SHA in the iOS Config.swift release path
- [ ] All 9 CloudWatch alarms in OK state
      (`aws cloudwatch describe-alarms --query 'MetricAlarms[?StateValue!=\`OK\`].AlarmName'`
      returns empty)
- [ ] SNS subscription **confirmed** to a monitored mailbox
      (`aws sns list-subscriptions-by-topic --topic-arn $ALERTS_ARN`
      shows `SubscriptionArn` is an ARN, not `PendingConfirmation`)
- [ ] CloudTrail logging is enabled and writing
      (`aws cloudtrail get-trail-status --name aurion-dev` returns
      `IsLogging=true` with a recent `LatestDeliveryTime`)
- [ ] VPC Flow Logs writing — check
      `s3://aurion-audit-logs-dev-366034225426/flowlogs/` has objects
      from today
- [ ] S3 access logs writing — same bucket, `s3-access/audio/` etc.
      have objects from today
- [ ] All 4 AI provider secrets populated with real values
      (not empty / not placeholder) — confirm by hitting
      `POST /transcription/{id}` with a tiny WAV in a smoke session
- [ ] Most recent **backup-restore drill** within the last 90 days,
      result PASS, logged in `docs/incidents/backup-drills.md`
- [ ] No `Blocker`-status items in `.claude/state/backlog.md`

## Cognito + auth

- [ ] `mfa_configuration` on the user pool reads `ON`
- [ ] Pilot users provisioned + in correct groups
      (`aws cognito-idp list-users-in-group --group-name CLINICIAN`
      lists Dr. Perry + Dr. Marie)
- [ ] Test sign-in path performed by 1 pilot physician with TOTP
      enrolled, MFA challenge presented + accepted, dashboard reached.
      **This is the smoke test that proves the entire stack works
      end-to-end.**
- [ ] Hosted UI sign-in page renders
      `https://aurion-dev.auth.ca-central-1.amazoncognito.com/login?...`

## iOS / TestFlight

- [ ] App ID `com.aurionclinical.physician` registered in Apple Developer
      portal
- [ ] App Store Connect record exists for "Aurion"
- [ ] At least one TestFlight build with the Cognito hosted UI login
      flow has been uploaded and processed
- [ ] Pilot physicians invited as Internal Testers — each accepted
      the email, installed via TestFlight
- [ ] Each physician completed first-sign-in flow: temp password →
      new password → TOTP QR enrolled → reached dashboard
- [ ] Each physician's `UserModel` row was auto-provisioned on first
      `/auth/me` call

## Clinical / compliance (NOT engineering)

- [ ] DPIA (Data Protection Impact Assessment) signed by DPO
- [ ] Pilot consent forms reviewed by clinical safety + legal,
      distributed to physicians
- [ ] Patient consent script approved (the consent the physician
      reads to the patient before tapping Record)
- [ ] Aurion's clinical safety committee or IRB-equivalent has
      written approval for the pilot
- [ ] Cyber insurance policy active, covers AI-assisted clinical
      documentation
- [ ] If applicable: BAA / equivalent agreements with AWS, OpenAI,
      Anthropic, Google AI, AssemblyAI on file (note: Apple does
      not sign BAAs — keep PHI off iCloud sync paths)

## Operations

- [ ] On-call rotation defined for the pilot window
      (one person; coverage hours; escalation tree if they can't be
      reached)
- [ ] Incident response runbook read by every on-call (not just
      filed)
- [ ] Pilot ops mailbox / Slack channel created — physicians know
      where to flag issues
- [ ] The 3 temp passwords distributed via secure channel, each
      acknowledged received by the matching person
- [ ] Pilot kill-switch procedure tested at least once in dev
      (`aws ecs update-service --desired-count 0` to halt traffic)

## Go / no-go review

The CTO and clinical safety lead jointly review all of the above
in a single meeting. Any unchecked item = no-go. The launch is
delayed by however long the gap takes to close — there is no
"launch and fix it later" path for a clinical app.

When all items check, file the approval record in
`docs/incidents/pilot-launch-approval-YYYY-MM-DD.md` (yes,
intentionally in the incidents folder — the audit train treats
launch approval as a documented event).
