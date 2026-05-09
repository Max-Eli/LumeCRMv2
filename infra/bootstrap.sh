#!/usr/bin/env bash
#
# One-shot bootstrap for the Terraform remote-state backend.
#
# Creates:
#   1. Customer-managed KMS key + alias for the state bucket
#   2. S3 bucket (versioned, encrypted, public-access-blocked) for state
#   3. DynamoDB table for state locking
#
# Run ONCE per AWS account, BEFORE the first `terraform init`. Idempotent —
# re-runs are safe and surface "already exists" warnings.
#
#   $ ./bootstrap.sh
#
# Requires the AWS CLI configured with credentials that have:
#   - kms:CreateKey, kms:CreateAlias
#   - s3:CreateBucket, s3:PutBucketEncryption, s3:PutBucketVersioning, s3:PutPublicAccessBlock
#   - dynamodb:CreateTable
#
# After this completes, `terraform init` will pick up the backend
# defined in `backend.tf`.

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
BUCKET_NAME="lume-crm-tfstate-prod"
TABLE_NAME="lume-crm-tfstate-locks"
KEY_ALIAS="alias/lume-crm-tfstate"

echo "Region:    $REGION"
echo "Bucket:    $BUCKET_NAME"
echo "Lock tbl:  $TABLE_NAME"
echo "KMS alias: $KEY_ALIAS"
echo ""

# ── 1. KMS key ──────────────────────────────────────────────────────

if aws kms describe-key --key-id "$KEY_ALIAS" --region "$REGION" >/dev/null 2>&1; then
  echo "✓ KMS alias $KEY_ALIAS already exists — skipping create."
else
  echo "Creating KMS key for state encryption…"
  KEY_ID=$(aws kms create-key \
    --region "$REGION" \
    --description "Lume CRM Terraform state encryption" \
    --key-usage ENCRYPT_DECRYPT \
    --key-spec SYMMETRIC_DEFAULT \
    --tags TagKey=Project,TagValue=lume-crm TagKey=Purpose,TagValue=tfstate \
    --query 'KeyMetadata.KeyId' \
    --output text)

  aws kms enable-key-rotation \
    --region "$REGION" \
    --key-id "$KEY_ID"

  aws kms create-alias \
    --region "$REGION" \
    --alias-name "$KEY_ALIAS" \
    --target-key-id "$KEY_ID"

  echo "✓ KMS key created: $KEY_ID"
fi

# ── 2. S3 bucket ────────────────────────────────────────────────────

if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "✓ S3 bucket $BUCKET_NAME already exists — skipping create."
else
  echo "Creating S3 bucket for state…"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket \
      --bucket "$BUCKET_NAME" \
      --region "$REGION"
  else
    aws s3api create-bucket \
      --bucket "$BUCKET_NAME" \
      --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  echo "✓ Bucket created."
fi

aws s3api put-bucket-versioning \
  --bucket "$BUCKET_NAME" \
  --versioning-configuration Status=Enabled

aws s3api put-public-access-block \
  --bucket "$BUCKET_NAME" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

aws s3api put-bucket-encryption \
  --bucket "$BUCKET_NAME" \
  --server-side-encryption-configuration "{
    \"Rules\": [{
      \"ApplyServerSideEncryptionByDefault\": {
        \"SSEAlgorithm\": \"aws:kms\",
        \"KMSMasterKeyID\": \"$KEY_ALIAS\"
      },
      \"BucketKeyEnabled\": true
    }]
  }"

echo "✓ Bucket hardened (versioning + encryption + public-access-block)."

# ── 3. DynamoDB lock table ──────────────────────────────────────────

if aws dynamodb describe-table --table-name "$TABLE_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "✓ DynamoDB table $TABLE_NAME already exists — skipping create."
else
  echo "Creating DynamoDB lock table…"
  aws dynamodb create-table \
    --region "$REGION" \
    --table-name "$TABLE_NAME" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --tags Key=Project,Value=lume-crm Key=Purpose,Value=tfstate-locks

  aws dynamodb wait table-exists --region "$REGION" --table-name "$TABLE_NAME"

  echo "✓ Lock table created."
fi

echo ""
echo "Bootstrap complete. Next:"
echo "  1. cp terraform.tfvars.example terraform.tfvars && edit"
echo "  2. terraform init"
echo "  3. terraform plan"
echo "  4. terraform apply"
