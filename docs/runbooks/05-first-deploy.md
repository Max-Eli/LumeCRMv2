# 05 — First deploy

Goal: from a freshly hardened AWS account, end with a running CRM at
`https://api.lumecrm.com` answering `/healthz` with 200, and the
frontend at `https://lumecrm.com` rendering the login page.

## Prerequisites

- Runbooks 01-04 done.
- AWS CLI logged in as the IAM admin user.
- Docker Desktop installed and running locally (only needed for the
  initial bootstrap image push; after that CI takes over).
- This repo cloned locally.

## Steps

### 1. Bootstrap the Terraform state backend

```bash
cd infra
./bootstrap.sh
```

Creates the state bucket, KMS key, lock table.

### 2. Configure inputs

```bash
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
```

Fill in `domain_name`, `ses_from_address`, `alarm_email`. Defaults
for the rest are sane.

### 3. Init + plan + apply

```bash
terraform init
terraform plan -out=tfplan
# Review the plan: ~70 resources to create. Look for any "destroy"
# lines (there shouldn't be any on first apply).
terraform apply tfplan
```

The apply takes 15-25 minutes. RDS is the long pole. If anything
fails, fix and re-run — Terraform is idempotent. Common first-run
gotchas:

- ACM cert validation hangs: zone NS records aren't propagated yet
  (runbook 02 step 5). Wait, then `terraform apply` again.
- KMS key rejection in CloudWatch logs: race between key creation
  and key-policy attachment. Re-run apply once.

### 4. Capture the outputs

```bash
terraform output
```

Note especially:
- `ecr_backend_url`, `ecr_frontend_url`
- `ecs_cluster_name`
- `alb_dns_name`

### 5. Push the bootstrap images

ECS services are running with `desired_count > 0` already, but the
tasks are failing because the ECR repos are empty (`:latest` tag
doesn't exist yet). Push initial images:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Backend (must be linux/arm64 — Fargate Graviton)
cd backend
docker buildx create --use --name lume-builder 2>/dev/null || true
docker buildx build \
  --platform linux/arm64 \
  -t $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/lume-prod-backend:latest \
  --push \
  .

# Frontend
cd ../frontend
docker buildx build \
  --platform linux/arm64 \
  --build-arg NEXT_PUBLIC_API_BASE=https://api.lumecrm.com \
  -t $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/lume-prod-frontend:latest \
  --push \
  .
```

### 6. Force the services to deploy

```bash
aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-backend \
  --force-new-deployment

aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-frontend \
  --force-new-deployment

# Wait for both
aws ecs wait services-stable \
  --cluster lume-prod-cluster \
  --services lume-prod-backend lume-prod-frontend
```

### 7. Run initial migrations

ECS exec into a running backend task:

```bash
TASK_ARN=$(aws ecs list-tasks \
  --cluster lume-prod-cluster \
  --service-name lume-prod-backend \
  --query 'taskArns[0]' --output text)

# Note: requires the ECS service to have `enableExecuteCommand=true`.
# Add via aws ecs update-service if needed (one-off; most safer to
# run migrations as a separate task — see CI workflow for that path).

aws ecs execute-command \
  --cluster lume-prod-cluster \
  --task "$TASK_ARN" \
  --container backend \
  --interactive \
  --command "/bin/sh"
```

Inside the shell:

```bash
export DATABASE_URL="postgres://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
python manage.py migrate
python manage.py createsuperuser
exit
```

(Yes, ECS exec is roughed-up plumbing. The CI workflow's
`run-migrations` step is the real path; this one-shot is just for
the very first deploy where CI hasn't run yet.)

### 8. Smoke-test

```bash
# Liveness — should return 200 always
curl -i https://api.lumecrm.com/healthz/live

# Readiness — should return 200 (DB SELECT 1 succeeded)
curl -i https://api.lumecrm.com/healthz

# Frontend — should return the login page HTML
curl -i https://lumecrm.com/login
```

If any of these fail:
- DNS not propagated yet — `dig api.lumecrm.com` should return the
  ALB's IP.
- ALB target group "unhealthy" — check CloudWatch logs at
  `/lume-crm/prod/backend` for the actual error.

### 9. Capture the post-apply secrets for CI

The deploy workflows need the private subnet IDs + backend SG ID
for the migration runner step. Pull them:

```bash
cd infra

# Private subnet IDs — JSON list
terraform output -json | jq -r '
  [.private_subnet_ids.value // .vpc.value.private_subnet_ids // empty]
' || aws ec2 describe-subnets \
  --filters "Name=tag:Tier,Values=private" "Name=tag:Project,Values=lume-crm" \
  --query 'Subnets[*].SubnetId' --output json

# Backend security group ID
aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=lume-prod-backend" \
  --query 'SecurityGroups[0].GroupId' --output text
```

Add as repo secrets:
- `PRIVATE_SUBNETS_JSON` — JSON list, e.g. `["subnet-abc","subnet-def"]`
- `BACKEND_SG_JSON` — JSON list with one ID, e.g. `["sg-123"]`

### 10. Hand off to CI

From now on, deploys go through the GitHub Actions workflows. The
manual `docker build / aws ecs update-service` dance above is a
one-time thing.

## Done when

- [ ] `terraform apply` succeeded with no errors
- [ ] Both ECS services are stable (`RUNNING` task count = desired)
- [ ] `/healthz` returns 200 over HTTPS
- [ ] Login page renders at the apex
- [ ] Superuser created
- [ ] CI deploy secrets are filled in
- [ ] First push to `main` triggers a successful deploy via CI
