# Runbooks

Operational checklists for one-time setup and recurring prod work.
Each runbook is self-contained — read top to bottom, do the steps in
order. If a step fails, stop and surface the failure rather than
muddling through.

## Setup (run once, in order)

1. [01-aws-account-setup.md](01-aws-account-setup.md) — fresh AWS
   account hardening + BAA signing
2. [02-domain-and-route53.md](02-domain-and-route53.md) — register the
   apex domain + create the hosted zone
3. [03-github-oidc-role.md](03-github-oidc-role.md) — IAM role that
   GitHub Actions assumes for deploys (no long-lived keys)
4. [04-ses-domain-verification.md](04-ses-domain-verification.md) —
   stand up SES + DKIM + SPF + DMARC for transactional email
5. [05-first-deploy.md](05-first-deploy.md) — bootstrap state, apply
   Terraform, push initial images, run migrations

## Day-2 operations

* [10-rotate-secrets.md](10-rotate-secrets.md) — Django SECRET_KEY,
  RDS master password, GitHub Actions OIDC role
* [11-rollback.md](11-rollback.md) — revert backend or frontend to a
  previous image tag
* [12-restore-from-backup.md](12-restore-from-backup.md) — RDS PITR,
  S3 object versioning recovery

## Pre-launch

* [20-prod-launch-checklist.md](20-prod-launch-checklist.md) — every
  box that has to be ticked before the first paying spa onboards

## Tenant onboarding

* [30-zenoti-tenant-import.md](30-zenoti-tenant-import.md) — migrate a
  spa from Zenoti into prod (services / employees / customers /
  packages / memberships / appointments)
