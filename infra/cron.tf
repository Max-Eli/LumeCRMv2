# Scheduled jobs — EventBridge Scheduler → ECS RunTask invoking
# Django management commands.
#
# Why EventBridge Scheduler (not the older Rules + RunTask wiring):
# Scheduler is the AWS-recommended successor for new scheduled
# workloads. It supports cron + rate expressions, flexible time
# windows, retry policies, dead-letter queues, and is priced cheaper
# per-invocation than the legacy Rule-based path.
#
# All schedules run on the same `backend` task definition as the
# long-running service — they share the image, env vars, secret
# bindings, and IAM scope. The difference is just the container
# `command` override that swaps gunicorn for `python manage.py …`.
# Using the task-definition family (no revision suffix) means
# scheduler invocations always pick up the latest deploy, exactly
# like the running service does.
#
# Schedules run in the same private subnets + security group as the
# backend service so they reach RDS, Secrets Manager, and the
# internet (Twilio) the same way the API does.

# ── Scheduler IAM role ─────────────────────────────────────────────
#
# EventBridge Scheduler needs its own role (separate from the task
# roles) so it can call `ecs:RunTask` on our behalf + `iam:PassRole`
# the execution + task roles into the launched task. Scoped tightly
# to those exact role ARNs + the backend task-def family.

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    # Confused-deputy prevention: only schedules in our account can
    # assume this role. Without `aws:SourceAccount`, any other account
    # whose schedules happen to reference this role ARN could call us.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
  tags               = { Name = "${local.name_prefix}-scheduler" }
}

data "aws_iam_policy_document" "scheduler" {
  # Launch tasks on our cluster. Resource is the task-definition
  # family (any revision) — we never want to pin a schedule to a
  # specific old revision when a new deploy ships.
  #
  # ARN is constructed from parts rather than referencing
  # `aws_ecs_task_definition.backend` directly, because the
  # task-definition resource drifts from Terraform state every time
  # CI deploys a new image (the running service ignores
  # `task_definition` changes). Referencing it here would pull that
  # drift into every cron-related apply.
  statement {
    sid     = "RunBackendTask"
    actions = ["ecs:RunTask"]
    resources = [
      "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name_prefix}-backend:*",
    ]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }

  # Pass the task + execution roles into the launched task. This is
  # what `RunTask` needs to bind the IAM identity inside the
  # container — without it the task fails to start with an
  # AccessDenied on the role.
  statement {
    sid     = "PassTaskRoles"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.backend_task.arn,
      aws_iam_role.ecs_execution.arn,
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "${local.name_prefix}-scheduler"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

# Backend task-def ARN at the family level — Scheduler binds here
# so a deploy that ships a new revision is picked up automatically
# on the next invocation. Constructed manually (rather than
# referenced) so the task-definition CI drift doesn't bleed into
# cron-related Terraform plans.
locals {
  backend_task_family_arn = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name_prefix}-backend"
}

# ── Reminder cron — every 30 minutes ──────────────────────────────
#
# `send_appointment_reminders` finds appointments 23–25 hours out
# (24h window ± 1h slop) whose reminder SMS hasn't yet been sent and
# fires them. Idempotent: a single appointment never gets two
# reminders even if the schedule fires twice (e.g. a retry after a
# transient failure).

resource "aws_scheduler_schedule" "send_appointment_reminders" {
  name = "${local.name_prefix}-send-appointment-reminders"

  flexible_time_window {
    mode = "OFF"
  }

  # `rate(30 minutes)` — fires every 30 min. The management command
  # uses a ±1h slop window, so missing one run (e.g. during a deploy)
  # is fully recoverable on the next invocation.
  schedule_expression          = "rate(30 minutes)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = local.backend_task_family_arn
      task_count          = 1
      launch_type         = "FARGATE"
      platform_version    = "LATEST"
      propagate_tags      = "TASK_DEFINITION"

      network_configuration {
        subnets          = aws_subnet.private[*].id
        security_groups  = [aws_security_group.backend.id]
        assign_public_ip = false
      }
    }

    # Container override: swap gunicorn for the management command.
    # Everything else (image, env, secrets, IAM, networking) comes
    # from the task definition.
    input = jsonencode({
      containerOverrides = [
        {
          name    = "backend"
          command = ["python", "manage.py", "send_appointment_reminders"]
        },
      ],
    })

    retry_policy {
      maximum_event_age_in_seconds = 600 # 10 min — don't retry stale events
      maximum_retry_attempts       = 2
    }
  }
}

# ── Review-request cron — every 30 minutes, offset by 15 min ──────
#
# `send_review_requests` iterates tenants that have enabled the
# automation + set a Google review URL, and fires the SMS for
# completed appointments whose `completed_at` is in
# `(hours_after - 1) ≤ Δ ≤ (hours_after + 1)` ago.
#
# Offset by 15 min so the two crons don't both spin up tasks at the
# top of every half-hour — cheaper Fargate cold-start contention and
# easier to read in CloudWatch.

resource "aws_scheduler_schedule" "send_review_requests" {
  name = "${local.name_prefix}-send-review-requests"

  flexible_time_window {
    mode = "OFF"
  }

  # cron expression so we can phase 15 min off the reminder schedule.
  # Fires at :15 and :45 of every hour, UTC.
  schedule_expression          = "cron(15,45 * * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = local.backend_task_family_arn
      task_count          = 1
      launch_type         = "FARGATE"
      platform_version    = "LATEST"
      propagate_tags      = "TASK_DEFINITION"

      network_configuration {
        subnets          = aws_subnet.private[*].id
        security_groups  = [aws_security_group.backend.id]
        assign_public_ip = false
      }
    }

    input = jsonencode({
      containerOverrides = [
        {
          name    = "backend"
          command = ["python", "manage.py", "send_review_requests"]
        },
      ],
    })

    retry_policy {
      maximum_event_age_in_seconds = 600
      maximum_retry_attempts       = 2
    }
  }
}


# ── Meta long-lived token refresh — daily ──────────────────────────
#
# Instagram Login long-lived tokens expire after 60 days. Meta's
# /refresh_access_token endpoint extends them for another 60 days
# as long as the token is at least 24h old + not yet expired.
# Without this cron, every connected tenant silently loses Instagram
# access on day 60.
#
# Runs once a day at 11:30 UTC (off-peak for both us-east-1 ECS
# capacity and Meta's API). The management command operates on a
# 14-day expiry window, so missing a few days of runs is recoverable.
# Permanent refresh failures (token expired, session revoked) flip
# the Connection to ERROR so the operator sees "reconnect required"
# in the integrations UI — no silent breakage.

resource "aws_scheduler_schedule" "refresh_meta_tokens" {
  name = "${local.name_prefix}-refresh-meta-tokens"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "cron(30 11 * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = local.backend_task_family_arn
      task_count          = 1
      launch_type         = "FARGATE"
      platform_version    = "LATEST"
      propagate_tags      = "TASK_DEFINITION"

      network_configuration {
        subnets          = aws_subnet.private[*].id
        security_groups  = [aws_security_group.backend.id]
        assign_public_ip = false
      }
    }

    input = jsonencode({
      containerOverrides = [
        {
          name    = "backend"
          command = ["python", "manage.py", "refresh_meta_tokens"]
        },
      ],
    })

    retry_policy {
      maximum_event_age_in_seconds = 3600 # 1h — daily, so wider window is fine
      maximum_retry_attempts       = 3
    }
  }
}
