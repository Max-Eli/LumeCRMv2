# Application Load Balancer + listener rules + ACM cert.
#
# Single ALB serves both apps via host-based routing:
#
#   api.<domain>      backend target group (port 8000)
#   *.<domain>        frontend target group (port 3000)
#
# HTTP (80) redirects to HTTPS (443) at the listener. The wildcard
# subdomain pattern (`*.<domain>`) is the per-tenant URL shape --
# `acmespa.lumecrm.com`, `bobsmedspa.lumecrm.com`, etc.
#
# DNS lives at the registrar (Hostinger) -- not Route 53. The
# operator adds the ACM validation CNAMEs manually after `terraform
# apply` outputs them, then the apply finishes when ACM detects them
# (validation resource below blocks until cert is ISSUED).

# ── ACM certificate ────────────────────────────────────────────────
#
# A single wildcard SAN (`*.<domain>`) covers `api.<domain>` AND
# every per-tenant subdomain (`acmespa.<domain>`, etc.) since `api.`
# is one level deep. We do NOT include the apex (`<domain>` itself)
# because that's served by the marketing site, not the CRM.

resource "aws_acm_certificate" "main" {
  domain_name       = "*.${var.domain_name}"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${local.name_prefix}-acm" }
}

# Wait for the cert to enter ISSUED state. Without `validation_record_fqdns`,
# the resource polls ACM until validation succeeds via whatever means
# (the operator adding the CNAME at Hostinger). Times out at the
# provider default (45 min) -- well past Hostinger's typical DNS
# propagation window (~1-15 min).
resource "aws_acm_certificate_validation" "main" {
  certificate_arn = aws_acm_certificate.main.arn
}

# ── ALB ────────────────────────────────────────────────────────────

resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # Drop invalid headers -- defense vs. request-smuggling style abuse.
  drop_invalid_header_fields = true

  # Idle timeout default (60s) is fine for our workload; long-poll
  # endpoints can override per-target if we ever add them.
  idle_timeout = 60

  enable_http2               = true
  enable_deletion_protection = var.environment == "prod"

  # ALB access logs disabled at v1 launch -- AWS's bucket-policy
  # requirements for ELB log delivery have a regional/account-age
  # dependency that's frustrating to debug, and CloudTrail + Config
  # already give us the audit posture we need for HIPAA. Re-enable
  # in Phase 0c.6 once we have time to handle the dual-principal /
  # service-principal policy quirk per region.
  #
  # access_logs {
  #   bucket  = aws_s3_bucket.alb_logs.id
  #   prefix  = "alb"
  #   enabled = true
  # }

  tags = { Name = "${local.name_prefix}-alb" }
}

# ── Target groups ──────────────────────────────────────────────────

resource "aws_lb_target_group" "backend" {
  name        = "${local.name_prefix}-backend-tg"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip" # Fargate awsvpc mode targets by IP, not instance
  vpc_id      = aws_vpc.main.id

  # `/healthz` does a SELECT 1; ALB pulls a task out of rotation
  # without restarting it (that's the liveness probe's job).
  health_check {
    path                = "/healthz"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = { Name = "${local.name_prefix}-backend-tg" }
}

resource "aws_lb_target_group" "frontend" {
  name        = "${local.name_prefix}-frontend-tg"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    # Next standalone serves the index page on /; cheap and never 500s.
    path                = "/"
    matcher             = "200-399"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = { Name = "${local.name_prefix}-frontend-tg" }
}

# ── Listeners ──────────────────────────────────────────────────────

# HTTP → HTTPS redirect at port 80.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# HTTPS — default is the frontend; api.<domain> is host-routed to
# the backend.
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  # TLS 1.2+ only. Avoid `ELBSecurityPolicy-2016-08` and other
  # legacy policies that allow TLS 1.0 / 1.1.
  ssl_policy      = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn = aws_acm_certificate_validation.main.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# Backend gets its own host (api.<domain>). We give it priority 100
# so when we add Phase 1 routing rules (e.g. /book/* → frontend) the
# numeric headroom is there.
resource "aws_lb_listener_rule" "backend_api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    host_header {
      values = ["api.${var.domain_name}"]
    }
  }
}
