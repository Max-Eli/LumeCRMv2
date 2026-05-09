# 20 — Production launch checklist

The absolute "no PHI in this system until everything below is
green" checklist. Do not onboard the first paying spa with any
unchecked box. Many of these point at runbooks that walk the actual
work; this list is the sign-off gate.

## Account / compliance

- [ ] AWS BAA signed (runbook 01)
- [ ] Twilio BAA signed (request via Twilio support)
- [ ] SES is HIPAA-eligible in the production region (us-east-1
      confirmed at AWS docs)
- [ ] Privacy Officer + Security Officer designated
      (PROJECT_PLAN.md §3) — name in writing
- [ ] HIPAA policies adopted: access control, audit logging, breach
      notification, workforce sanction, incident response
      (templates from Aptible / HHS)
- [ ] Initial risk assessment document exists, signed
- [ ] BAA template ready for signing with each spa
- [ ] Cyber liability insurance quote in hand (defer purchase until
      first paying spa, but quote first)

## Infrastructure

- [ ] CloudTrail enabled, writing to S3, log file validation on
- [ ] AWS Config enabled, recording all resources
- [ ] Billing alarm armed
- [ ] Root account MFA enforced
- [ ] No long-lived IAM access keys exist for human users
- [ ] All IAM users have MFA
- [ ] Password policy: 14+ chars, 90-day expiry, no reuse-of-last-24
- [ ] Terraform state bucket is versioned + KMS-encrypted +
      public-access-blocked
- [ ] Production AWS account is separate from any dev account (we
      don't have dev yet — fine)

## Network + transport

- [ ] ALB listener is HTTPS-only (port 80 redirects to 443)
- [ ] TLS 1.2+ only (`ELBSecurityPolicy-TLS13-1-2-2021-06`)
- [ ] HSTS header set on all responses, preload OFF (until ready)
- [ ] No publicly accessible RDS instance
- [ ] No publicly accessible Fargate task (private subnets only)
- [ ] Wildcard ACM cert covers `*.lumecrm.com` + apex + `api.`

## Data

- [ ] All PHI tables have `tenant_id` column (PROJECT_PLAN.md §3)
- [ ] Postgres RLS policies on every PHI table — DEFERRED to Phase
      0c.6, but block the launch on this if any cross-tenant leak
      vector is unverified
- [ ] RDS encrypted at rest with customer-managed KMS
- [ ] RDS automated backups enabled, 30-day retention
- [ ] RDS deletion protection ON
- [ ] RDS `rds.force_ssl = 1` parameter is set
- [ ] Application connects with `sslmode=require`
- [ ] S3 media bucket: versioning on, KMS-encrypted, public-access
      blocked
- [ ] Audit log table records every PHI read + write with
      `tenant_id`, `user_id`, `action`, `resource`, `ip`, `timestamp`

## Application

- [ ] `DEBUG=False` in production (settings/prod.py guards on this)
- [ ] `SECRET_KEY` is in Secrets Manager, not hardcoded
- [ ] Session cookies: Secure, HttpOnly, SameSite=Lax
- [ ] CSRF cookies: Secure, HttpOnly, SameSite=Lax
- [ ] 15-min idle session timeout enforced (middleware in prod.py)
- [ ] PHI-scrubbing logger filter active (test it: trigger a logged
      exception with a fake patient email, verify it's redacted in
      CloudWatch)
- [ ] No PHI in URL query parameters (audit each public-ish route)
- [ ] No PHI in error messages returned to clients
- [ ] CSP headers strict on API, looser on admin (verify in browser
      devtools)
- [ ] X-Frame-Options DENY (verify)
- [ ] All test data deleted from production before first paying
      spa onboards

## Authentication

- [ ] MFA enforced on every staff account (django-otp)
- [ ] Password policy matches Django's defaults + length 12+
- [ ] Failed-login throttling on the login endpoint
- [ ] Logout invalidates the session server-side (verified)
- [ ] Platform admin and tenant user surfaces are separate (already
      proven via tests in apps.users)

## Email

- [ ] SES domain verified, DKIM enabled
- [ ] SPF + DMARC records published
- [ ] SES out of sandbox (production access approved)
- [ ] Bounce + complaint SNS topic wired (Phase 0c.6 if not yet)
- [ ] First test email sent to a real inbox: SPF=pass, DKIM=pass,
      DMARC=pass

## Observability

- [ ] CloudWatch log groups exist for backend + frontend, 90-day
      retention, KMS-encrypted
- [ ] CloudWatch alarms armed: backend running task count low, RDS
      free storage low, RDS connections high, ALB 5xx rate high
- [ ] Alarm SNS topic subscribed to a real inbox you actually read
- [ ] ALB access logs writing to S3, lifecycle policy in place

## Operational readiness

- [ ] All runbooks (01-12) read top-to-bottom by the on-call person
- [ ] First-deploy runbook walked successfully
- [ ] Rollback procedure tested at least once (deploy a "v0.0.1
      bad" tag, roll back to previous, verify)
- [ ] PITR restore procedure tested at least once (restore yesterday
      to a temp instance, verify it works, delete temp)
- [ ] Postmortem template exists (even a one-pager)
- [ ] On-call rotation defined (currently: solo dev — that's a
      single point of failure; document it explicitly so a future
      hire / contractor knows what to inherit)

## Pre-launch acceptance test

The first paying spa is a known-friendly partner; treat the
onboarding itself as the final acceptance test:

- [ ] Spa is signed up via the platform admin flow
- [ ] First user (owner) can log in
- [ ] Owner adds a second user (manager); manager logs in
- [ ] Both users have MFA enrolled before any PHI is entered
- [ ] One real customer added, one appointment booked, one form
      sent + signed
- [ ] Audit log has corresponding entries with the right tenant_id

When every box is checked, ship it. Until then, the staging-quality
banner stays on the login page.
