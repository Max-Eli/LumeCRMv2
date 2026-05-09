# Persistent storage: RDS Postgres + S3 buckets.
#
# RDS:
#   - Postgres 16 (matches our local dev version)
#   - Encrypted at rest with the customer-managed KMS key
#   - Multi-AZ via Single-AZ-with-DR readiness — we start single-AZ
#     to halve cost; flipping to Multi-AZ is a one-line change when
#     paying-customer count justifies the ~$30/mo bump.
#   - 30-day automated backups with PITR
#   - Force SSL via parameter group
#   - Performance Insights on (free tier covers our scale)
#
# S3:
#   - One bucket for application media (PHI uploads, signed forms,
#     before/after photos eventually)
#   - One bucket for ALB access logs (compliance evidence)
#   - Both KMS-encrypted, no public access, versioning on for the
#     PHI bucket so a buggy delete is recoverable
#
# Master DB password lives in Secrets Manager; RDS is configured to
# read it directly (managed_master_user_password = true) so the
# secret never appears in Terraform state plain-text.

# ── RDS ────────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${local.name_prefix}-db-subnet-group" }
}

# Parameter group: force SSL connections + tighten logging.
resource "aws_db_parameter_group" "postgres16" {
  name        = "${local.name_prefix}-postgres16"
  family      = "postgres16"
  description = "Lume CRM Postgres 16 hardening - SSL only, slow query log."

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_statement"
    value = "ddl"
  }

  parameter {
    # Log queries slower than 1 second. Useful for spotting N+1s in
    # production without bloating the log volume.
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    # Don't log statement text in error messages — risk of PHI leak
    # to CloudWatch even with the app-side scrubber, since RDS
    # error logs go straight to CloudWatch outside our process.
    name  = "log_error_verbosity"
    value = "default"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-postgres"

  engine                = "postgres"
  engine_version        = "16.4"
  instance_class        = var.rds_instance_class
  allocated_storage     = var.rds_allocated_storage_gb
  max_allocated_storage = var.rds_max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  db_name  = "lume_crm"
  username = var.rds_master_username
  # Let RDS manage the master password in Secrets Manager — we never
  # see the plain-text. The application uses a separate non-master
  # role with bounded grants (created via post-deploy migration).
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.secrets.arn

  port = 5432

  vpc_security_group_ids = [aws_security_group.rds.id]
  db_subnet_group_name   = aws_db_subnet_group.main.name
  parameter_group_name   = aws_db_parameter_group.postgres16.name
  publicly_accessible    = false

  # Multi-AZ: off for $$ at v1. Flip to true when revenue justifies.
  multi_az = false

  # Backups
  backup_retention_period = var.rds_backup_retention_days
  backup_window           = "06:00-07:00" # UTC; ~ 1-2 AM ET
  maintenance_window      = "sun:07:00-sun:08:00"
  copy_tags_to_snapshot   = true

  # Don't auto-minor-upgrade — security patches are vetted in
  # staging first. Major upgrades are explicit ops events.
  auto_minor_version_upgrade = false

  # Performance Insights — free tier covers 7 days retention.
  performance_insights_enabled          = true
  performance_insights_kms_key_id       = aws_kms_key.rds.arn
  performance_insights_retention_period = 7

  # CloudWatch log exports — Postgres "postgresql" log only. Slow
  # query / DDL / errors land in /aws/rds/instance/<id>/postgresql.
  enabled_cloudwatch_logs_exports = ["postgresql"]

  # Deletion protection on. Removing this requires a Terraform
  # `apply` first, then a destroy — eliminates one-button accidents.
  deletion_protection = true

  # Skip final snapshot in non-prod; keep it in prod (compliance
  # requires a recoverable copy at termination).
  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${local.name_prefix}-postgres-final-${formatdate("YYYY-MM-DD", timestamp())}" : null

  apply_immediately = false # batch param-group changes to maintenance window

  tags = { Name = "${local.name_prefix}-postgres" }

  lifecycle {
    # `final_snapshot_identifier` includes a timestamp; ignore drift
    # so a re-plan doesn't try to "fix" it.
    ignore_changes = [final_snapshot_identifier]
  }
}

# ── S3: PHI / media bucket ─────────────────────────────────────────

# Random suffix prevents bucket-name collisions across regions /
# accounts and makes the name unguessable (defense vs. enumeration).
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "media" {
  bucket = "${local.name_prefix}-media-${random_id.bucket_suffix.hex}"

  tags = { Name = "${local.name_prefix}-media" }
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket                  = aws_s3_bucket.media.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true # cuts KMS API costs ~99%
  }
}

# Lifecycle: move noncurrent versions to cheaper storage after 30
# days, expire after 365. Keeps disaster recovery without paying
# hot-tier storage forever.
resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "media" {
  bucket = aws_s3_bucket.media.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# ── S3: ALB access logs ────────────────────────────────────────────

resource "aws_s3_bucket" "alb_logs" {
  bucket = "${local.name_prefix}-alb-logs-${random_id.bucket_suffix.hex}"

  tags = { Name = "${local.name_prefix}-alb-logs" }
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  bucket                  = aws_s3_bucket.alb_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ALB access logs are written by AWS's ELB account. KMS encryption
# is supported as of late 2023 but only via SSE-S3 was reliable for
# years; we use SSE-S3 here to avoid runtime errors. The data is not
# PHI (request URLs + response codes), so SSE-S3 is HIPAA-fine.
resource "aws_s3_bucket_server_side_encryption_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  rule {
    id     = "expire-old-logs"
    status = "Enabled"

    filter {}

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      # 6 years for HIPAA audit retention.
      days = 365 * 6 + 1
    }
  }
}

# Allow ELB to write access logs to this bucket.
#
# Two principals, both granted, because AWS uses two delivery models
# depending on region + account age:
#
#   1. `logdelivery.elasticloadbalancing.amazonaws.com` (Service principal)
#      -- the modern model; required for every new account in 2024+.
#      Per-account policies must include `aws:SourceAccount` to prevent
#      the confused-deputy class of attacks.
#
#   2. `arn:aws:iam::<regional-elb-account>:root` (AWS principal)
#      -- the legacy model. Some older regions still route through this.
#      `aws_elb_service_account` data source returns the regional ARN.
#
# Granting both keeps us working regardless of which model AWS routes
# our region's ALB through. AWS docs explicitly recommend this dual-
# principal pattern during the migration window.
data "aws_elb_service_account" "main" {}

resource "aws_s3_bucket_policy" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowELBLogDeliveryService"
        Effect    = "Allow"
        Principal = { Service = "logdelivery.elasticloadbalancing.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.alb_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
            "s3:x-amz-acl"      = "bucket-owner-full-control"
          }
        }
      },
      {
        Sid       = "AllowELBLegacyRegionalAccount"
        Effect    = "Allow"
        Principal = { AWS = data.aws_elb_service_account.main.arn }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.alb_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
      },
    ]
  })
}
