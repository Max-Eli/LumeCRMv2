# Customer-managed KMS keys.
#
# We use customer-managed keys (not AWS-managed) for everything that
# touches PHI so the KMS audit trail is in our control + we can
# disable / rotate keys without an AWS support ticket. AWS-managed
# keys (alias/aws/rds, alias/aws/s3) work but their key policy is
# opaque to us and they auto-rotate on AWS's schedule.
#
# Three keys, one per data-domain:
#   - rds       : RDS storage + automated backups
#   - s3        : S3 PHI / media buckets
#   - secrets   : Secrets Manager values
#
# Yearly key rotation is enabled on each. Old key material stays
# usable for old ciphertext indefinitely; rotation only changes what
# new ciphertext is encrypted with.

# ── RDS ────────────────────────────────────────────────────────────

resource "aws_kms_key" "rds" {
  description             = "Lume CRM ${var.environment} - RDS Postgres encryption."
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = { Name = "${local.name_prefix}-kms-rds" }
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${local.name_prefix}-rds"
  target_key_id = aws_kms_key.rds.key_id
}

# ── S3 ─────────────────────────────────────────────────────────────

resource "aws_kms_key" "s3" {
  description             = "Lume CRM ${var.environment} - S3 PHI/media bucket encryption."
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = { Name = "${local.name_prefix}-kms-s3" }
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${local.name_prefix}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

# ── Secrets Manager ────────────────────────────────────────────────

resource "aws_kms_key" "secrets" {
  description             = "Lume CRM ${var.environment} - Secrets Manager value encryption."
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = { Name = "${local.name_prefix}-kms-secrets" }
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${local.name_prefix}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}
