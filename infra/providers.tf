# AWS provider configuration.
#
# Region + default tags come from variables so a future second
# environment (staging) can reuse this exact module by pointing at a
# different region or tag set. Default tags propagate to every
# resource that supports them — invaluable for cost-allocation
# reports and "why is this resource here" audits.

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "lume-crm"
      Environment = var.environment
      ManagedBy   = "terraform"
      Repository  = "lume-crm/infra"
    }
  }
}
