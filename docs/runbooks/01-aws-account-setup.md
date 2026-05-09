# 01 — AWS account setup

Goal: a fresh AWS account hardened to the point where the BAA is
signed and the first IAM user has MFA enforced. Everything later in
the runbook assumes these are done.

## Prerequisites

You have an AWS account. (Account creation itself is out of scope —
sign up at aws.amazon.com and complete payment-method verification.)

## Steps

### 1. Sign in as the root user (one time only)

* Sign in at https://console.aws.amazon.com using the root email +
  password used at signup.
* Note: this is the ONLY time we sign in as root. Every subsequent
  action goes through an IAM user or role.

### 2. Enable MFA on the root user

* Account menu → Security credentials → Multi-factor authentication
  (MFA) → Assign MFA device.
* Use a hardware key (YubiKey) if available. Authenticator app
  (1Password, Authy) is fine. SMS is NOT.

### 3. Sign the AWS BAA

* AWS Artifact (search top bar) → Reports → "AWS Business Associate
  Addendum" → Click → Accept agreement.
* Free. Activates HIPAA eligibility for the AWS-managed services
  we use: EC2, ECS, Fargate, RDS, S3, KMS, Secrets Manager, Route 53,
  ACM, CloudFront, CloudWatch, IAM, ELB, ECR, SNS.
* SES is HIPAA-eligible **in specific regions only** — us-east-1 is
  on the list. Confirm the region you've chosen here:
  https://aws.amazon.com/compliance/services-in-scope/

### 4. Configure billing alerts

* Billing dashboard → Billing preferences → enable "Receive Billing
  Alerts" + "Receive AWS Free Tier Usage Alerts".
* CloudWatch (region: us-east-1) → Billing → Create alarm:
  - Metric: EstimatedCharges, Currency USD
  - Threshold: $250 (initial; tighten or loosen based on the spa
    count and the cost projection in `infra/README.md`)
  - Action: SNS topic → email yourself

### 5. Create an IAM admin user (you, daily-driver)

* IAM → Users → Create user
  - Name: `<your-handle>-admin` (e.g. `max-admin`)
  - Console access: yes; auto-generated password; must reset on first
    login.
* Permissions: attach `AdministratorAccess` directly. (Tightening
  scope happens later via roles.)
* User detail → Security credentials → Assign MFA device. SAME
  posture as root — hardware or app, never SMS.
* Sign out of root. Sign in as this IAM user via
  `https://<account-id>.signin.aws.amazon.com/console`.

### 6. Create an OrganizationAccountAccessRole (optional but recommended)

If you ever want a separate staging account, AWS Organizations is
the right shape. Skip for now if you're solo and one-account; come
back when staging exists.

### 7. Set the password policy

* IAM → Account settings → Password policy → Edit:
  - Minimum length: 14
  - Require uppercase, lowercase, numbers, symbols
  - Password expiry: 90 days
  - Prevent password reuse: 24
  - Allow users to change their own password: on
  - Require admin password reset for new users: on

### 8. Enable CloudTrail (account-wide audit log)

* CloudTrail → Trails → Create trail
  - Name: `lume-crm-audit`
  - Storage: new S3 bucket, KMS-encrypted (let CloudTrail create the
    KMS key for you; you can swap to a customer-managed key later)
  - Log file validation: ON
  - Log events: Management events (read + write), Data events:
    leave off for now (cost), Insights events: on
* Cost: ~$2/mo for our scale. Worth it for the audit trail —
  every IAM action, every Terraform apply, every console click is
  recorded.

### 9. Enable AWS Config (HIPAA evidence)

* Config → 1-click setup → enable for all resources, all regions.
* Adds about $4/mo. Records every resource change with a timestamp,
  which is the kind of evidence a SOC 2 auditor wants.

### 10. Note the account ID

```
aws sts get-caller-identity --query Account --output text
```

Save somewhere accessible — needed in the OIDC role runbook (03).

## Done when

- [ ] Root user has MFA enforced
- [ ] BAA signed (visible in AWS Artifact under "Active agreements")
- [ ] IAM admin user exists, has MFA, can sign in
- [ ] CloudTrail recording to S3
- [ ] Billing alarm armed at $250
- [ ] Account ID written down

Next: [02-domain-and-route53.md](02-domain-and-route53.md)
