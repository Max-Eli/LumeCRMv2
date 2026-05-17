# SES bounce/complaint pipeline (ADR 0029).
#
# Wires together five resources that together close the §4.55
# launch-debt items:
#
#   1. SES Configuration Set — `lume-ses-events`. django-ses
#      attaches it to every SendEmail call via the
#      AWS_SES_CONFIGURATION_SET env var (set on the backend task
#      def below). Without it, NONE of the bounce/complaint event
#      publishing below would fire.
#
#   2. SNS topic — `lume-ses-events`. Configuration set's event
#      destination publishes Bounce + Complaint events here.
#
#   3. SNS subscription — HTTPS POST to our backend at
#      `/api/aws/ses-events/`. The Django receiver verifies AWS's
#      X.509 signature, handles SubscriptionConfirmation
#      automatically, and writes EmailSuppression rows.
#
#   4. SES Event Destination — connects the config set to the SNS
#      topic, filtered to Bounce + Complaint event types (we don't
#      need Delivery / Send / Open / Click in the suppression
#      pipeline; CloudWatch metrics below cover the aggregate rates
#      for those).
#
#   5. CloudWatch alarms — bounce rate 3% (warn) + 5% (critical),
#      complaint rate 0.1% (warn) + 0.3% (critical). Both alarm
#      onto the existing `aws_sns_topic.alarms` topic the founder
#      is subscribed to.

# ── Configuration set ───────────────────────────────────────────────

resource "aws_sesv2_configuration_set" "events" {
  configuration_set_name = "${local.name_prefix}-ses-events"

  reputation_options {
    reputation_metrics_enabled = true
  }

  delivery_options {
    tls_policy = "REQUIRE"
  }

  sending_options {
    sending_enabled = true
  }

  tags = { Name = "${local.name_prefix}-ses-events" }
}

# ── SNS topic for SES events (separate from alarm topic) ────────────

resource "aws_sns_topic" "ses_events" {
  name              = "${local.name_prefix}-ses-events"
  kms_master_key_id = aws_kms_key.secrets.arn

  tags = { Name = "${local.name_prefix}-ses-events" }
}

# Permit SES to publish to this SNS topic (the config-set event
# destination below assumes the SES service principal).
data "aws_iam_policy_document" "ses_events_publish" {
  statement {
    sid     = "AllowSESToPublish"
    effect  = "Allow"
    actions = ["sns:Publish"]
    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }
    resources = [aws_sns_topic.ses_events.arn]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "ses_events" {
  arn    = aws_sns_topic.ses_events.arn
  policy = data.aws_iam_policy_document.ses_events_publish.json
}

# ── Event destination wiring ────────────────────────────────────────

resource "aws_sesv2_configuration_set_event_destination" "sns" {
  configuration_set_name = aws_sesv2_configuration_set.events.configuration_set_name
  event_destination_name = "sns"

  event_destination {
    enabled = true
    # Bounce + Complaint suppress-on-receive. Delivery / Send /
    # Open / Click stay disabled here — we use CloudWatch metrics
    # below for the aggregate rates instead of per-message events.
    matching_event_types = ["BOUNCE", "COMPLAINT"]

    sns_destination {
      topic_arn = aws_sns_topic.ses_events.arn
    }
  }

  # Both policies must be in place BEFORE SES tries to publish:
  #   - aws_sns_topic_policy.ses_events grants SES sns:Publish.
  #   - aws_kms_key_policy.secrets grants SES kms:GenerateDataKey
  #     + kms:Decrypt on the topic's KMS key (added in
  #     observability.tf). Without the KMS grant, the create call
  #     itself fails with "Access denied to KMS key for SNS topic"
  #     — which is what bit CI on the first apply attempt.
  depends_on = [
    aws_sns_topic_policy.ses_events,
    aws_kms_key_policy.secrets,
  ]
}

# ── HTTPS subscription to the backend webhook ───────────────────────
#
# SNS retries the SubscriptionConfirmation message until our endpoint
# GETs the SubscribeURL it carries — handled automatically by
# `apps.marketing.views_aws_ses.SnsEventReceiverView`. No manual
# action needed after `terraform apply`.

resource "aws_sns_topic_subscription" "ses_events_https" {
  topic_arn              = aws_sns_topic.ses_events.arn
  protocol               = "https"
  endpoint               = "https://api.${var.domain_name}/api/aws/ses-events/"
  endpoint_auto_confirms = true

  # Raw delivery would strip the SNS envelope (Type / Signature /
  # SigningCertURL) — leave it OFF so the receiver can verify
  # the signature.
  raw_message_delivery = false
}

# ── CloudWatch alarms ───────────────────────────────────────────────
#
# Reputation metrics come from the SES sending identity, not the
# configuration set. AWS publishes them every minute under
# `AWS/SES`. The same alarms catch issues regardless of which
# config set tagged the original send.

resource "aws_cloudwatch_metric_alarm" "ses_bounce_rate_warn" {
  alarm_name          = "${local.name_prefix}-ses-bounce-rate-warn"
  alarm_description   = "SES bounce rate above 3%. AWS suspends sending around 5% — investigate now."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0.03
  metric_name         = "Reputation.BounceRate"
  namespace           = "AWS/SES"
  period              = 900 # 15 min — matches AWS's reputation reporting cadence
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]

  tags = { Name = "${local.name_prefix}-ses-bounce-rate-warn" }
}

resource "aws_cloudwatch_metric_alarm" "ses_bounce_rate_critical" {
  alarm_name          = "${local.name_prefix}-ses-bounce-rate-critical"
  alarm_description   = "SES bounce rate above 5%. Sending pause imminent — stop new sends until resolved."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0.05
  metric_name         = "Reputation.BounceRate"
  namespace           = "AWS/SES"
  period              = 900
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]

  tags = { Name = "${local.name_prefix}-ses-bounce-rate-critical" }
}

resource "aws_cloudwatch_metric_alarm" "ses_complaint_rate_warn" {
  alarm_name          = "${local.name_prefix}-ses-complaint-rate-warn"
  alarm_description   = "SES complaint rate above 0.1%. AWS threshold is 0.3% — investigate now."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0.001
  metric_name         = "Reputation.ComplaintRate"
  namespace           = "AWS/SES"
  period              = 900
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]

  tags = { Name = "${local.name_prefix}-ses-complaint-rate-warn" }
}

resource "aws_cloudwatch_metric_alarm" "ses_complaint_rate_critical" {
  alarm_name          = "${local.name_prefix}-ses-complaint-rate-critical"
  alarm_description   = "SES complaint rate above 0.3%. Sending pause imminent — stop new sends until resolved."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0.003
  metric_name         = "Reputation.ComplaintRate"
  namespace           = "AWS/SES"
  period              = 900
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]

  tags = { Name = "${local.name_prefix}-ses-complaint-rate-critical" }
}

# ── Outputs ─────────────────────────────────────────────────────────

output "ses_configuration_set_name" {
  description = "Pass this as AWS_SES_CONFIGURATION_SET on the backend task. Without it, no bounce/complaint events publish."
  value       = aws_sesv2_configuration_set.events.configuration_set_name
}

output "ses_events_sns_topic_arn" {
  description = "SNS topic the SES event destination publishes Bounce + Complaint events to."
  value       = aws_sns_topic.ses_events.arn
}
