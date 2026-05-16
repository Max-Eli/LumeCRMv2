# `infra/` — Lumè CRM AWS infrastructure

Terraform that provisions the production AWS footprint for Lumè CRM:
VPC, RDS Postgres, ECR×2, ECS+Fargate (backend + frontend), ALB, S3
buckets, Secrets Manager, KMS, CloudWatch, Route 53.

## File layout

| File                | Owns                                                         |
| ------------------- | ------------------------------------------------------------ |
| `versions.tf`       | Terraform + AWS provider version pins                        |
| `providers.tf`      | AWS provider config + default tags                           |
| `backend.tf`        | Remote state in S3 + DynamoDB locking                        |
| `variables.tf`      | All input knobs (region, sizing, domain, alarm email)        |
| `locals.tf`         | Shared name prefixes + AZ list + subnet CIDR math            |
| `network.tf`        | VPC, public/private subnets, NAT, IGW, VPC endpoints, SGs    |
| `kms.tf`            | Customer-managed KMS keys (RDS, S3, Secrets)                 |
| `iam.tf`            | ECS execution role + per-service task roles                  |
| `storage.tf`        | RDS Postgres + S3 (media + ALB-logs) buckets                 |
| `secrets.tf`        | Django SECRET_KEY in Secrets Manager                         |
| `registry.tf`       | ECR repos + lifecycle policies                               |
| `loadbalancer.tf`   | ALB + target groups + listeners + ACM cert                   |
| `compute.tf`        | ECS cluster + task defs + services                           |
| `observability.tf`  | CloudWatch log groups + SNS alarms topic + metric alarms     |
| `dns.tf`            | Route 53 records (apex + wildcard + api)                     |
| `outputs.tf`        | Useful values for the runbook + CI                           |
| `bootstrap.sh`      | One-shot script to create the state backend                  |

## First-time setup

Order matters. The chicken-and-egg dependencies (registrar →
hosted zone → ACM validation → ALB cert) are explicit.

### 0. Prerequisites

* AWS account with the BAA signed (`/runbooks/aws-account-setup.md`).
* Domain registered (any registrar — Namecheap, Squarespace,
  Route 53 Domains).
* AWS CLI configured locally with credentials that have administrative
  access. CI uses a separate, scoped role; this is just for the first
  apply.

### 1. Create the Route 53 hosted zone (manual, one-time)

The hosted zone has to exist before this Terraform can read it. Why
not put it in Terraform? Because the registrar's NS records have to
point at the zone's nameservers BEFORE Terraform can write any
record into the zone, which means the very first apply has to
create the zone with the right NS data on the first try — and any
failure leaves a half-finished zone Terraform can't reason about.

```bash
aws route53 create-hosted-zone \
  --name xn--lumcrm-5ua.com \
  --caller-reference "$(date +%s)"

# Print the NS records — copy them to your registrar.
aws route53 list-hosted-zones-by-name --dns-name xn--lumcrm-5ua.com
aws route53 get-hosted-zone --id <zone-id>
```

Update the registrar to point at those four NS records. DNS
propagation is typically <1 hr but can be longer. Once `dig NS
xn--lumcrm-5ua.com` returns the AWS nameservers, continue.

### 2. Bootstrap the state backend

```bash
cd infra
./bootstrap.sh
```

Creates the S3 bucket, KMS key, and DynamoDB lock table that
`backend.tf` points at. Idempotent.

### 3. Configure inputs

```bash
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
```

At minimum fill in:
- `domain_name`
- `ses_from_address`
- `alarm_email`

### 4. Init + plan + apply

```bash
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

The apply takes ~15-25 minutes — RDS provisioning is the slow step.

### 5. Push the first images

The ECS services start with `desired_count=0`-style behavior until
images exist. Build + push:

```bash
# From the repo root, with AWS CLI logged in to your account:
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Backend
docker build -t lume-prod-backend:bootstrap ./backend
docker tag lume-prod-backend:bootstrap $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/lume-prod-backend:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/lume-prod-backend:latest

# Frontend
docker build --build-arg NEXT_PUBLIC_API_BASE=https://api.xn--lumcrm-5ua.com \
  -t lume-prod-frontend:bootstrap ./frontend
docker tag lume-prod-frontend:bootstrap $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/lume-prod-frontend:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/lume-prod-frontend:latest
```

### 6. Force a deployment

```bash
aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-backend \
  --force-new-deployment

aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-frontend \
  --force-new-deployment
```

After ~3 min, hit the ALB DNS name (in `terraform output`):

```bash
curl https://api.xn--lumcrm-5ua.com/healthz/live
```

Should return `{"status":"alive"}`.

### 7. Run migrations (one-time)

The first deploy doesn't run migrations. Use ECS exec to run them
from inside a task:

```bash
aws ecs execute-command \
  --cluster lume-prod-cluster \
  --task <task-arn-from-list-tasks> \
  --container backend \
  --interactive \
  --command "/bin/sh"

# Inside:
python manage.py migrate
python manage.py createsuperuser
```

Hand it off to CI from then on. `/runbooks/ci-deploy.md` walks the
GitHub Actions handover.

## Day-2 operations

### Rotating the Django SECRET_KEY

```bash
aws secretsmanager update-secret \
  --secret-id lume-prod/django-secret-key \
  --secret-string "$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"

aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-backend \
  --force-new-deployment
```

Tasks restart and pick up the new secret. Rotating SECRET_KEY
invalidates every active session — schedule for a low-traffic window.

### Scaling

`backend_desired_count` and `frontend_desired_count` are independent.
Bump in `terraform.tfvars` and re-apply, or run an out-of-band
`aws ecs update-service --desired-count N` (Terraform's
`ignore_changes = [desired_count]` keeps it from being clobbered).

### Disaster recovery

* RDS automated backups: 30-day retention, point-in-time recovery
  enabled. To restore, use AWS console "Restore to point in time."
* S3 media bucket: versioning on; deleted objects can be restored
  for 365 days.
* Terraform state: bucket versioning + KMS — recover via
  `aws s3api list-object-versions` if state corrupts.

## Cost notes

Monthly ballpark, no traffic (us-east-1):

| Resource          | Monthly             |
| ----------------- | ------------------- |
| Fargate (4 tasks) | ~$60                |
| RDS t4g.micro     | ~$13                |
| NAT gateway       | ~$32 + data         |
| ALB               | ~$22                |
| VPC endpoints     | ~$21 (3 interface)  |
| S3 + KMS          | ~$3                 |
| CloudWatch logs   | ~$5                 |
| Secrets Manager   | ~$1                 |
| **Total**         | **~$155 + traffic** |

Multi-AZ RDS adds ~$13/mo. Replacing the single NAT with one-per-AZ
adds ~$32/mo (worth it once you can't tolerate one AZ taking the
service down with it).
