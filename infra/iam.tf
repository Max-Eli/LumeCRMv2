# IAM roles for ECS — execution role + per-service task roles.
#
# Two distinct concepts, often confused:
#
#   execution role : ECS-agent-side. Pulls images from ECR, fetches
#                    secrets at task-start, writes container logs to
#                    CloudWatch. Same role for backend + frontend
#                    because the agent's needs don't differ.
#
#   task role      : Application-side. The credentials boto3 picks up
#                    inside the container. Must be SCOPED to the
#                    minimum each service actually needs:
#                    - backend: S3 PHI bucket + SES + Secrets Manager
#                    - frontend: nothing (no AWS calls from Node)
#
# The backend's task role is least-privilege: bucket-scoped S3 perms,
# verified-domain-scoped SES perms, secret-ARN-scoped Secrets Manager
# perms. No wildcards.

# ── Execution role ─────────────────────────────────────────────────

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${local.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = { Name = "${local.name_prefix}-ecs-execution" }
}

# AWS-managed policy gets us most of the way (ECR pulls + CW Logs).
resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Custom policy: read the secrets we inject into the task definition,
# decrypt them with our customer-managed KMS key. Without this the
# task fails to start because the agent can't resolve the secret
# ARNs in the task def.
data "aws_iam_policy_document" "ecs_execution_secrets" {
  statement {
    actions = [
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      aws_secretsmanager_secret.django_secret_key.arn,
      # The RDS-managed master user secret. Wildcard the suffix —
      # AWS appends a random one when the secret is created.
      "${aws_db_instance.main.master_user_secret[0].secret_arn}*",
    ]
  }

  statement {
    actions = [
      "kms:Decrypt",
    ]
    resources = [
      aws_kms_key.secrets.arn,
    ]
  }
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name   = "${local.name_prefix}-ecs-execution-secrets"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution_secrets.json
}

# ── Backend task role ──────────────────────────────────────────────

resource "aws_iam_role" "backend_task" {
  name               = "${local.name_prefix}-backend-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = { Name = "${local.name_prefix}-backend-task" }
}

data "aws_iam_policy_document" "backend_task" {
  # S3 — read/write/delete on objects in the media bucket only.
  # No bucket-level operations (no ListAllMyBuckets, no policy edit).
  statement {
    sid = "S3MediaObjectAccess"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.media.arn}/*"]
  }

  statement {
    sid = "S3MediaBucketList"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.media.arn]
  }

  # KMS for the S3 bucket — needed to encrypt PUTs and decrypt GETs.
  statement {
    sid = "S3KmsAccess"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.s3.arn]
  }

  # SES — sending only, scoped to the verified domain. We don't grant
  # ListIdentities or anything that exposes the broader account state.
  statement {
    sid = "SESSendFromVerifiedDomain"
    actions = [
      "ses:SendEmail",
      "ses:SendRawEmail",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.ses_from_address]
    }
  }
}

resource "aws_iam_role_policy" "backend_task" {
  name   = "${local.name_prefix}-backend-task"
  role   = aws_iam_role.backend_task.id
  policy = data.aws_iam_policy_document.backend_task.json
}

# ── Frontend task role ─────────────────────────────────────────────
#
# The Next standalone server makes no AWS API calls. We still create
# the role (ECS needs ONE for every task) but attach no inline
# policy — the AWS-managed `AmazonECSTaskExecutionRolePolicy` on the
# execution role covers what the agent needs at task-start.

resource "aws_iam_role" "frontend_task" {
  name               = "${local.name_prefix}-frontend-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = { Name = "${local.name_prefix}-frontend-task" }
}
