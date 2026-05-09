# Remote state backend — S3 + DynamoDB for locking.
#
# The bucket and table must already exist before `terraform init` runs
# (chicken-and-egg with the state file). `bootstrap.sh` in this
# directory creates them. After that, this block is the source of
# truth — DO NOT re-create the bucket via Terraform from another
# config; the state would loop on itself.
#
# Bucket name + table name are env-derivable (see bootstrap.sh) so a
# future staging environment can reuse this file with a workspace
# switch instead of duplicating it.

terraform {
  backend "s3" {
    bucket         = "lume-crm-tfstate-prod"
    key            = "infra/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "lume-crm-tfstate-locks"
    # Use a customer-managed KMS key for the state bucket. Bootstrap
    # creates it; the alias is fixed.
    kms_key_id = "alias/lume-crm-tfstate"
  }
}
