# Secrets Manager — application secrets.
#
# RDS manages its own master credential (see storage.tf
# `manage_master_user_password = true`). What lives here:
#
#   - django-secret-key  : 50+ random bytes for SECRET_KEY
#
# We intentionally do NOT put DATABASE_URL here. Instead the ECS task
# definition assembles it at task-start from the RDS-managed secret
# + plaintext host/db-name. That keeps the connection string out of
# any single static secret blob.
#
# Secret values are seeded with placeholder generated values so
# `terraform apply` succeeds the first time. After bootstrap, rotate
# them via `aws secretsmanager update-secret`. The rotation is NOT
# managed by Terraform — Terraform sets the schema, ops sets the
# values.

resource "random_password" "django_secret_key" {
  length  = 64
  special = true
  # SECRET_KEY can include any printable ASCII; Django uses it for
  # cryptographic signing only.
  override_special = "!@#$%^&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "django_secret_key" {
  name                    = "${local.name_prefix}/django-secret-key"
  description             = "Lume CRM Django SECRET_KEY for ${var.environment}."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-django-secret-key" }
}

resource "aws_secretsmanager_secret_version" "django_secret_key" {
  secret_id     = aws_secretsmanager_secret.django_secret_key.id
  secret_string = random_password.django_secret_key.result

  # Terraform ignores changes after the first set. Rotate via the
  # AWS console / CLI; a Terraform-driven rotation would log the
  # plaintext into state on every run.
  lifecycle {
    ignore_changes = [secret_string]
  }
}


# ── Twilio credentials ──────────────────────────────────────────────
#
# Two Secrets Manager entries the backend task role can read:
#   - twilio-account-sid (ACxxxx..., not super sensitive but secret
#     by convention)
#   - twilio-auth-token (the API root credential; treat as sensitive)
#
# We declare the secret resource but DO NOT populate it via Terraform
# state. The first `aws secretsmanager put-secret-value` happens
# manually with the actual Twilio creds — same way operators would
# rotate credentials. `lifecycle.ignore_changes` keeps Terraform
# from churning the value on subsequent runs.

resource "aws_secretsmanager_secret" "twilio_account_sid" {
  name                    = "${local.name_prefix}/twilio-account-sid"
  description             = "Twilio Account SID for ${var.environment}. Populated via AWS console / CLI; not in Terraform state."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-twilio-account-sid" }
}

resource "aws_secretsmanager_secret" "twilio_auth_token" {
  name                    = "${local.name_prefix}/twilio-auth-token"
  description             = "Twilio Auth Token for ${var.environment}. Sensitive — full Twilio API access. Populated via AWS console / CLI."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-twilio-auth-token" }
}

# Anthropic API key — direct-API path for the AI SMS inbox
# (ADR 0032). Used when AI_LLM_PROVIDER=anthropic. Empty when
# AI_LLM_PROVIDER=bedrock (Bedrock uses IAM-role auth instead).
# Populated via AWS console / CLI, never in Terraform state.
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "${local.name_prefix}/anthropic-api-key"
  description             = "Anthropic API key for apps/ai_inbox direct-Anthropic provider. Populated via AWS console / CLI."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-anthropic-api-key" }
}


# ── Meta (Instagram + Facebook + WhatsApp) credentials ─────────────
#
# ADR 0027 wires Instagram Business DM ingestion. Four secrets per
# environment, all populated post-bootstrap via AWS CLI (see runbook
# 08-deploy-meta-integration.md):
#
#   - meta-app-id              : The Meta App ID from developers.facebook.com
#   - meta-app-secret          : The Meta App Secret (treat like a password)
#   - meta-webhook-verify-token: Random string we choose; Meta echoes
#                                back during webhook handshake
#   - integrations-fernet-key  : Fernet key for encrypting OAuth tokens
#                                at rest in the Connection.auth_data column.
#                                NEVER change without re-encrypting existing
#                                tokens — ADR 0027 §1.
#
# Same pattern as Twilio: Terraform declares the slot; ops populates
# the value via `put-secret-value`; `lifecycle.ignore_changes` keeps
# Terraform from churning subsequent values on re-apply.

resource "aws_secretsmanager_secret" "meta_app_id" {
  name                    = "${local.name_prefix}/meta-app-id"
  description             = "Meta App ID (developers.facebook.com) for ${var.environment}. ADR 0027."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-meta-app-id" }
}

resource "aws_secretsmanager_secret" "meta_app_secret" {
  name                    = "${local.name_prefix}/meta-app-secret"
  description             = "Meta App Secret for ${var.environment}. Sensitive — full Meta API access. Used for OAuth + webhook signature HMAC."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-meta-app-secret" }
}

resource "aws_secretsmanager_secret" "meta_webhook_verify_token" {
  name                    = "${local.name_prefix}/meta-webhook-verify-token"
  description             = "Verify token Meta sends back during the webhook GET handshake. We choose the value; must match what's configured in the Meta App webhook UI."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-meta-webhook-verify-token" }
}

resource "aws_secretsmanager_secret" "integrations_fernet_key" {
  name                    = "${local.name_prefix}/integrations-fernet-key"
  description             = "Fernet key for encrypting OAuth tokens at rest on Connection.auth_data. Rotate via INTEGRATIONS_FERNET_KEYS multi-key list. ADR 0027 §1."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-integrations-fernet-key" }
}


# ── Instagram Login credentials (ADR 0027 revision 2) ──────────────
#
# Instagram Login uses a separate App ID + Secret from the parent
# Meta App (above). These come from the Instagram product config
# inside the Meta App dashboard. The Instagram Login OAuth flow
# authenticates the spa directly via instagram.com — no Facebook
# account or Page required.
#
# Populated post-bootstrap via:
#   aws secretsmanager put-secret-value --secret-id lume-prod/instagram-app-id ...

resource "aws_secretsmanager_secret" "instagram_app_id" {
  name                    = "${local.name_prefix}/instagram-app-id"
  description             = "Instagram product App ID inside the Meta App (different from META_APP_ID) for ${var.environment}."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-instagram-app-id" }
}

resource "aws_secretsmanager_secret" "instagram_app_secret" {
  name                    = "${local.name_prefix}/instagram-app-secret"
  description             = "Instagram product App Secret. Sensitive — full IG Business API access via Instagram Login."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-instagram-app-secret" }
}
