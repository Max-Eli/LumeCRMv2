# Terraform + provider version pins.
#
# We pin minor versions but allow patch increments. Bumping the AWS
# provider major (e.g. 5.x → 6.x) requires re-reading the changelog
# and validating against staging — not something we want to inherit
# automatically on a Friday-afternoon `terraform init`.

terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
