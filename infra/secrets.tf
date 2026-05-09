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
