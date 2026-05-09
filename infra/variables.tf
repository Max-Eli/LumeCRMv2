# Input variables — all knobs at the top so the rest of the config
# stays declarative. Defaults match production for the first
# environment; pass overrides via `terraform.tfvars` (see
# `terraform.tfvars.example`).

variable "aws_region" {
  description = "AWS region for all resources. SES must be HIPAA-eligible in this region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Short environment identifier — appears in resource names + tags."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["prod", "staging", "dev"], var.environment)
    error_message = "Environment must be one of: prod, staging, dev."
  }
}

variable "domain_name" {
  description = "Apex domain (e.g. 'lumecrm.com'). Tenants live at <slug>.<domain>; the API at api.<domain>."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR for the VPC. /16 gives plenty of headroom for subnets across AZs."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "How many AZs to spread subnets across. RDS Multi-AZ + ALB both need ≥ 2."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3 — RDS / ALB need at least 2; 3 is the max worth paying for at this scale."
  }
}

variable "rds_instance_class" {
  description = "RDS instance class. db.t4g.micro is fine for two spas; bump to db.t4g.small or db.t4g.medium when you onboard ~10+."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_allocated_storage_gb" {
  description = "Initial RDS storage. gp3 autoscales above this, capped at max_allocated_storage_gb."
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage_gb" {
  description = "Cap on RDS storage autoscaling. Prevents a runaway query from racking up unbounded EBS cost."
  type        = number
  default     = 100
}

variable "rds_backup_retention_days" {
  description = "Days RDS keeps automated backups. HIPAA needs ≥ 6 yr for PHI, but that retention is on a separate audit-grade snapshot pipeline (Phase 0c.6). Hot backups stay at 30 days."
  type        = number
  default     = 30
}

variable "rds_master_username" {
  description = "Master DB user. Application code uses a separate, less-privileged role."
  type        = string
  default     = "lume_admin"
}

variable "backend_image_tag" {
  description = "Tag of the backend image to deploy. Set by CI to the commit SHA."
  type        = string
  default     = "latest"
}

variable "frontend_image_tag" {
  description = "Tag of the frontend image to deploy. Set by CI to the commit SHA."
  type        = string
  default     = "latest"
}

variable "backend_cpu" {
  description = "Backend Fargate task CPU units (1024 = 1 vCPU)."
  type        = number
  default     = 512
}

variable "backend_memory_mb" {
  description = "Backend Fargate task memory."
  type        = number
  default     = 1024
}

variable "backend_desired_count" {
  description = "Desired count of backend tasks. 2 = HA across AZs."
  type        = number
  default     = 2
}

variable "frontend_cpu" {
  description = "Frontend Fargate task CPU units."
  type        = number
  default     = 256
}

variable "frontend_memory_mb" {
  description = "Frontend Fargate task memory."
  type        = number
  default     = 512
}

variable "frontend_desired_count" {
  description = "Desired count of frontend tasks. 2 = HA across AZs."
  type        = number
  default     = 2
}

variable "ses_from_address" {
  description = "Verified SES sender address (e.g. 'noreply@mail.lumecrm.com')."
  type        = string
}

variable "alarm_email" {
  description = "Email that gets paged on critical CloudWatch alarms."
  type        = string
}
