# Outputs — values useful to the runbook and the GitHub Actions
# workflows. Every output here gets read by either a human (for
# verification) or CI (for environment variables).

output "alb_dns_name" {
  description = "ALB DNS name. Add CNAME records at the registrar (Hostinger) for *.<domain> and api.<domain> pointing at this value."
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID. Only useful if a future change brings DNS into Route 53 -- A-alias records need this."
  value       = aws_lb.main.zone_id
}

# Validation records the operator must add at Hostinger before the
# ACM cert can ISSUE. `terraform apply` blocks on the validation
# resource until the records appear and ACM verifies them.
#
# Each entry: { name = "_xxx.<domain>", type = "CNAME", value = "_yyy.acm-validations.aws." }
# Hostinger UI accepts these as plain CNAME records. TTL: 1 hour
# (Hostinger default) is fine -- ACM only checks once.
output "acm_validation_records" {
  description = "Add these as CNAME records at the registrar (Hostinger) to validate the ACM cert."
  value = {
    for dvo in aws_acm_certificate.main.domain_validation_options :
    dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }
}

output "rds_endpoint" {
  description = "RDS Postgres endpoint. Used by the Django app via env."
  value       = aws_db_instance.main.address
}

output "rds_master_secret_arn" {
  description = "ARN of the RDS-managed master credential secret. CI doesn't need this; ops uses it for one-off psql access."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
  sensitive   = true
}

output "media_bucket_name" {
  description = "S3 bucket for application media (PHI uploads, signed forms, etc.)."
  value       = aws_s3_bucket.media.id
}

output "ecr_backend_url" {
  description = "Backend ECR repository URL. CI pushes images here."
  value       = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_url" {
  description = "Frontend ECR repository URL. CI pushes images here."
  value       = aws_ecr_repository.frontend.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name. CI uses this for `aws ecs update-service`."
  value       = aws_ecs_cluster.main.name
}

output "ecs_backend_service_name" {
  description = "Backend ECS service name."
  value       = aws_ecs_service.backend.name
}

output "ecs_frontend_service_name" {
  description = "Frontend ECS service name."
  value       = aws_ecs_service.frontend.name
}

output "django_secret_arn" {
  description = "ARN of the Django SECRET_KEY in Secrets Manager."
  value       = aws_secretsmanager_secret.django_secret_key.arn
  sensitive   = true
}
