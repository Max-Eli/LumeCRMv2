# ECS cluster + task definitions + services for backend and frontend.
#
# Container Insights ON for the cluster — gives us the
# RunningTaskCount metric the observability alarms rely on.
#
# Both services run in private subnets (no public IP) and reach the
# internet via the NAT gateway. ECR pulls bypass the NAT thanks to
# the VPC endpoints in network.tf.

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = "${local.name_prefix}-cluster" }
}

# Capacity providers — Fargate for steady tasks, FARGATE_SPOT for
# anything we add later that's tolerant of interruption (currently
# nothing). Defining both now makes the future easier.
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# ── Backend task definition ────────────────────────────────────────

# DATABASE_URL is built by the entrypoint script at task-start from
# the RDS-managed secret + plaintext host/db. We pass the secret
# JSON path syntax (`secret-arn:JSONKey::`) so the agent extracts
# just the password.

locals {
  # The RDS-managed secret is a JSON blob with `username`, `password`.
  rds_secret_arn = aws_db_instance.main.master_user_secret[0].secret_arn

  backend_container_def = jsonencode([
    {
      name      = "backend"
      image     = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"
      essential = true

      portMappings = [
        { containerPort = 8000, protocol = "tcp" },
      ]

      environment = [
        { name = "DJANGO_SETTINGS_MODULE", value = "lume_crm.settings.prod" },
        { name = "DEBUG", value = "0" },
        # ALLOWED_HOSTS is "*" because ALB health checks send the
        # task's private IP as the Host header (e.g. "10.0.11.201:8000"),
        # which Django would otherwise reject with 400. Safe at our
        # layer because the ALB listener rules already restrict which
        # Host headers reach the backend service -- public requests
        # only arrive with a verified `*.<domain>` host. ALLOWED_HOSTS
        # is defense-in-depth for the case where backend traffic
        # bypasses the ALB, which our network topology forbids
        # (private subnets, SG ingress only from ALB SG).
        { name = "ALLOWED_HOSTS", value = "*" },
        { name = "PUBLIC_BASE_URL", value = "https://${var.domain_name}" },
        { name = "DEFAULT_FROM_EMAIL", value = "Lumè CRM <${var.ses_from_address}>" },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "AWS_SES_REGION", value = var.aws_region },
        { name = "AWS_STORAGE_BUCKET_NAME", value = aws_s3_bucket.media.id },
        { name = "AWS_S3_KMS_KEY_ID", value = aws_kms_key.s3.arn },
        { name = "SESSION_COOKIE_DOMAIN", value = ".${var.domain_name}" },
        # CORS + CSRF allowlists. The frontend lives at
        # `*.<domain>` (per-tenant subdomains) and hits the API at
        # `api.<domain>`. Browser preflight checks an
        # Access-Control-Allow-Origin response, which django-cors-
        # headers writes only if the request's Origin matches either
        # CORS_ALLOWED_ORIGINS (exact) or CORS_ALLOWED_ORIGIN_REGEXES.
        #
        # The regex matches any single-level subdomain (alphanumeric
        # plus hyphens) of the configured domain. Hyphens in the
        # Punycode form (`xn--lumcrm-5ua`) are literal -- they're
        # outside the character class, so matched as-is.
        #
        # CSRF_TRUSTED_ORIGINS uses Django's wildcard syntax
        # (`https://*.<domain>`); the regex form isn't supported there.
        { name = "CORS_ALLOWED_ORIGIN_REGEXES", value = "^https://[a-z0-9-]+\\.${replace(var.domain_name, ".", "\\.")}$" },
        { name = "CSRF_TRUSTED_ORIGINS", value = "https://*.${var.domain_name},https://api.${var.domain_name}" },
        # Connection-string components. settings/base.py assembles
        # DATABASE_URL from these + the password secret, with proper
        # URL-encoding (RDS-generated passwords commonly contain `$`,
        # `@`, `&` etc. that break shell + URL parsing if not escaped).
        { name = "DB_HOST", value = aws_db_instance.main.address },
        { name = "DB_PORT", value = tostring(aws_db_instance.main.port) },
        { name = "DB_NAME", value = aws_db_instance.main.db_name },
        { name = "DB_USER", value = var.rds_master_username },
        # Twilio SMS — shared toll-free number visible to recipients,
        # not a secret. SID + auth-token below are pulled from
        # Secrets Manager. Status callback URL points at our public
        # webhook (mounted under /api/marketing/twilio/...).
        { name = "TWILIO_FROM_NUMBER", value = var.twilio_from_number },
        { name = "TWILIO_STATUS_CALLBACK_URL", value = "https://api.${var.domain_name}/api/marketing/twilio/status-callback/" },
        # Meta OAuth redirect URI — MUST match what's registered in
        # the Meta App dashboard (App Settings → Facebook Login →
        # Valid OAuth Redirect URIs). Mismatch = browser-visible
        # OAuth error from Facebook, not a 4xx from us.
        { name = "META_OAUTH_REDIRECT_URI", value = "https://api.${var.domain_name}/api/integrations/meta/oauth/callback/" },
      ]

      secrets = [
        {
          name      = "SECRET_KEY"
          valueFrom = aws_secretsmanager_secret.django_secret_key.arn
        },
        {
          name      = "DB_PASSWORD"
          valueFrom = "${local.rds_secret_arn}:password::"
        },
        {
          name      = "TWILIO_ACCOUNT_SID"
          valueFrom = aws_secretsmanager_secret.twilio_account_sid.arn
        },
        {
          name      = "TWILIO_AUTH_TOKEN"
          valueFrom = aws_secretsmanager_secret.twilio_auth_token.arn
        },
        # Meta Instagram integration — ADR 0027. The OAuth flow stays
        # disabled cleanly (provider.oauth_ready=False) until ALL four
        # are populated; safe to deploy in any order.
        {
          name      = "META_APP_ID"
          valueFrom = aws_secretsmanager_secret.meta_app_id.arn
        },
        {
          name      = "META_APP_SECRET"
          valueFrom = aws_secretsmanager_secret.meta_app_secret.arn
        },
        {
          name      = "META_WEBHOOK_VERIFY_TOKEN"
          valueFrom = aws_secretsmanager_secret.meta_webhook_verify_token.arn
        },
        {
          name      = "INTEGRATIONS_FERNET_KEY"
          valueFrom = aws_secretsmanager_secret.integrations_fernet_key.arn
        },
      ]

      # Container starts gunicorn directly. settings/base.py reads
      # DB_USER/DB_PASSWORD/DB_HOST/DB_PORT/DB_NAME from env and
      # builds the DATABASE_URL with URL-encoded password (see
      # base.py for why -- shell expansion mangles passwords with
      # `$`, `@`, `&`, etc., which RDS-generated values commonly
      # contain).
      command = [
        "gunicorn", "lume_crm.wsgi:application",
        "--bind", "0.0.0.0:8000",
        "--workers", "3",
        "--threads", "2",
        "--worker-tmp-dir", "/dev/shm",
        "--access-logfile", "-",
        "--error-logfile", "-",
        "--log-level", "info",
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.backend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "task"
        }
      }

      # Stop healthchecks while gunicorn is starting workers.
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/healthz/live || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }

      # Drop Linux capabilities; readonly fs is too aggressive for
      # gunicorn temp files. /tmp tmpfs covers what we need.
      readonlyRootFilesystem = false
      linuxParameters = {
        capabilities = {
          drop = ["ALL"]
        }
      }
    },
  ])
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.name_prefix}-backend"
  cpu                      = tostring(var.backend_cpu)
  memory                   = tostring(var.backend_memory_mb)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64" # Fargate Graviton — ~20% cheaper at same perf
  }

  container_definitions = local.backend_container_def

  tags = { Name = "${local.name_prefix}-backend-task" }
}

# ── Frontend task definition ───────────────────────────────────────

locals {
  frontend_container_def = jsonencode([
    {
      name      = "frontend"
      image     = "${aws_ecr_repository.frontend.repository_url}:${var.frontend_image_tag}"
      essential = true

      portMappings = [
        { containerPort = 3000, protocol = "tcp" },
      ]

      environment = [
        { name = "NODE_ENV", value = "production" },
        { name = "PORT", value = "3000" },
        { name = "HOSTNAME", value = "0.0.0.0" },
        # NEXT_PUBLIC_* are baked at build time; we don't pass them
        # at runtime. Listed here as a comment for clarity.
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.frontend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "task"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "wget --quiet --spider http://localhost:3000/ || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }

      readonlyRootFilesystem = false
      linuxParameters = {
        capabilities = {
          drop = ["ALL"]
        }
      }
    },
  ])
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name_prefix}-frontend"
  cpu                      = tostring(var.frontend_cpu)
  memory                   = tostring(var.frontend_memory_mb)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.frontend_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = local.frontend_container_def

  tags = { Name = "${local.name_prefix}-frontend-task" }
}

# ── Services ───────────────────────────────────────────────────────

resource "aws_ecs_service" "backend" {
  name            = "${local.name_prefix}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_desired_count
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  # Rolling deploys with a brief overlap period to avoid serving
  # 503s during a deploy. ALB pulls a deregistering task out of
  # rotation before stop, see deregistration_delay on the TG.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  # Don't fight CI deployments — `aws ecs update-service` from a
  # GitHub Action workflow bumps the task definition revision, but
  # we don't want a subsequent `terraform apply` to revert it.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  # Both target group and IAM policy must exist before the service
  # tries to register tasks.
  depends_on = [
    aws_lb_listener.https,
    aws_iam_role_policy.backend_task,
    aws_iam_role_policy.ecs_execution_secrets,
  ]

  tags = { Name = "${local.name_prefix}-backend-svc" }
}

resource "aws_ecs_service" "frontend" {
  name            = "${local.name_prefix}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.frontend_desired_count
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.frontend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 3000
  }

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [
    aws_lb_listener.https,
  ]

  tags = { Name = "${local.name_prefix}-frontend-svc" }
}
