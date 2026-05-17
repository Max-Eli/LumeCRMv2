# CloudWatch log groups + alarms.
#
# Log groups are created explicitly (not auto-created on first
# write) so we can set retention + encryption on them. Default
# CloudWatch retention is "never" — bad for cost AND HIPAA risk
# (PHI scrub failure leaks compounded indefinitely). 90 days here;
# the audit-grade long-term archive lives in S3 (Phase 0c.6).

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/lume-crm/${var.environment}/backend"
  retention_in_days = 90
  # Encrypt logs with the secrets KMS key. The key policy that grants
  # logs.<region>.amazonaws.com access is `aws_kms_key_policy.secrets`
  # below; the log group must NOT be created until that policy is
  # attached, or CreateLogGroup fails with "KMS key not allowed."
  kms_key_id = aws_kms_key.secrets.arn

  depends_on = [aws_kms_key_policy.secrets]

  tags = { Name = "${local.name_prefix}-backend-logs" }
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/lume-crm/${var.environment}/frontend"
  retention_in_days = 90
  kms_key_id        = aws_kms_key.secrets.arn

  depends_on = [aws_kms_key_policy.secrets]

  tags = { Name = "${local.name_prefix}-frontend-logs" }
}

# CloudWatch Logs needs an explicit policy to use the KMS key. Without
# this, log creation fails with "kms:Encrypt access denied" the first
# time a task tries to write.
data "aws_iam_policy_document" "logs_kms" {
  statement {
    sid    = "AllowCloudWatchLogsToUseKey"
    effect = "Allow"
    actions = [
      "kms:Encrypt*",
      "kms:Decrypt*",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:Describe*",
    ]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.amazonaws.com"]
    }
    resources = ["*"]
    condition {
      test     = "ArnEquals"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values = [
        "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/lume-crm/${var.environment}/*",
      ]
    }
  }

  # SES needs to encrypt the messages it publishes into the
  # KMS-encrypted lume-prod-ses-events SNS topic (bounce + complaint
  # event destination). Without these grants, SES rejects the
  # CreateConfigurationSetEventDestination call with "Access denied
  # to KMS key for SNS topic." ADR 0029.
  statement {
    sid    = "AllowSESToPublishToEncryptedSesEventsTopic"
    effect = "Allow"
    actions = [
      "kms:GenerateDataKey*",
      "kms:Decrypt",
    ]
    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }
    resources = ["*"]
    # Restrict the grant to the specific SNS topic — SES can only
    # use this key when publishing to lume-{env}-ses-events, never
    # for other purposes.
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.ses_events.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }

  # Account-root admin — the standard "leave a backdoor for IAM" line
  # without which a misconfigured key lockout requires AWS support.
  statement {
    sid     = "AccountRootFullAccess"
    effect  = "Allow"
    actions = ["kms:*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    resources = ["*"]
  }
}

resource "aws_kms_key_policy" "secrets" {
  key_id = aws_kms_key.secrets.id
  policy = data.aws_iam_policy_document.logs_kms.json
}

data "aws_caller_identity" "current" {}

# ── Alarms ─────────────────────────────────────────────────────────

resource "aws_sns_topic" "alarms" {
  name              = "${local.name_prefix}-alarms"
  kms_master_key_id = aws_kms_key.secrets.arn

  tags = { Name = "${local.name_prefix}-alarms" }
}

resource "aws_sns_topic_subscription" "alarm_email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# Backend service: alarm if running task count drops below desired.
# Catches "the deployment broke and ECS can't keep tasks alive" before
# the user notices.
resource "aws_cloudwatch_metric_alarm" "backend_running_tasks_low" {
  alarm_name          = "${local.name_prefix}-backend-running-tasks-low"
  alarm_description   = "Backend ECS service has fewer running tasks than desired."
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  threshold           = var.backend_desired_count
  metric_name         = "RunningTaskCount"
  namespace           = "ECS/ContainerInsights"
  period              = 60
  statistic           = "Average"
  treat_missing_data  = "breaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.backend.name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

# RDS: free storage trending toward zero. Storage autoscaling will
# kick in well before this alarms; this is a "something is very
# wrong" canary.
resource "aws_cloudwatch_metric_alarm" "rds_low_storage" {
  alarm_name          = "${local.name_prefix}-rds-low-storage"
  alarm_description   = "RDS free storage below 2 GB."
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  threshold           = 2 * 1024 * 1024 * 1024 # 2 GB in bytes
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

# RDS: connection count climbing. Fargate auto-scaling could make
# this misleading — set the threshold high enough to only fire on
# a real connection leak.
resource "aws_cloudwatch_metric_alarm" "rds_high_connections" {
  alarm_name          = "${local.name_prefix}-rds-high-connections"
  alarm_description   = "RDS DB connections > 80 (likely a connection leak)."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 80
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

# ALB: 5xx rate high. Distinguishes "backend is breaking" from
# "users are getting 4xx" (those don't page).
resource "aws_cloudwatch_metric_alarm" "alb_5xx_rate" {
  alarm_name          = "${local.name_prefix}-alb-5xx-rate-high"
  alarm_description   = "ALB target group is returning 5xxs."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 10
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}
