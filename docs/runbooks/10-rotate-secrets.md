# 10 — Rotate secrets

Recurring task. HIPAA technical safeguards expect documented rotation
on a schedule; we set the cadence at "every 90 days" or "on any
suspected exposure" (a contractor leaving with access, a laptop
lost, etc.).

## Django SECRET_KEY

Used for session signing + CSRF tokens + password reset signatures.
Rotating invalidates every active session — schedule for a
low-traffic window (Sunday early morning).

```bash
NEW=$(python -c 'import secrets; print(secrets.token_urlsafe(64))')

aws secretsmanager update-secret \
  --secret-id lume-prod/django-secret-key \
  --secret-string "$NEW"

aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-backend \
  --force-new-deployment

aws ecs wait services-stable \
  --cluster lume-prod-cluster \
  --services lume-prod-backend
```

After the deploy stabilizes, every signed-in user gets logged out on
their next request (cookie signature mismatch). They re-auth, no
data lost.

## RDS master password

The master password is in Secrets Manager and managed by RDS itself
(`manage_master_user_password = true`). Trigger a rotation:

```bash
SECRET_ARN=$(aws rds describe-db-instances \
  --db-instance-identifier lume-prod-postgres \
  --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)

# Rotates immediately; RDS picks the new password atomically.
aws secretsmanager rotate-secret --secret-id "$SECRET_ARN"
```

The backend reads the password fresh from Secrets Manager at task
start. To pick up the new value:

```bash
aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-backend \
  --force-new-deployment
```

Tasks restart one at a time (deployment_minimum_healthy_percent =
100), and there's no service-level downtime.

## GitHub Actions OIDC role permissions

The role has `AdministratorAccess` for the first cut. To tighten:

```bash
aws iam detach-role-policy \
  --role-name lume-crm-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess

# Attach a custom least-privilege policy. AWS docs at:
# https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html
```

The custom policy has to allow:
- ECR push + pull on the two repos
- ECS register-task-definition + update-service on the cluster
- IAM PassRole on the task roles
- secretsmanager:GetSecretValue on the named secrets
- For Terraform plan/apply: most of the resource-creation surface
  this stack uses

This is genuinely its own project — start from `PowerUserAccess`
when you have time, scope down from there.

## When to rotate proactively

- A team member with admin access leaves.
- A laptop with AWS CLI credentials is lost or stolen.
- Suspected secret leak (CloudWatch Logs sanity check failed, GitHub
  push that was force-pushed away contained a secret, etc.).
- Every 90 days as a baseline (calendar reminder).
